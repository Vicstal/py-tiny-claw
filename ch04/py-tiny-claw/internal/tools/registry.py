# internal/tools/registry.py
# 对应 Go 版: internal/tools/registry.go
# 第 2 章：此时 Registry 还只是一个接口定义，具体实现由 main.py 中的 mock 提供。
from abc import ABC, abstractmethod

from internal.schema.message import ToolCall, ToolDefinition, ToolResult


class Registry(ABC):
    """工具注册中心接口（对应 Go 的 interface）"""

    @abstractmethod
    def get_available_tools(self) -> list[ToolDefinition]:
        ...

    @abstractmethod
    def execute(self, call: ToolCall) -> ToolResult:
        ...
