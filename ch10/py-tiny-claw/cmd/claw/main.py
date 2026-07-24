# cmd/claw/main.py
# 对应 Go 版: cmd/claw/main.go
# 第 10 章：工作区隔离(workspace/) + AGENTS.md 项目记忆 + SKILL.md 外挂技能。
# （Go 版让模型写 ping.go；Python 版对应改为 ping.py）
# 运行方式（在 py-tiny-claw 目录下）: ZHIPU_API_KEY=xxx python -m cmd.claw.main
import logging
import os
import sys

from internal.engine.loop import AgentEngine
from internal.engine.terminal_reporter import new_terminal_reporter
from internal.provider.openai import new_zhipu_openai_provider
from internal.tools.bash import BashTool
from internal.tools.edit_file import EditFileTool
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量")

    work_dir = os.getcwd()
    work_dir += "/workspace"

    llm_provider = new_zhipu_openai_provider("glm-4.5-air")
    registry = new_registry()

    registry.register(ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    registry.register(BashTool(work_dir))
    registry.register(EditFileTool(work_dir))

    eng = AgentEngine(llm_provider, registry, work_dir, True)
    reporter = new_terminal_reporter()

    prompt = """
	我需要在当前目录下新建一个 ping.py，提供一个简单的 http ping 接口。
	写完之后，帮我把代码用 git 提交一下。
	"""

    try:
        eng.run(prompt, reporter)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


if __name__ == "__main__":
    main()
