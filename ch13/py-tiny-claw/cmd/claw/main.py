# cmd/claw/main.py
# 对应 Go 版: cmd/claw/main.go
# 第 13 章：状态外部化 —— 通过命令行 -prompt 下发任务，PlanMode 强制模型
# 把计划写入 PLAN.md / TODO.md，进程重启后也能断点续传。
# 运行方式（在 py-tiny-claw 目录下）:
#   ZHIPU_API_KEY=xxx python -m cmd.claw.main -prompt "你的任务指令"
import argparse
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
    # 通过命令行参数接收用户的 prompt（对应 Go 的 flag 包）
    parser = argparse.ArgumentParser()
    parser.add_argument("-prompt", "--prompt", default="", help="要交给 Agent 执行的任务描述")
    args = parser.parse_args()

    if args.prompt == "":
        print('用法: python -m cmd.claw.main -prompt "你的任务指令"')
        sys.exit(1)

    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量")

    work_dir = os.getcwd()
    work_dir += "/workspace"
    llm_provider = new_zhipu_openai_provider("glm-4.5-air")

    # 挂载 4 大基础工具
    registry = new_registry()
    registry.register(ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    registry.register(BashTool(work_dir))
    registry.register(EditFileTool(work_dir))

    # 实例化引擎并开启计划模式 (PlanMode=True)
    eng = AgentEngine(llm_provider, registry, False, True)
    reporter = new_terminal_reporter()

    # 我们使用一个固定的 SessionID，以便在多次运行之间共享基于内存的“短期工作记忆”。
    # (在真实的 CLI 中，如果进程重启，Session 的内存历史其实是丢失的。
    # 但这正是我们要演示的重点：即便短期内存丢失，只要 TODO.md 还在，任务就能继续！)
    session_id = "task_web_server_01"
    sess = GLOBAL_SESSION_MGR.get_or_create(session_id, work_dir)

    log.info("\n>>> 🚀 收到指令: %s", args.prompt)

    # 将用户的 Prompt 压入 Session
    sess.append(Message(role=ROLE_USER, content=args.prompt))

    # 唤醒引擎执行
    try:
        eng.run(sess, reporter)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")


if __name__ == "__main__":
    main()
