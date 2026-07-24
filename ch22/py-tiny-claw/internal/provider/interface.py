# internal/provider/interface.py
# 对应 Go 版: internal/provider/interface.go
from abc import ABC, abstractmethod

from internal.schema.message import Message, ToolDefinition


class LLMProvider(ABC):
    """LLMProvider 定义了与大模型通信的统一接口（对应 Go 的 interface）"""

    @abstractmethod
    def generate(self, messages: list[Message], available_tools: list[ToolDefinition] | None) -> Message:
        """generate 接收当前上下文历史和可用工具列表，返回模型响应"""
        ...
