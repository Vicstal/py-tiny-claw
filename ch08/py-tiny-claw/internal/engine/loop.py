# internal/engine/loop.py
# 对应 Go 版: internal/engine/loop.go
# 第 8 章：并发执行工具调用。Go 版用 goroutine + WaitGroup，
# Python 版用 ThreadPoolExecutor 实现同样的"并发执行、按序聚合"。
import logging
from concurrent.futures import ThreadPoolExecutor

from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ROLE_SYSTEM, ROLE_USER, ToolCall
from internal.tools.registry import Registry

log = logging.getLogger(__name__)


class AgentEngine:
    def __init__(self, provider: LLMProvider, registry: Registry, work_dir: str, enable_thinking: bool):
        self.provider = provider
        self.registry = registry
        self.work_dir = work_dir
        self.enable_thinking = enable_thinking

    def run(self, user_prompt: str) -> None:
        log.info("[Engine] 引擎启动，锁定工作区: %s", self.work_dir)
        log.info("[Engine] 慢思考模式 (Thinking Phase): %s", self.enable_thinking)

        context_history: list[Message] = [
            Message(
                role=ROLE_SYSTEM,
                content="You are py-tiny-claw, an expert coding assistant. You have full access to tools in the workspace.",
            ),
            Message(
                role=ROLE_USER,
                content=user_prompt,
            ),
        ]

        turn_count = 0

        while True:
            turn_count += 1
            log.info("\n========== [Turn %d] 开始 ==========", turn_count)

            available_tools = self.registry.get_available_tools()

            # Phase 1: 慢思考阶段
            if self.enable_thinking:
                log.info("[Engine][Phase 1] 剥夺工具访问权，强制进入慢思考与规划阶段...")
                try:
                    think_resp = self.provider.generate(context_history, None)
                except Exception as e:
                    raise RuntimeError(f"Thinking 阶段生成失败: {e}") from e
                if think_resp.content != "":
                    print(f"🧠 [内部思考 Trace]: \n{think_resp.content}")
                    context_history.append(think_resp)

            # Phase 2: 行动阶段
            log.info("[Engine][Phase 2] 恢复工具挂载，等待模型采取行动...")
            try:
                action_resp = self.provider.generate(context_history, available_tools)
            except Exception as e:
                raise RuntimeError(f"Action 阶段生成失败: {e}") from e

            context_history.append(action_resp)

            if action_resp.content != "":
                print(f"🤖 [对外回复]: \n{action_resp.content}")

            if len(action_resp.tool_calls) == 0:
                log.info("[Engine] 模型未请求调用工具，任务宣告完成。")
                break

            log.info("[Engine] 模型请求并发调用 %d 个工具...", len(action_resp.tool_calls))

            # ================= 并发执行逻辑 =================

            # 预分配列表以保证顺序（对应 Go 版预分配切片避免并发写入锁）
            observation_msgs: list[Message | None] = [None] * len(action_resp.tool_calls)

            def run_tool(idx: int, call: ToolCall):
                log.info("  -> [Worker-%d] 🛠️ 触发并行执行: %s", idx, call.name)

                # 执行底层工具
                result = self.registry.execute(call)

                if result.is_error:
                    log.info("  -> [Worker-%d] ❌ 工具执行报错: %s", idx, result.output)
                else:
                    log.info("  -> [Worker-%d] ✅ 工具执行成功 (返回 %d 字节)", idx, len(result.output))

                # 安全写入对应索引
                observation_msgs[idx] = Message(
                    role=ROLE_USER,
                    content=result.output,
                    tool_call_id=call.id,
                )

            # 线程池并发执行所有工具调用（对应 Go 的 go func + wg.Wait 阻塞聚合）
            with ThreadPoolExecutor(max_workers=len(action_resp.tool_calls)) as executor:
                futures = [
                    executor.submit(run_tool, i, tool_call)
                    for i, tool_call in enumerate(action_resp.tool_calls)
                ]
                for f in futures:
                    f.result()  # 阻塞等待，并让 worker 内的异常向上传播

            log.info("[Engine] 所有并发工具执行完毕，开始聚合观察结果 (Observation)...")

            # 按序追加回 Context
            for obs in observation_msgs:
                context_history.append(obs)
