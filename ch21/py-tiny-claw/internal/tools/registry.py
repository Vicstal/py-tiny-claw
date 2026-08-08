# internal/tools/registry.py
# 第 19 章：Registry 的 execute 增加 Tracing 埋点。
import logging
from abc import ABC, abstractmethod
from typing import Callable

from internal.observability.trace import start_span
from internal.schema.message import ToolCall, ToolDefinition, ToolResult

log = logging.getLogger(__name__)

# MiddlewareFunc 定义了中间件的签名。
# 它接收当前的 ToolCall，并返回一个是否允许执行的布尔值 (allowed)，以及拦截时的原因 (reject_reason)。
MiddlewareFunc = Callable[[ToolCall], tuple[bool, str]]


class BaseTool(ABC):
    """所有工具必须实现的基础接口"""

    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def definition(self) -> ToolDefinition:
        ...

    @abstractmethod
    def execute(self, args: str) -> str:
        ...


class Registry(ABC):
    @abstractmethod
    def register(self, tool: BaseTool):
        ...

    @abstractmethod
    def use(self, mw: MiddlewareFunc):
        """【新增】全局 Middleware 挂载点"""
        ...

    @abstractmethod
    def get_available_tools(self) -> list[ToolDefinition]:
        ...

    @abstractmethod
    def execute(self, call: ToolCall) -> ToolResult:
        ...


class RegistryImpl(Registry):
    def __init__(self):
        self.tools: dict[str, BaseTool] = {}
        self.middlewares: list[MiddlewareFunc] = []  # 【新增】保存挂载的中间件链

    def use(self, mw: MiddlewareFunc):
        self.middlewares.append(mw)

    def register(self, tool: BaseTool):
        name = tool.name()
        if name in self.tools:
            log.info("[Warning] 工具 '%s' 已经被注册，将被覆盖。", name)
        self.tools[name] = tool
        log.info("[Registry] 成功挂载工具: %s", name)

    def get_available_tools(self) -> list[ToolDefinition]:
        return [tool.definition() for tool in self.tools.values()]

    def execute(self, call: ToolCall) -> ToolResult:
        # 【埋点 5】：开启工具执行的 Span
        span = start_span("Tool.Execute")
        span.add_attribute("tool_name", call.name)
        # 将 JSON 参数存入以备调试
        span.add_attribute("arguments", call.arguments)

        try:
            # 1. 路由查找
            tool = self.tools.get(call.name)
            if tool is None:
                return ToolResult(
                    tool_call_id=call.id,
                    output=f"Error: 系统中不存在名为 '{call.name}' 的工具。",
                    is_error=True,
                )

            # 2. 【核心防御】在执行底层逻辑前，依次运行所有的 Middleware
            for mw in self.middlewares:
                allowed, reason = mw(call)
                if not allowed:
                    log.info("[Registry] ⚠️ 工具 %s 被 Middleware 拦截: %s", call.name, reason)
                    span.add_attribute("intercepted", True)
                    span.add_attribute("reject_reason", reason)
                    return ToolResult(
                        tool_call_id=call.id,
                        output=f"执行被系统拦截。原因: {reason}",
                        is_error=True,  # 必须返回 Error，强制大模型阅读拒绝理由
                    )

            # 3. 执行工具逻辑 (如果所有 Middleware 都放行了)
            try:
                output = tool.execute(call.arguments)
            except Exception as e:
                return ToolResult(
                    tool_call_id=call.id,
                    output=f"Error executing {call.name}: {e}",
                    is_error=True,
                )

            # 我们甚至可以只截取输出的前 100 字符放入 Trace，防止 Trace 文件过度膨胀
            span.add_attribute("output_preview", truncate(output, 100))

            return ToolResult(
                tool_call_id=call.id,
                output=output,
                is_error=False,
            )
        finally:
            span.end_span()  # 无论成功失败，确保结束


def new_registry() -> Registry:
    return RegistryImpl()


def truncate(s: str, max_len: int) -> str:
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
