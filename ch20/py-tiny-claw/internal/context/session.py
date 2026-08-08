# internal/context/session.py
# 第 11 章：Session —— 多会话隔离 + 短期工作记忆（带截断保护）。
import threading
from datetime import datetime

from internal.schema.message import Message, ROLE_USER


class Session:
    def __init__(self, id: str, work_dir: str):
        self.id = id
        self.work_dir = work_dir
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

        # 【新增】用于统计该 Session 累计消耗的资源
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost_cny = 0.0

        self._history: list[Message] = []
        # 读写锁简化为互斥锁（对应 Go 的 sync.RWMutex）
        self._mu = threading.Lock()

    def append(self, *msgs: Message):
        with self._mu:
            self._history.extend(msgs)
            self.updated_at = datetime.now()

    def get_working_memory(self, limit: int) -> list[Message]:
        """获取最近 limit 条消息作为短期工作记忆"""
        with self._mu:
            total = len(self._history)
            if total <= limit or limit <= 0:
                return list(self._history)

            res = list(self._history[total - limit:])

            # 处理截断边缘的 ToolResult 孤儿问题：
            # 如果窗口开头是一条"工具结果"消息，其对应的 assistant tool_call 已被截掉，
            # 直接发给模型会导致协议错误，必须继续丢弃。
            while len(res) > 0:
                if res[0].role == ROLE_USER and res[0].tool_call_id != "":
                    res = res[1:]
                else:
                    break

            return res

    def record_usage(self, prompt: int, completion: int, cost: float):
        """record_usage 是一个给外部 Tracker 调用的辅助方法，用于累加账单"""
        with self._mu:
            self.total_prompt_tokens += prompt
            self.total_completion_tokens += completion
            self.total_cost_cny += cost


class SessionManager:
    def __init__(self):
        self.sessions: dict[str, Session] = {}
        self._mu = threading.Lock()

    def get_or_create(self, id: str, work_dir: str) -> Session:
        with self._mu:
            if id in self.sessions:
                return self.sessions[id]
            sess = Session(id, work_dir)
            self.sessions[id] = sess
            return sess


# 全局单例（对应 Go 版的包级变量 GlobalSessionMgr）
GLOBAL_SESSION_MGR = SessionManager()
