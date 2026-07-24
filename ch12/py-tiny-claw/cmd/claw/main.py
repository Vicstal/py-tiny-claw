# cmd/claw/main.py
# 对应 Go 版: cmd/claw/main.go
# 第 12 章：上下文 OOM 保护实验 —— 读取巨大的 mock_log.txt，观察 Compactor 触发压缩。
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
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量")

    work_dir = os.getcwd()
    llm_provider = new_zhipu_openai_provider("glm-4.5-air")

    registry = new_registry()
    registry.register(ReadFileTool(work_dir))
    registry.register(BashTool(work_dir))

    eng = AgentEngine(llm_provider, registry, False)
    reporter = new_terminal_reporter()

    session_id = "test_oom_protection_001"
    sess = GLOBAL_SESSION_MGR.get_or_create(session_id, work_dir)

    # 提示：你需要在终端先执行 yes "这是一段极其冗长的、无意义的服务器报错日志信息，用来模拟 OOM 场景" | head -n 2000 > mock_log.txt
    prompt = """
	请帮我执行以下三个步骤：
	1. 使用 bash 执行 echo "开始排查日志"
	2. 读取当前目录下的巨大文件 mock_log.txt
	3. 用 bash 执行 date 命令获取当前时间，并告诉我任务完成。
	"""

    sess.append(Message(role=ROLE_USER, content=prompt))

    try:
        eng.run(sess, reporter)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


if __name__ == "__main__":
    main()
