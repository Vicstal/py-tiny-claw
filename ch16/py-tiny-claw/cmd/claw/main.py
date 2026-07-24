# cmd/claw/main.py
# 对应 Go 版: cmd/claw/main.go
# 第 16 章：安全拦截 Middleware + 飞书人工审批（人在回路）。
# 运行方式（在 py-tiny-claw 目录下）:
#   ZHIPU_API_KEY=xxx FEISHU_APP_ID=xxx FEISHU_APP_SECRET=xxx python -m cmd.claw.main
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import lark_oapi as lark

from internal.context.session import GLOBAL_SESSION_MGR
from internal.engine.loop import AgentEngine
from internal.feishu.approval import GLOBAL_APPROVAL_MGR, is_dangerous_command
from internal.feishu.bot import FeishuBot
from internal.provider.openai import new_zhipu_openai_provider
from internal.schema.message import Message, ROLE_USER, ToolCall
from internal.tools.bash import BashTool
from internal.tools.edit_file import EditFileTool
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")
log = logging.getLogger(__name__)


def make_webhook_handler(dispatcher: lark.EventDispatcherHandler):
    """把 lark SDK 的事件分发器包装成标准库 http.server 的 Handler"""

    class WebhookHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/webhook/event":
                self.send_response(404)
                self.end_headers()
                return

            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))

            raw_req = lark.RawRequest()
            raw_req.uri = self.path
            raw_req.body = body
            raw_req.headers = {k: v for k, v in self.headers.items()}

            raw_resp = dispatcher.do(raw_req)

            self.send_response(raw_resp.status_code)
            for k, v in (raw_resp.headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if raw_resp.content:
                self.wfile.write(raw_resp.content)

        def log_message(self, fmt, *args):
            pass

    return WebhookHandler


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

    eng = AgentEngine(llm_provider, registry, False, False)

    # 假设一个bot一个session
    session_id = "test_command_intercept_001"
    sess = GLOBAL_SESSION_MGR.get_or_create(session_id, work_dir)
    sess.append(Message(role=ROLE_USER, content=""))

    bot = FeishuBot(eng, sess)
    handler = make_webhook_handler(bot.get_event_dispatcher())

    # 【核心注入】注册安全拦截 Middleware
    def security_middleware(call: ToolCall) -> tuple[bool, str]:
        args_str = call.arguments

        # 检查是否命中高危特征库
        if is_dangerous_command(call.name, args_str):
            task_id = call.id  # 使用大模型生成的唯一 ToolCallID 作为 TaskID

            # 挂起当前线程，发送消息给飞书，死死等待人类的审批！
            allowed, reason = GLOBAL_APPROVAL_MGR.wait_for_approval(
                task_id, call.name, args_str, bot.reporter()
            )

            if not allowed:
                return False, reason  # 拒绝，将理由传回给大模型
            return True, ""  # 同意，放行底层工具

        # 没命中黑名单，直接 YOLO 放行
        return True, ""

    registry.use(security_middleware)

    # 3. 注册路由并启动 HTTP 服务
    port = 48080
    log.info("🚀 py-tiny-claw 飞书服务端已启动，正在监听 :%d 端口", port)

    try:
        HTTPServer(("", port), handler).serve_forever()
    except Exception as e:
        sys.exit(f"服务器启动失败: {e}")


if __name__ == "__main__":
    main()
