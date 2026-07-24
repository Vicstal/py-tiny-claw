# internal/engine/loop.py
# 对应 Go 版: internal/engine/loop.go
# 第 12 章：主循环接入 Compactor —— 每次请求模型前先做上下文双重降级压缩。
import logging
from concurrent.futures import ThreadPoolExecutor

from internal.context.compactor import Compactor
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
        # 测试时将阈值调低至 3000，保护区设为 6
        self.compactor = Compactor(3000, 6)  # 【新增】

    def run(self, session: Session, reporter: Reporter | None) -> None:
        log.info("[Engine] 唤醒会话 [%s]，锁定工作区: %s", session.id, session.work_dir)

        composer = PromptComposer(session.work_dir)
        system_msg = composer.build()

        while True:
            available_tools = self.registry.get_available_tools()

            working_memory = session.get_working_memory(20)

            context_history: list[Message] = []
            context_history.append(system_msg)
            context_history.extend(working_memory)

            # 【核心防线】在向大模型发起请求前，执行上下文双重降级压缩！
            compacted_context = self.compactor.compact(context_history)

            if self.enable_thinking:
                if reporter is not None:
                    reporter.on_thinking()
                try:
                    think_resp = self.provider.generate(compacted_context, None)
                except Exception as e:
                    raise RuntimeError(f"Thinking 阶段失败: {e}") from e
                if think_resp.content != "":
                    session.append(think_resp)
                    compacted_context.append(think_resp)

            try:
                action_resp = self.provider.generate(compacted_context, available_tools)
            except Exception as e:
                raise RuntimeError(f"Action 阶段失败: {e}") from e

            session.append(action_resp)
            compacted_context.append(action_resp)

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

            session.append(*observation_msgs)
