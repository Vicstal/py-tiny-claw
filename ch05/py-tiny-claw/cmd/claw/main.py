# cmd/claw/main.py
# 第 5 章：挂载第一个真实工具 read_file，让模型真正"看到"文件系统。
# 运行方式（在 py-tiny-claw 目录下）: ZHIPU_API_KEY=xxx python -m cmd.claw.main
import logging
import os
import sys

from internal.engine.loop import AgentEngine
from internal.provider.openai import new_zhipu_openai_provider
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量")

    work_dir = os.getcwd()

    llm_provider = new_zhipu_openai_provider("glm-4.5-air")

    registry = new_registry()

    read_file_tool = ReadFileTool(work_dir)
    registry.register(read_file_tool)

    eng = AgentEngine(llm_provider, registry, work_dir, False)

    prompt = "请调用工具读取一下当前工作区目录下 hello.txt 文件的内容，并用一句话向我总结它说了什么。"

    try:
        eng.run(prompt)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


if __name__ == "__main__":
    main()
