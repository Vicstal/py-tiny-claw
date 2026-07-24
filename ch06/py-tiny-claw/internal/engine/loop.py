# internal/engine/loop.py
# 对应 Go 版: internal/engine/loop.go
# 第 3 章：引入"慢思考"(Thinking Phase)：先剥夺工具强制模型规划，再放开工具让它行动。
import logging

from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ROLE_SYSTEM, ROLE_USER
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

            # ================= Phase 1: Thinking =================
            if self.enable_thinking:
                log.info("[Engine][Phase 1] 剥夺工具访问权，强制进入慢思考与规划阶段...")
                try:
                    # 传入 None 剥夺工具
                    think_resp = self.provider.generate(context_history, None)
                except Exception as e:
                    raise RuntimeError(f"Thinking 阶段生成失败: {e}") from e
                if think_resp.content != "":
                    print(f"🧠 [内部思考 Trace]: {think_resp.content}")
                    context_history.append(think_resp)

            # ================= Phase 2: Action =================
            log.info("[Engine][Phase 2] 恢复工具挂载，等待模型采取行动...")
            try:
                action_resp = self.provider.generate(context_history, available_tools)
            except Exception as e:
                raise RuntimeError(f"Action 阶段生成失败: {e}") from e

            context_history.append(action_resp)

            if action_resp.content != "":
                print(f"🤖 [对外回复]: {action_resp.content}")

            # ================= 执行判断 =================
            if len(action_resp.tool_calls) == 0:
                log.info("[Engine] 模型未请求调用工具，任务宣告完成。")
                break

            log.info("[Engine] 模型请求调用 %d 个工具...", len(action_resp.tool_calls))

            for tool_call in action_resp.tool_calls:
                log.info("  -> 🛠️ 执行工具: %s, 参数: %s", tool_call.name, tool_call.arguments)

                result = self.registry.execute(tool_call)

                if result.is_error:
                    log.info("  -> ❌ 工具执行报错: %s", result.output)
                else:
                    log.info("  -> ✅ 工具执行成功 (返回 %d 字节)", len(result.output))

                observation_msg = Message(
                    role=ROLE_USER,
                    content=result.output,
                    tool_call_id=tool_call.id,
                )
                context_history.append(observation_msg)
