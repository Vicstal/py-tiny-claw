# internal/engine/reminder.py
# 第 15 章：ReminderInjector —— 死循环探测器：
# 同一"工具+参数"指纹连续失败 3 次，就注入一条强力干预消息。
import hashlib
import logging

from internal.schema.message import Message, ROLE_USER, ToolCall, ToolResult

log = logging.getLogger(__name__)


def generate_fingerprint(tool_name: str, args: str) -> str:
    """把 工具名+参数 哈希成唯一指纹（对应 Go 版的 md5 实现）"""
    hasher = hashlib.md5()
    hasher.update(tool_name.encode("utf-8"))
    hasher.update(args.encode("utf-8"))
    return hasher.hexdigest()


class ReminderInjector:
    def __init__(self):
        self.consecutive_failures: dict[str, int] = {}

    def check_and_inject(self, last_tool_call: ToolCall, last_result: ToolResult) -> Message | None:
        fingerprint = generate_fingerprint(last_tool_call.name, last_tool_call.arguments)

        if not last_result.is_error:
            # 只要有一次成功，就认为模型已经走出困境，清空计数器
            self.consecutive_failures = {}
            return None

        self.consecutive_failures[fingerprint] = self.consecutive_failures.get(fingerprint, 0) + 1
        fail_count = self.consecutive_failures[fingerprint]

        log.info("[Reminder] 监控到工具 %s 执行失败，该参数特征连续失败次数: %d", last_tool_call.name, fail_count)

        if fail_count >= 3:
            log.info("[Reminder] ⚠️ 触发死循环干预！注入强力修正指令。")

            nudge_msg = f"""[SYSTEM REMINDER 警告]
你似乎陷入了死循环。你刚刚连续 {fail_count} 次使用相同的参数调用了 '{last_tool_call.name}' 工具，并且都失败了。
请立即停止这种无效的重试！你的注意力被当前的报错过度吸引了。
你需要：
1. 停止猜测参数。跳出当前的局部思维。
2. 彻底改变你的策略。
3. 如果你确实无法通过系统工具解决当前问题，请直接结束任务并向用户说明你需要什么人工帮助，而不是继续盲目消耗 API 资源尝试。"""

            return Message(
                role=ROLE_USER,
                content=nudge_msg,
            )

        return None
