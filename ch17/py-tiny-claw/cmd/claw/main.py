# cmd/claw/main.py
# 第 17 章：多智能体协同 —— 主 Agent 派出只读沙箱中的子智能体探索，再亲自写入结果。
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
from internal.tools.subagent import SubagentTool
from internal.tools.write_file import WriteFileTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")
log = logging.getLogger(__name__)


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量")

    work_dir = os.getcwd()
    work_dir += "/workspace"

    llm_provider = new_zhipu_openai_provider("glm-4.5-air")
    reporter = new_terminal_reporter()

    # 【防御沙箱】为子智能体准备受限的只读注册表
    read_only_registry = new_registry()
    read_only_registry.register(ReadFileTool(work_dir))
    read_only_registry.register(BashTool(work_dir))  # 允许简单的 grep 等搜索操作

    # 为主智能体准备全功能注册表
    main_registry = new_registry()
    main_registry.register(ReadFileTool(work_dir))
    main_registry.register(WriteFileTool(work_dir))
    main_registry.register(BashTool(work_dir))
    main_registry.register(EditFileTool(work_dir))

    # 初始化主引擎
    eng = AgentEngine(llm_provider, main_registry, False, False)

    # 【核心装配】：将带有 Engine 引用和只读 Registry 的 Subagent 工具注册进主线
    main_registry.register(SubagentTool(eng, read_only_registry, reporter))

    session_id = "test_subagent_001"
    sess = GLOBAL_SESSION_MGR.get_or_create(session_id, work_dir)

    prompt = """
	我需要你在这个遗留项目里，找到那个“核心密码”。
	为了防止污染主上下文，请你务必派出子智能体（spawn_subagent）去执行探索任务。
	你可以让子智能体使用 bash 去查找当前目录（及其所有子目录）下名为 config.txt 的文件。
	子智能体拿到密码向你汇报后，请你亲自使用 write_file 工具，将密码写在根目录的 answer.txt 里。
	"""

    log.info("\n>>> 🚀 启动多智能体协同测试...")
    sess.append(Message(role=ROLE_USER, content=prompt))

    try:
        eng.run(sess, reporter)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


if __name__ == "__main__":
    main()
