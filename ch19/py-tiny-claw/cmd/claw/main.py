# cmd/claw/main.py
# 第 19 章：链路追踪测试 —— 一轮并行调用两个工具，观察 .claw/traces 下的 Trace 树。
# 运行方式（在 py-tiny-claw 目录下）: ZHIPU_API_KEY=xxx python -m cmd.claw.main
import logging
import os
import sys

from internal.context.session import GLOBAL_SESSION_MGR
from internal.engine.loop import AgentEngine
from internal.engine.terminal_reporter import new_terminal_reporter
from internal.provider.openai import new_zhipu_openai_provider
from internal.schema.message import Message, ROLE_USER
from internal.tools.bash import BashTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")
log = logging.getLogger(__name__)


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量")

    work_dir = os.getcwd()
    work_dir += "/workspace"
    llm_provider = new_zhipu_openai_provider("glm-4.5-air")

    registry = new_registry()
    registry.register(BashTool(work_dir))
    registry.register(WriteFileTool(work_dir))

    eng = AgentEngine(llm_provider, registry, False, False)
    reporter = new_terminal_reporter()
    sess = GLOBAL_SESSION_MGR.get_or_create("test_trace_001", work_dir)

    # 触发一个跨工具类型的并发任务
    prompt = """
	为了加快执行速度，请你在一轮回复中，【同时并行】完成以下两件事：
	1. 使用 bash 工具执行 'sleep 2 && echo "系统环境检查完毕"'
	2. 使用 write_file 工具，在当前目录下创建一个 'trace_test.md'，内容写上 "测试并发的写入"。
	请确保你是分别调用两个不同的工具，不要试图把它们合并成一个命令！
	"""
    sess.append(Message(role=ROLE_USER, content=prompt))

    log.info("\n>>> 🚀 启动带 Tracing 链路追踪的测试...")
    try:
        eng.run(sess, reporter)
    except Exception as e:
        sys.exit(f"引擎崩溃: {e}")


if __name__ == "__main__":
    main()
