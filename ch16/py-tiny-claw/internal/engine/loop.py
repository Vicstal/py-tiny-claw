# internal/engine/loop.py
# 对应 Go 版: internal/engine/loop.go
# 第 15 章：主循环接入 ReminderInjector —— 每轮工具执行后做死循环探测与干预。
import logging
from concurrent.futures import ThreadPoolExecutor

from internal.context.compactor import Compactor
from internal.context.composer import PromptComposer
from internal.context.recovery import RecoveryManager
from internal.context.session import Session
from internal.engine.reminder import ReminderInjector
from internal.engine.reporter import Reporter
from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ROLE_ASSISTANT, ROLE_USER, ToolCall, ToolResult
from internal.tools.registry import Registry

log = logging.getLogger(__name__)


class AgentEngine:
    def __init__(self, provider: LLMProvider, registry: Registry, enable_thinking: bool, plan_mode: bool):
        self.provider = provider
        self.registry = registry
        self.enable_thinking = enable_thinking
        self.plan_mode = plan_mode
        self.compactor = Compactor(20000, 6)
        self.recovery = RecoveryManager()
        self.injector = ReminderInjector()  # 【新增】提醒注入器

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

            # Phase 1: Thinking
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

            # Phase 2: Action
            try:
                action_resp = self.provider.generate(compacted_context, available_tools)
            except Exception as e:
                raise RuntimeError(f"Action 阶段失败: {e}") from e

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

            observation_msgs: list[Message | None] = [None] * len(action_resp.tool_calls)

            # 用于收集本轮执行的最后一个工具供 Reminder 分析
            last_tool_call: ToolCall | None = None
            last_tool_result: ToolResult | None = None

            def run_tool(idx: int, call: ToolCall):
                nonlocal last_tool_call, last_tool_result

                if reporter is not None:
                    reporter.on_tool_call(call.name, call.arguments)

                result = self.registry.execute(call)

                final_output = result.output
                if result.is_error:
                    final_output = self.recovery.analyze_and_inject(call.name, result.output)

                if reporter is not None:
                    display_output = final_output
                    if len(display_output) > 200:
                        display_output = display_output[:200] + "... (已截断)"
                    reporter.on_tool_result(call.name, display_output, result.is_error)

                observation_msgs[idx] = Message(
                    role=ROLE_USER,
                    content=final_output,
                    tool_call_id=call.id,
                )

                if idx == 0:
                    last_tool_call = call
                    last_tool_result = result

            with ThreadPoolExecutor(max_workers=len(action_resp.tool_calls)) as executor:
                futures = [
                    executor.submit(run_tool, i, tool_call)
                    for i, tool_call in enumerate(action_resp.tool_calls)
                ]
                for f in futures:
                    f.result()

            session.append(*observation_msgs)

            # 【核心防线】：在进入下一轮前，进行死循环探测与注入
            reminder_msg = self.injector.check_and_inject(last_tool_call, last_tool_result)
            if reminder_msg is not None:
                session.append(reminder_msg)
