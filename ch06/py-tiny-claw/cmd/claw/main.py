# cmd/claw/main.py
# 第 6 章：补齐 write_file 和 bash 工具，Agent 首次具备"读写执行"完整能力。
# （Go 版让模型写 helloworld.go 并用 go 编译运行；Python 版对应改为 helloworld.py）
# 运行方式（在 py-tiny-claw 目录下）: ZHIPU_API_KEY=xxx python -m cmd.claw.main
import logging
import os
import sys

from internal.engine.loop import AgentEngine
from internal.provider.openai import new_zhipu_openai_provider
from internal.tools.bash import BashTool
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量")

    work_dir = os.getcwd()

    llm_provider = new_zhipu_openai_provider("glm-4.5-air")
    registry = new_registry()

    registry.register(ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    registry.register(BashTool(work_dir))

    eng = AgentEngine(llm_provider, registry, work_dir, False)

    prompt = """
	请帮我执行以下操作：
	1. 用 bash 查看一下我当前电脑的 Python 版本。
	2. 帮我写一个简单的 helloworld.py 文件，输出 "Hello, py-tiny-claw!"。
	3. 用 bash 运行这个 python 文件，确认它能正常工作。
	"""

    try:
        eng.run(prompt)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


if __name__ == "__main__":
    main()
