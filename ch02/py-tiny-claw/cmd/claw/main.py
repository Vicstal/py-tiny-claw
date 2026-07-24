# cmd/claw/main.py
# 对应 Go 版: cmd/claw/main.go
# 第 2 章：用 mock 的 Provider 和 Registry 驱动主循环，验证 Reason-Act-Observe 骨架。
# 运行方式（在 py-tiny-claw 目录下）: python -m cmd.claw.main
import logging
import os
import sys

from internal.engine.loop import AgentEngine
from internal.provider.interface import LLMProvider
from internal.schema.message import (
    Message,
    ROLE_ASSISTANT,
    ToolCall,
    ToolResult,
)
from internal.tools.registry import Registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")


class MockProvider(LLMProvider):
    """假模型：第一轮固定要求调用 bash 工具，第二轮宣布任务完成。"""

    def __init__(self):
        self.turn = 0

    def generate(self, msgs, _tools):
        self.turn += 1
        if self.turn == 1:
            return Message(
                role=ROLE_ASSISTANT,
                content="让我来看看当前目录下有什么文件。",
                tool_calls=[
                    ToolCall(id="call_123", name="bash", arguments='{"command": "ls -la"}'),
                ],
            )

        return Message(
            role=ROLE_ASSISTANT,
            content="我看到了文件列表，里面包含 main.py，任务完成！",
        )


class MockRegistry(Registry):
    """假工具箱：无论调用什么工具都返回一份固定的 ls 输出。"""

    def get_available_tools(self):
        return []

    def execute(self, call: ToolCall) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            output="-rw-r--r--  1 user group  234 Oct 24 10:00 main.py\n",
            is_error=False,
        )


def main():
    work_dir = os.getcwd()

    p = MockProvider()
    r = MockRegistry()

    eng = AgentEngine(p, r, work_dir)

    try:
        eng.run("帮我检查当前目录的文件")
    except Exception as e:
        sys.exit(f"引擎崩溃: {e}")


if __name__ == "__main__":
    main()
