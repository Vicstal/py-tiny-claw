# cmd/claw/main.py
# 第 4 章：接入真实大模型（智谱 GLM，走 OpenAI 兼容协议），工具仍然是 mock 的天气工具。
# 运行方式（在 py-tiny-claw 目录下）: ZHIPU_API_KEY=xxx python -m cmd.claw.main
import logging
import os
import sys

from internal.engine.loop import AgentEngine
from internal.provider.openai import new_zhipu_openai_provider
from internal.schema.message import ToolCall, ToolDefinition, ToolResult
from internal.tools.registry import Registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")
log = logging.getLogger(__name__)


class MockRegistry(Registry):
    def get_available_tools(self):
        return [
            ToolDefinition(
                name="get_weather",
                description="获取指定城市的当前天气情况。",
                input_schema={
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                        },
                    },
                    "required": ["city"],
                },
            ),
        ]

    def execute(self, call: ToolCall) -> ToolResult:
        log.info("  -> [Mock 工具执行] 获取 %s 的天气中...", call.name)
        return ToolResult(
            tool_call_id=call.id,
            output="API 返回：今天是晴天，气温 25 度。",
            is_error=False,
        )


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量")

    work_dir = os.getcwd()

    llm_provider = new_zhipu_openai_provider("glm-4.5-air")
    registry = MockRegistry()

    eng = AgentEngine(llm_provider, registry, work_dir, False)

    prompt = "我想去北京跑步，帮我查查天气适合吗？"

    try:
        eng.run(prompt)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


if __name__ == "__main__":
    main()
