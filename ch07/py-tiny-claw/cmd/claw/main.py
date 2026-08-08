# cmd/claw/main.py
# 第 7 章：挂载 edit_file 工具，让 Agent 学会"外科手术式"的局部修改。
# （Go 版的实验对象是 server.go；Python 版对应改为 server.py）
# 运行方式（在 py-tiny-claw 目录下）: ZHIPU_API_KEY=xxx python -m cmd.claw.main
import logging
import os
import sys

from internal.engine.loop import AgentEngine
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

    llm_provider = new_zhipu_openai_provider("glm-4.5-air")
    registry = new_registry()

    registry.register(ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    registry.register(BashTool(work_dir))
    registry.register(EditFileTool(work_dir))  # 挂载 Edit 工具

    # 开启慢思考模式
    eng = AgentEngine(llm_provider, registry, work_dir, False)

    prompt = """
	我当前目录下有一个 server.py 文件。
	请帮我把里面 "TODO: 增加鉴权逻辑" 下面的那个 if 语句，整个替换为：
	if user is None:
	    print("Forbidden!")
	    return
	"""

    try:
        eng.run(prompt)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


if __name__ == "__main__":
    main()
