# internal/context/compactor.py
# 第 12 章：Compactor —— 上下文"内存回收器"：
# 超过阈值时，对早期工具输出和早期思考过程做降级压缩，防止上下文 OOM。
import logging

from internal.schema.message import Message, ROLE_ASSISTANT, ROLE_SYSTEM, ROLE_USER

log = logging.getLogger(__name__)


class Compactor:
    def __init__(self, max_chars: int, retain_last_msgs: int):
        self.max_chars = max_chars
        self.retain_last_msgs = retain_last_msgs

    def compact(self, msgs: list[Message]) -> list[Message]:
        current_length = self.estimate_length(msgs)

        if current_length < self.max_chars:
            return msgs

        log.info(
            "[Compactor] ⚠️ 内存告警：当前上下文长度 (%d 字符) 超过阈值 (%d)，触发压缩清理...",
            current_length, self.max_chars,
        )

        compacted: list[Message] = []
        msg_count = len(msgs)

        # 最近 retain_last_msgs 条消息属于"保护区"（工作记忆），只做轻度截断
        protect_start_index = msg_count - self.retain_last_msgs
        if protect_start_index < 0:
            protect_start_index = 0

        for i, msg in enumerate(msgs):
            if msg.role == ROLE_SYSTEM:
                compacted.append(msg)
                continue

            # 复制一份再修改，避免污染 Session 中的原始记录
            new_msg = Message(
                role=msg.role,
                content=msg.content,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id,
            )
            is_in_working_memory = i >= protect_start_index

            if msg.role == ROLE_USER and msg.tool_call_id != "":
                if not is_in_working_memory:
                    # 早期工具输出：整体丢弃，只留一行占位说明
                    if len(msg.content) > 200:
                        new_msg.content = f"...[为了节省内存，早期的工具输出已被系统强制清理。原始长度: {len(msg.content)} 字节]..."
                else:
                    # 保护区内的工具输出：保留头尾各 500 字符
                    MAX_KEEP = 1000
                    if len(msg.content) > MAX_KEEP:
                        head = msg.content[:500]
                        tail = msg.content[len(msg.content) - 500:]
                        new_msg.content = f"{head}\n\n...[内容过长，中间 {len(msg.content) - MAX_KEEP} 字节已被系统截断]...\n\n{tail}"
            elif msg.role == ROLE_ASSISTANT and msg.content != "":
                # 早期的长篇思考过程直接折叠
                if not is_in_working_memory and len(msg.content) > 200:
                    new_msg.content = "...[早期的推理思考过程已折叠]..."

            compacted.append(new_msg)

        new_length = self.estimate_length(compacted)
        log.info("[Compactor] ✅ 压缩完成。上下文长度从 %d 降至 %d 字符。", current_length, new_length)

        return compacted

    def estimate_length(self, msgs: list[Message]) -> int:
        length = 0
        for msg in msgs:
            length += len(msg.content)
            for tc in msg.tool_calls:
                length += len(tc.name) + len(tc.arguments)
        return length
