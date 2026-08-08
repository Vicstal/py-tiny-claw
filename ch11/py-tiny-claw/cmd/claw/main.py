# cmd/claw/main.py
# 第 11 章：多会话隔离实验 —— 两个并发会话各自持有独立的记忆与工作区。
# 运行方式（在 py-tiny-claw 目录下）: ZHIPU_API_KEY=xxx python -m cmd.claw.main
import logging
import os
import sys
import threading
import time

from internal.context.session import GLOBAL_SESSION_MGR
from internal.engine.loop import AgentEngine
from internal.engine.terminal_reporter import new_terminal_reporter
from internal.provider.openai import new_zhipu_openai_provider
from internal.schema.message import Message, ROLE_ASSISTANT, ROLE_USER
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")
log = logging.getLogger(__name__)


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY 环境变量")

    llm_provider = new_zhipu_openai_provider("glm-4.5-air")

    registry = new_registry()
    registry.register(ReadFileTool("/tmp/project_front"))

    eng = AgentEngine(llm_provider, registry, False)
    reporter = new_terminal_reporter()

    # ================= 并发场景 1：Session A =================
    def session_a_worker():
        session_a = GLOBAL_SESSION_MGR.get_or_create("chat_front_001", "/tmp/project_front")

        log.info("\n>>> 🙋‍♂️ [Session A / Turn 1]: 帮我看看 README.md 里记录了什么密钥？")
        session_a.append(Message(role=ROLE_USER, content="帮我看看 README.md 里记录了什么密钥？"))
        eng.run(session_a, reporter)

        # 塞入废话，刷掉记忆
        for _ in range(6):
            session_a.append(Message(role=ROLE_USER, content="这只是一句闲聊占位符。"))
            session_a.append(Message(role=ROLE_ASSISTANT, content="好的，收到闲聊。"))

        log.info("\n>>> 🙋‍♂️ [Session A / Turn 2]: 请直接告诉我，刚才第一轮你查到的那个密钥是什么？")
        session_a.append(Message(role=ROLE_USER, content="请直接告诉我，刚才第一轮你查到的那个密钥是什么？不准调用工具！"))
        eng.run(session_a, reporter)

    # ================= 并发场景 2：Session B =================
    def session_b_worker():
        time.sleep(1)

        session_b = GLOBAL_SESSION_MGR.get_or_create("chat_back_002", "/tmp/project_back")

        log.info("\n>>> 🙋‍♂️ [Session B]: 别人查到了一个密钥，你这里能看到吗？")
        session_b.append(Message(role=ROLE_USER, content="别人查到了一个密钥，你这里能看到吗？不准调用工具！"))
        eng.run(session_b, reporter)

    # 对应 Go 版的两个 goroutine + WaitGroup
    t1 = threading.Thread(target=session_a_worker)
    t2 = threading.Thread(target=session_b_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()


if __name__ == "__main__":
    main()
