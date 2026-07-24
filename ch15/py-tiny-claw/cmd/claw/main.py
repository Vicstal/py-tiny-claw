# cmd/claw/main.py
# 对应 Go 版: cmd/claw/main.go
# 第 15 章：死循环干预测试 —— 诱导模型反复用同一参数重试，观察 Reminder 注入。
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
from internal.tools.edit_file import EditFileTool
from internal.tools.read_file import ReadFileTool
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
    registry.register(ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    registry.register(BashTool(work_dir))
    registry.register(EditFileTool(work_dir))

    # 关闭 Plan 模式，让它在死胡同里专注地展示挣扎过程
    eng = AgentEngine(llm_provider, registry, False, False)
    reporter = new_terminal_reporter()

    session_id = "test_doom_loop_001"
    sess = GLOBAL_SESSION_MGR.get_or_create(session_id, work_dir)

    prompt = """
	帮我读取当前目录下的 secret_key.txt。
	注意：我们的文件系统现在非常不稳定，经常报 File Not Found。
	如果报错了，请你【千万不要改变参数】，直接原样再次调用 read_file 尝试，直到成功或连续重试 5 次为止。
	"""

    log.info("\n>>> 🚀 启动死循环干预测试...")
    sess.append(Message(role=ROLE_USER, content=prompt))

    try:
        eng.run(sess, reporter)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


if __name__ == "__main__":
    main()
