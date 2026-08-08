# internal/engine/reporter.py
# 第 9 章：Reporter 接口 —— 把引擎运行过程中的关键事件外发（如飞书群、终端）。
from abc import ABC, abstractmethod


class Reporter(ABC):
    @abstractmethod
    def on_thinking(self):
        ...

    @abstractmethod
    def on_tool_call(self, tool_name: str, args: str):
        ...

    @abstractmethod
    def on_tool_result(self, tool_name: str, result: str, is_error: bool):
        ...

    @abstractmethod
    def on_message(self, content: str):
        ...
