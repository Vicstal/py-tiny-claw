# internal/feishu/bot.py
# 第 9 章：飞书机器人 —— 接收群聊消息事件，触发 Agent 运行，并把过程回报到群里。
# 使用飞书官方 Python SDK: lark-oapi (对应 Go 版的 larksuite/oapi-sdk-go)
import json
import logging
import os
import sys
import threading

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
)

from internal.engine.loop import AgentEngine
from internal.engine.reporter import Reporter

log = logging.getLogger(__name__)


class FeishuBot:
    def __init__(self, eng: AgentEngine):
        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")

        if not app_id or not app_secret:
            sys.exit("请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")

        client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

        self.client = client
        self.app_id = app_id
        self.app_secret = app_secret
        self.engine = eng

    def get_event_dispatcher(self) -> lark.EventDispatcherHandler:
        encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY", "")
        verify_token = os.getenv("FEISHU_VERIFY_TOKEN", "")

        def on_message_receive(event: P2ImMessageReceiveV1) -> None:
            # 消息内容形如 {"text":"用户输入"}，这里粗暴地剥掉外壳（与 Go 版保持一致）
            content_str = event.event.message.content
            content_str = content_str.removeprefix('{"text":"')
            content_str = content_str.removesuffix('"}')

            chat_id = event.event.message.chat_id
            log.info("[Feishu] 收到会话 %s 消息: %s", chat_id, content_str)

            # 后台线程运行 Agent（对应 Go 版的 go b.handleAgentRun），
            # 避免阻塞事件回调导致飞书侧超时重推。
            threading.Thread(
                target=self.handle_agent_run, args=(chat_id, content_str), daemon=True
            ).start()

        handler = (
            lark.EventDispatcherHandler.builder(encrypt_key, verify_token)
            .register_p2_im_message_receive_v1(on_message_receive)
            .build()
        )

        return handler

    def handle_agent_run(self, chat_id: str, prompt: str):
        reporter = FeishuReporter(client=self.client, chat_id=chat_id)

        try:
            self.engine.run(prompt, reporter)
        except Exception as e:
            reporter.send_msg(f"❌ Agent 运行崩溃: {e}")


class FeishuReporter(Reporter):
    """把引擎的关键事件转发到飞书群聊（实现 engine.Reporter 接口）"""

    def __init__(self, client: lark.Client, chat_id: str):
        self.client = client
        self.chat_id = chat_id

    def send_msg(self, text: str):
        # Build text message content
        text_content = {"text": text}
        content_str = json.dumps(text_content, ensure_ascii=False)

        msg_req = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(self.chat_id)
                .msg_type("text")
                .content(content_str)
                .build()
            )
            .build()
        )

        self.client.im.v1.message.create(msg_req)

    def on_thinking(self):
        self.send_msg("🤔 模型正在慢思考 (Thinking)...")

    def on_tool_call(self, tool_name: str, args: str):
        self.send_msg(f"🛠️ **正在执行工具**：`{tool_name}`\n参数：`{args}`")

    def on_tool_result(self, tool_name: str, result: str, is_error: bool):
        if is_error:
            self.send_msg(f"⚠️ **执行报错** ({tool_name})：\n{result}")
        else:
            self.send_msg(f"✅ **执行成功** ({tool_name})")

    def on_message(self, content: str):
        self.send_msg(content)
