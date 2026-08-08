# cmd/claw/main.py
# 第 14 章：自愈测试 —— 故意下发一个 old_text 不匹配的编辑指令，观察 Agent 借助
# 救援指南自我纠偏。（Go 版的实验对象是 auth.go；Python 版对应改为 auth.py）
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
    llm_provider = new_zhipu_openai_provider("glm-4.5-air")  # 或 Claude 3.5

    registry = new_registry()
    registry.register(ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    registry.register(BashTool(work_dir))
    registry.register(EditFileTool(work_dir))

    # 关闭 Plan 模式，专注于见证它改变主意的单点纠偏过程
    eng = AgentEngine(llm_provider, registry, False, False)
    reporter = new_terminal_reporter()

    session_id = "test_recovery_001"
    sess = GLOBAL_SESSION_MGR.get_or_create(session_id, work_dir)

    # 这是一个巨大的陷阱指令：
    # 我们不给它查看文件的机会，直接命令它凭初始上下文去修改文件，目的是诱发 old_text 不匹配的错误。
    prompt = """
	我当前目录下有一个 auth.py 文件。
	请修改 auth.py 中的 login 函数。
	请直接使用 edit_file 工具替换下面的代码块，将判断条件改为同时允许"admin"、"root"和"guest"三种用户登录：

    # 鉴权入口函数
    def login(user):
        # 检查用户名
        if user == "admin":
            return True
        return False
"""
    log.info("\n>>> 🚀 启动自愈测试任务...")
    sess.append(Message(role=ROLE_USER, content=prompt))

    try:
        eng.run(sess, reporter)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


if __name__ == "__main__":
    main()
