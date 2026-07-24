# internal/engine/loop.py
# 对应 Go 版: internal/engine/loop.go
# 第 14 章：主循环接入 RecoveryManager —— 工具报错时拦截结果并注入救援指南。
import logging
from concurrent.futures import ThreadPoolExecutor

from internal.context.compactor import Compactor
from internal.context.composer import PromptComposer
from internal.context.recovery import RecoveryManager
from internal.context.session import Session
from internal.engine.reporter import Reporter
from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ROLE_ASSISTANT, ROLE_USER, ToolCall
from internal.tools.registry import Registry

log = logging.getLogger(__name__)


class AgentEngine:
    def __init__(self, provider: LLMProvider, registry: Registry, enable_thinking: bool, plan_mode: bool):
        self.provider = provider
        self.registry = registry
        self.enable_thinking = enable_thinking
        self.plan_mode = plan_mode
        self.compactor = Compactor(20000, 6)
        self.recovery = RecoveryManager()  # 【新增】自愈管理器

    def run(self, session: Session, reporter: Reporter | None) -> None:
        log.info("[Engine] 唤醒会话 [%s]，锁定工作区: %s (PlanMode: %s)", session.id, session.work_dir, self.plan_mode)

        composer = PromptComposer(session.work_dir, self.plan_mode)
        system_msg = composer.build()

        while True:
            available_tools = self.registry.get_available_tools()
            working_memory = session.get_working_memory(20)

            context_history: list[Message] = []
            context_history.append(system_msg)
            context_history.extend(working_memory)
            compacted_context = self.compactor.compact(context_history)

            current_turn_thinking_content = ""

            # ================= Phase 1: Thinking =================
            if self.enable_thinking:
                if reporter is not None:
                    reporter.on_thinking()

                try:
                    think_resp = self.provider.generate(compacted_context, None)
                except Exception as e:
                    raise RuntimeError(f"Thinking 阶段失败: {e}") from e
                if think_resp.content != "":
                    current_turn_thinking_content = think_resp.content
                    compacted_context.append(think_resp)

            # ================= Phase 2: Action =================
            try:
                action_resp = self.provider.generate(compacted_context, available_tools)
            except Exception as e:
                raise RuntimeError(f"Action 阶段失败: {e}") from e

            # (上一讲修复 1214 的关键代码：合并为合法的单条 Assistant 消息)
            final_assistant_msg = Message(
                role=ROLE_ASSISTANT,
                content=(current_turn_thinking_content + "\n" + action_resp.content).strip(),
                tool_calls=action_resp.tool_calls,
            )
            session.append(final_assistant_msg)

            if action_resp.content != "" and reporter is not None:
                reporter.on_message(action_resp.content)

            if len(action_resp.tool_calls) == 0:
                break

            # ================= 执行工具并注入自愈模板 =================
            observation_msgs: list[Message | None] = [None] * len(action_resp.tool_calls)

            def run_tool(idx: int, call: ToolCall):
                if reporter is not None:
                    reporter.on_tool_call(call.name, call.arguments)

                # 底层物理执行工具
                result = self.registry.execute(call)

                # 【核心拦截与注入】
                final_output = result.output
                if result.is_error:
                    # 发生错误，交由 RecoveryManager 诊断并注入“锦囊妙计”
                    final_output = self.recovery.analyze_and_inject(call.name, result.output)
                    log.info("  -> [Worker-%d] ❌ 注入救援指南: %s", idx, final_output)
                else:
                    log.info("  -> [Worker-%d] ✅ 工具执行成功 (返回 %d 字节)", idx, len(result.output))

                if reporter is not None:
                    display_output = final_output
                    if len(display_output) > 200:
                        display_output = display_output[:200] + "... (已截断)"
                    reporter.on_tool_result(call.name, display_output, result.is_error)

                # 将注入过 Recovery Hint 的最终结果写入上下文历史
                observation_msgs[idx] = Message(
                    role=ROLE_USER,
                    content=final_output,
                    tool_call_id=call.id,
                )

            with ThreadPoolExecutor(max_workers=len(action_resp.tool_calls)) as executor:
                futures = [
                    executor.submit(run_tool, i, tool_call)
                    for i, tool_call in enumerate(action_resp.tool_calls)
                ]
                for f in futures:
                    f.result()

            session.append(*observation_msgs)
