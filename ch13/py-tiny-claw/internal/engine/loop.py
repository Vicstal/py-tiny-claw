# internal/engine/loop.py
# 第 13 章：计划模式(PlanMode) + 合规的消息结构：
# Thinking 和 Action 的内容在持久化时合并为一条 Assistant 消息，
# 保证 Session 中的消息严格保持 User -> Assistant 交替。
import logging
from concurrent.futures import ThreadPoolExecutor

from internal.context.compactor import Compactor
from internal.context.composer import PromptComposer
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
        self.plan_mode = plan_mode  # 【新增】计划模式开关
        self.compactor = Compactor(20000, 6)

    def run(self, session: Session, reporter: Reporter | None) -> None:
        log.info("[Engine] 唤醒会话 [%s]，工作区: %s", session.id, session.work_dir)

        composer = PromptComposer(session.work_dir, self.plan_mode)
        system_msg = composer.build()

        while True:
            available_tools = self.registry.get_available_tools()
            working_memory = session.get_working_memory(20)

            context_history: list[Message] = []
            context_history.append(system_msg)
            context_history.extend(working_memory)
            compacted_context = self.compactor.compact(context_history)

            # 用于存放本轮 Turn 合并后的内容
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
                    # 【修改点】：思考内容暂存，先不 append 到 session
                    current_turn_thinking_content = think_resp.content

                    # 为了让 Phase 2 能看到刚才的思考，我们临时将其加入 context_history
                    # 注意：这里仅用于本次 API 请求，不代表最终 Session 结构
                    compacted_context.append(think_resp)

            # ================= Phase 2: Action =================
            try:
                action_resp = self.provider.generate(compacted_context, available_tools)
            except Exception as e:
                raise RuntimeError(f"Action 阶段失败: {e}") from e

            # 【核心修正】：合并 Thinking 和 Action 的内容
            # 构造一条唯一的、合规的 Assistant 消息
            final_assistant_msg = Message(
                role=ROLE_ASSISTANT,
                content=(current_turn_thinking_content + "\n" + action_resp.content).strip(),
                tool_calls=action_resp.tool_calls,
            )

            # 将合并后的合规消息存入持久化 Session
            session.append(final_assistant_msg)

            # 汇报给用户
            if action_resp.content != "" and reporter is not None:
                reporter.on_message(action_resp.content)

            # 如果没有工具调用，结束本轮对话
            if len(action_resp.tool_calls) == 0:
                break

            # ================= 执行工具并记录 Observation =================
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

            # 工具执行结果作为 ROLE_USER 消息存入，保证了下一轮循环时 Role 必然是 User -> Assistant 交替
            session.append(*observation_msgs)
