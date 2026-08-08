# cmd/claw/main.py
# 第 9 章：启动一个 HTTP 服务，接收飞书 Webhook 事件，把 Agent 接入群聊。
# Go 版用 net/http + httpserverext；Python 版用标准库 http.server 手工适配 lark SDK。
# 运行方式（在 py-tiny-claw 目录下）:
#   ZHIPU_API_KEY=xxx FEISHU_APP_ID=xxx FEISHU_APP_SECRET=xxx python -m cmd.claw.main
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import lark_oapi as lark

from internal.engine.loop import AgentEngine
from internal.feishu.bot import FeishuBot
from internal.provider.openai import new_zhipu_openai_provider
from internal.tools.bash import BashTool
from internal.tools.edit_file import EditFileTool
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S")
log = logging.getLogger(__name__)


def make_webhook_handler(dispatcher: lark.EventDispatcherHandler):
    """把 lark SDK 的事件分发器包装成标准库 http.server 的 Handler
    （对应 Go 版的 httpserverext.NewEventHandlerFunc）"""

    class WebhookHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/webhook/event":
                self.send_response(404)
                self.end_headers()
                return

            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))

            # 构造 lark SDK 的原始请求对象并交给分发器处理
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
            pass  # 静默 http.server 自带的访问日志

    return WebhookHandler


def main():
    if not os.getenv("ZHIPU_API_KEY"):
        sys.exit("请先导出 ZHIPU_API_KEY")

    work_dir = os.getcwd()
    llm_provider = new_zhipu_openai_provider("glm-4.5-air")

    registry = new_registry()
    registry.register(ReadFileTool(work_dir))
    registry.register(WriteFileTool(work_dir))
    registry.register(BashTool(work_dir))
    registry.register(EditFileTool(work_dir))

    eng = AgentEngine(llm_provider, registry, work_dir, True)

    bot = FeishuBot(eng)
    handler = make_webhook_handler(bot.get_event_dispatcher())

    port = 48080
    log.info("🚀 py-tiny-claw 飞书服务端已启动，正在监听 :%d 端口", port)

    try:
        HTTPServer(("", port), handler).serve_forever()
    except Exception as e:
        sys.exit(f"服务器启动失败: {e}")


if __name__ == "__main__":
    main()
