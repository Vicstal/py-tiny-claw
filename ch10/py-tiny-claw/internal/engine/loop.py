# internal/engine/loop.py
# 第 10 章：引擎接入 PromptComposer，System Prompt 不再写死，而是动态组装。
import logging
from concurrent.futures import ThreadPoolExecutor

from internal.context.composer import PromptComposer
from internal.engine.reporter import Reporter
from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ROLE_USER, ToolCall
from internal.tools.registry import Registry

log = logging.getLogger(__name__)


class AgentEngine:
    def __init__(self, provider: LLMProvider, registry: Registry, work_dir: str, enable_thinking: bool):
        self.provider = provider
        self.registry = registry
        self.work_dir = work_dir
        self.enable_thinking = enable_thinking
        self.composer = PromptComposer(work_dir)  # 【新增】

    def run(self, user_prompt: str, reporter: Reporter | None) -> None:
        log.info("[Engine] 引擎启动，锁定工作区: %s", self.work_dir)

        # 【核心修改】动态组装 System Prompt
        system_msg = self.composer.build()

        context_history: list[Message] = [
            system_msg,
            Message(role=ROLE_USER, content=user_prompt),
        ]

        while True:
            available_tools = self.registry.get_available_tools()

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

            # Phase 2: Action
            try:
                action_resp = self.provider.generate(context_history, available_tools)
            except Exception as e:
                raise RuntimeError(f"Action 阶段失败: {e}") from e

            context_history.append(action_resp)

            if action_resp.content != "" and reporter is not None:
                reporter.on_message(action_resp.content)

            # 检查结束
            if len(action_resp.tool_calls) == 0:
                break

            # 执行并发工具调用
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

            for obs in observation_msgs:
                context_history.append(obs)
