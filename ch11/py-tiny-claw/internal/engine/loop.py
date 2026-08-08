# internal/engine/loop.py
# 第 11 章：引擎改为面向 Session 运行：每轮从会话中取"短期工作记忆"拼装上下文，
# 生成的消息全部持久化回 Session。
import logging
from concurrent.futures import ThreadPoolExecutor

from internal.context.composer import PromptComposer
from internal.context.session import Session
from internal.engine.reporter import Reporter
from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ROLE_USER, ToolCall
from internal.tools.registry import Registry

log = logging.getLogger(__name__)


class AgentEngine:
    def __init__(self, provider: LLMProvider, registry: Registry, enable_thinking: bool):
        self.provider = provider
        self.registry = registry
        self.enable_thinking = enable_thinking

    # 接收 Session 参数，动态加载工作区环境
    def run(self, session: Session, reporter: Reporter | None) -> None:
        log.info("[Engine] 唤醒会话 [%s]，锁定工作区: %s", session.id, session.work_dir)

        composer = PromptComposer(session.work_dir)
        system_msg = composer.build()

        while True:
            available_tools = self.registry.get_available_tools()

            # 获取短期工作记忆
            working_memory = session.get_working_memory(6)

            context_history: list[Message] = []
            context_history.append(system_msg)
            context_history.extend(working_memory)

            # Phase 1: Thinking
            if self.enable_thinking:
                if reporter is not None:
                    reporter.on_thinking()

                try:
                    think_resp = self.provider.generate(context_history, None)
                except Exception as e:
                    raise RuntimeError(f"Thinking 阶段失败: {e}") from e
                if think_resp.content != "":
                    context_history.append(think_resp)
                    session.append(think_resp)  # 持久化

            # Phase 2: Action
            try:
                action_resp = self.provider.generate(context_history, available_tools)
            except Exception as e:
                raise RuntimeError(f"Action 阶段失败: {e}") from e

            context_history.append(action_resp)
            session.append(action_resp)  # 持久化

            if action_resp.content != "" and reporter is not None:
                reporter.on_message(action_resp.content)

            if len(action_resp.tool_calls) == 0:
                break

            observation_msgs: list[Message | None] = [None] * len(action_resp.tool_calls)

            def run_tool(idx: int, call: ToolCall):
                if reporter is not None:
                    reporter.on_tool_call(call.name, call.arguments)

                result = self.registry.execute(call)

                if reporter is not None:
                    display_output = result.output
                    if len(display_output) > 200:
                        display_output = display_output[:200] + "... (已截断)"
                    reporter.on_tool_result(call.name, display_output, result.is_error)

                observation_msgs[idx] = Message(
                    role=ROLE_USER,
                    content=result.output,
                    tool_call_id=call.id,
                )

            with ThreadPoolExecutor(max_workers=len(action_resp.tool_calls)) as executor:
                futures = [
                    executor.submit(run_tool, i, tool_call)
                    for i, tool_call in enumerate(action_resp.tool_calls)
                ]
                for f in futures:
                    f.result()

            # 持久化观察结果
            session.append(*observation_msgs)
