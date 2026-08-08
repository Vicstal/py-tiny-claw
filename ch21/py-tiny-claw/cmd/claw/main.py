# cmd/claw/main.py
# 第 21 章：最终 CLI 形态 —— 命令行参数 + 全息监控 (Tracker + Tracing) + 持久化会话。
# 运行方式（在 py-tiny-claw 目录下）:
#   ZHIPU_API_KEY=xxx python -m cmd.claw.main -prompt "你的任务描述" [-dir /path/to/workdir] [-session session_id]
import argparse
import logging
import os
import sys
import time

from internal.context.session import GLOBAL_SESSION_MGR
from internal.engine.loop import AgentEngine
from internal.engine.terminal_reporter import new_terminal_reporter
from internal.observability.tracker import CostTracker
from internal.observability.trace import export_trace_to_file, start_span
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
    # 1. 命令行参数解析
    parser = argparse.ArgumentParser()
    parser.add_argument("-prompt", "--prompt", default="", help="要交给 Agent 执行的任务描述")
    parser.add_argument("-dir", "--dir", default=".", help="Agent 运行的工作区目录路径 (默认为当前目录)")
    parser.add_argument("-session", "--session", default="cli_default_session", help="指定会话 ID，支持断点续传")
    args = parser.parse_args()

    if args.prompt == "":
        print('用法: py-tiny-claw -prompt "你的任务描述" [-dir /path/to/workdir] [-session session_id]')
        sys.exit(1)

    # 解析工作区绝对路径
    work_dir = os.path.abspath(args.dir)

    print("==================================================")
    print("🚀 启动 py-tiny-claw CLI 引擎...")
    print(f"📁 锁定工作区: {work_dir}")
    print("==================================================")

    # 2. 初始化核心基础服务
    model_name = "glm-4.5-air"
    real_provider = new_zhipu_openai_provider(model_name)

    # 获取持久化 Session
    sess = GLOBAL_SESSION_MGR.get_or_create(args.session, work_dir)

    # 【全息监控装配】：用 Cost Tracker 将真实大脑包裹起来
    tracked_provider = CostTracker(real_provider, model_name, sess)

    # 3. 初始化工具与执行层
    registry = new_registry()
    registry.register(ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    registry.register(BashTool(work_dir))
    registry.register(EditFileTool(work_dir))

    # 在 CLI 模式下，我们默认开启 YOLO 模式（全权信任本地执行），
    # 因此这里暂时不挂载 Feishu 审批 Middleware。

    # 4. 初始化核心引擎 (组装器内部会自动加载 Composer, Compactor, Recovery, Reminders)
    # 开启 PlanMode = True
    eng = AgentEngine(tracked_provider, registry, False, True)

    # 【全息追踪装配】：初始化链路追踪 Root Span
    root_span = start_span("CLI.TaskRun")
    root_span.add_attribute("Prompt", args.prompt)
    start = time.monotonic()

    # 5. 初始化彩色终端输出器
    reporter = new_terminal_reporter()

    print(f"\n🎯 收到任务: {args.prompt}\n")

    # 将用户的 Prompt 压入 Session 记忆
    sess.append(Message(role=ROLE_USER, content=args.prompt))

    # 6. 发起冲锋：启动 Main Loop！
    try:
        eng.run(sess, reporter)
    except Exception as e:
        sys.exit(f"\n💥 引擎运行崩溃: {e}")
    finally:
        # 对应 Go 版的 defer：结束 Root Span 并导出 Trace
        root_span.end_span()
        export_trace_to_file(root_span, work_dir, sess.id)

    print("\n==================================================")
    print(f"✨ 任务圆满结束。总耗时: {time.monotonic() - start:.3f}s")
    print(f"💰 Session 累计消耗: ${sess.total_cost_cny:.6f} | Token: Input {sess.total_prompt_tokens}, Output {sess.total_completion_tokens}")
    print("==================================================")


if __name__ == "__main__":
    main()
