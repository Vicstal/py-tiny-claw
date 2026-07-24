# internal/observability/trace.py
# 对应 Go 版: internal/observability/trace.go
# 第 19 章：极简链路追踪 (Tracing)。
# Go 版通过 context.Context 逐层传递父 Span；Python 版用标准库 contextvars 实现同样的
# "当前 Span" 级联语义（跨线程时配合 contextvars.copy_context 使用）。
import contextvars
import json
import os
import threading
import time
from datetime import datetime

# _current_span 是存放当前 Span 的上下文变量（对应 Go 的 traceKey + context.WithValue）
_current_span: contextvars.ContextVar["Span | None"] = contextvars.ContextVar("current_span", default=None)


class Span:
    """Span 代表链路追踪中的一个时间跨度和操作节点"""

    def __init__(self, name: str):
        self.name = name
        self.start_time = datetime.now()
        self.end_time: datetime | None = None
        self.duration_ms = 0
        self.attributes: dict = {}   # 存放元数据 (如消耗的 Token, 执行的命令)
        self.children: list[Span] = []  # 子跨度

        self._mu = threading.Lock()  # 保护 children/attributes 的并发写入
        self._token: contextvars.Token | None = None
        self._start_monotonic = time.monotonic()

    def end_span(self):
        """结束跨度，计算耗时，并把"当前 Span"恢复为父节点"""
        self.end_time = datetime.now()
        self.duration_ms = int((time.monotonic() - self._start_monotonic) * 1000)
        if self._token is not None:
            try:
                _current_span.reset(self._token)
            except ValueError:
                # Token 属于其他上下文副本（并发场景），忽略即可
                pass
            self._token = None

    def add_attribute(self, key: str, value):
        """为当前 Span 记录关键的元数据"""
        with self._mu:
            self.attributes[key] = value

    def to_dict(self) -> dict:
        """递归序列化为 JSON 友好的 dict（对应 Go 版的 json tag 结构）"""
        d = {
            "name": self.name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
        }
        if self.attributes:
            d["attributes"] = self.attributes
        if self.children:
            d["children"] = [child.to_dict() for child in self.children]
        return d


def start_span(name: str) -> Span:
    """开启一个新的追踪跨度，挂到当前 Span 之下，并把自己置为最新的"当前 Span"。"""
    span = Span(name)

    # 尝试获取父 Span 并级联
    parent = _current_span.get()
    if parent is not None:
        with parent._mu:
            parent.children.append(span)

    # 将当前新创建的 Span 作为最新的父节点
    span._token = _current_span.set(span)
    return span


def export_trace_to_file(root_span: Span, work_dir: str, session_id: str):
    """当整个根 Span 结束时，将其序列化并保存为本地 JSON 文件"""
    trace_dir = os.path.join(work_dir, ".claw", "traces")
    os.makedirs(trace_dir, exist_ok=True)

    # 使用纳秒时间戳避免同一秒内多次运行导致文件碰撞
    filename = os.path.join(trace_dir, f"trace_{session_id}_{time.time_ns()}.json")

    # 美化输出 JSON，便于人类和工具阅读
    data = json.dumps(root_span.to_dict(), ensure_ascii=False, indent=2)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(data)
