# cmd/claw/main.py
# 第 18 章：可观测性 —— 用 CostTracker 包裹 Provider，任务结束后输出财务报表。
# 运行方式（在 py-tiny-claw 目录下）: ZHIPU_API_KEY=xxx python -m cmd.claw.main
import logging
import os
import sys

from internal.context.session import GLOBAL_SESSION_MGR
from internal.engine.loop import AgentEngine
from internal.engine.terminal_reporter import new_terminal_reporter
from internal.observability.tracker import CostTracker
from internal.provider.openai import new_zhipu_openai_provider
from internal.schema.message import Message, ROLE_USER
from internal.tools.bash import BashTool
from internal.tools.registry import new_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")
log = logging.getLogger(__name__)


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量")

    work_dir = os.getcwd()
    model_name = "glm-4.5-air"

    # 1. 初始化真实的底层大脑
    real_provider = new_zhipu_openai_provider(model_name)

    session_id = "test_observability_001"
    sess = GLOBAL_SESSION_MGR.get_or_create(session_id, work_dir)

    # 2. 核心拼装：用 Tracker 将真实的大脑包裹起来
    tracked_provider = CostTracker(real_provider, model_name, sess)

    registry = new_registry()
    registry.register(BashTool(work_dir))

    # 3. 将被包裹的 Provider 注入给 Engine (Engine 毫不知情)
    eng = AgentEngine(tracked_provider, registry, False, False)
    reporter = new_terminal_reporter()

    prompt = "请用 bash 帮我用 date 命令查一下现在的时间。"

    log.info("\n>>> 🚀 启动带仪表盘的可观测性测试...")
    sess.append(Message(role=ROLE_USER, content=prompt))

    try:
        eng.run(sess, reporter)
    except Exception as e:
        sys.exit(f"引擎运行崩溃: {e}")

    log.info("\n================ 财务报表 ================")
    log.info("会话 ID: %s", sess.id)
    log.info("总消耗 Input Tokens: %d", sess.total_prompt_tokens)
    log.info("总消耗 Output Tokens: %d", sess.total_completion_tokens)
    log.info("总计费用 (CNY): ¥%.6f", sess.total_cost_cny)
    log.info("==========================================")


if __name__ == "__main__":
    main()
