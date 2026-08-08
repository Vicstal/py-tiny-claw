# internal/engine/loop.py
# 第 17 章：新增 run_sub —— 专为子智能体拉起的一次性受限循环（只读工具 + 轮数上限）。
import logging
from concurrent.futures import ThreadPoolExecutor

from internal.context.compactor import Compactor
from internal.context.composer import PromptComposer
from internal.context.recovery import RecoveryManager
from internal.context.session import Session
from internal.engine.reminder import ReminderInjector
from internal.engine.reporter import Reporter
from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_USER, ToolCall, ToolResult
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

    # run_sub 是专为 Subagent 拉起的一次性受限循环。
    # 它不依赖外部 Session，打完就跑。
    # reporter：为了让用户在终端看到子智能体的工作轨迹，我们将主线程的 Reporter 透传进来，并打上特殊标记。
    def run_sub(self, task_prompt: str, read_only_registry: Registry, reporter) -> str:

        # 【核心优化】：子智能体极其容易偷懒。我们必须在 System Prompt 中严厉警告它必须使用工具！
        context_history: list[Message] = [
            Message(
                role=ROLE_SYSTEM,
                content="""你是一个专门负责深度探索的探路者 (Explorer Subagent)。
你的任务是根据主架构师的指令，在当前工作区内仔细阅读代码、查阅日志，搜集足够的信息。

【核心纪律】
1. 你必须、且只能依靠内置工具（如 bash 的 find/grep，或 read_file）去寻找答案。绝对不允许凭空捏造或猜测！
2. 如果你没有找到确切的答案，你必须继续使用工具深入搜索。
3. 当且仅当你找到了确切的线索后，停止调用工具，直接输出一段纯文本作为你的终极汇报。主架构师会根据你的汇报来做下一步决策。""",
            ),
            Message(
                role=ROLE_USER,
                content=task_prompt,
            ),
        ]

        # 限制子智能体最多只能跑 10 个 Turn，防止它自己卡死
        MAX_SUB_TURNS = 10
        turn_count = 0

        while True:
            turn_count += 1
            if turn_count > MAX_SUB_TURNS:
                raise RuntimeError(f"子智能体探索过于深入，超过 {MAX_SUB_TURNS} 轮被强制召回，请主 Agent 给它更明确的指令")

            # 【驾驭底线】：子智能体仅能获取传入的只读工具注册表
            available_tools = read_only_registry.get_available_tools()

            compacted_context = self.compactor.compact(context_history)

            # 子任务要求急速响应，强制关闭主体的慢思考，直接预测行动
            try:
                action_resp = self.provider.generate(compacted_context, available_tools)
            except Exception as e:
                raise RuntimeError(f"子智能体推理失败: {e}") from e

            context_history.append(action_resp)

            # 【核心退出条件】：子智能体一旦不调用工具了，说明它做好了总结汇报
            if len(action_resp.tool_calls) == 0:
                # 直接将它的这段汇报内容剥离出来返回给上层
                return action_resp.content

            # 执行只读工具的并发循环
            observation_msgs: list[Message | None] = [None] * len(action_resp.tool_calls)

            def run_tool(idx: int, call: ToolCall):
                # 【可视化的关键】：让终端用户看到 Subagent 正在干嘛
                if reporter is not None:
                    reporter.on_tool_call(f"[Subagent] {call.name}", call.arguments)

                result = read_only_registry.execute(call)

                final_output = result.output
                if result.is_error:
                    final_output = self.recovery.analyze_and_inject(call.name, result.output)

                if reporter is not None:
                    display = final_output
                    if len(display) > 200:
                        display = display[:200] + "... (已截断)"
                    reporter.on_tool_result(f"[Subagent] {call.name}", display, result.is_error)

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

            context_history.extend(observation_msgs)
