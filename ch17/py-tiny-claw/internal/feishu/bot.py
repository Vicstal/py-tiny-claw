# internal/feishu/bot.py
# 第 16 章：飞书机器人增加审批口令拦截 —— "approve <taskID>" / "reject <taskID>"
# 直接唤醒挂起等待的工具执行线程。
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

from internal.context.session import Session
from internal.engine.loop import AgentEngine
from internal.engine.reporter import Reporter
from internal.feishu.approval import GLOBAL_APPROVAL_MGR
from internal.schema.message import Message, ROLE_USER

log = logging.getLogger(__name__)


class FeishuBot:
    def __init__(self, eng: AgentEngine, sess: Session):
        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")

        if not app_id or not app_secret:
            sys.exit("请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")

        client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

        self.client = client
        self.app_id = app_id
        self.app_secret = app_secret
        self.engine = eng
        self.sess = sess
        self.r: FeishuReporter | None = None

    def get_event_dispatcher(self) -> lark.EventDispatcherHandler:
        encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY", "")
        verify_token = os.getenv("FEISHU_VERIFY_TOKEN", "")

        def on_message_receive(event: P2ImMessageReceiveV1) -> None:
            content_str = event.event.message.content
            content_str = content_str.removeprefix('{"text":"')
            content_str = content_str.removesuffix('"}')

            chat_id = event.event.message.chat_id
            log.info("[Feishu] 收到会话 %s 消息: %s", chat_id, content_str)

            # 【新增】：拦截人工审批的特殊口令
            if content_str.startswith("approve "):
                task_id = content_str.removeprefix("approve ").strip()
                # 唤醒挂起的引擎线程！
                GLOBAL_APPROVAL_MGR.resolve_approval(task_id, True, "人类管理员已批准操作")
                log.info("[Feishu] 会话 %s: ✅ 已为您批准任务 %s", chat_id, task_id)
                return
            if content_str.startswith("reject "):
                task_id = content_str.removeprefix("reject ").strip()
                # 唤醒挂起的引擎线程，并反馈拒绝理由！
                GLOBAL_APPROVAL_MGR.resolve_approval(task_id, False, "人类管理员认为该操作存在极高风险，已无情拒绝")
                log.info("[Feishu] 会话 %s: 🚫 已拒绝任务 %s", chat_id, task_id)
                return

            # 如果不是审批命令，则是正常对话，启动一个新的 Agent 任务去处理
            threading.Thread(
                target=self.handle_agent_run, args=(chat_id, content_str), daemon=True
            ).start()

        handler = (
            lark.EventDispatcherHandler.builder(encrypt_key, verify_token)
            .register_p2_im_message_receive_v1(on_message_receive)
            .build()
        )

        return handler

    def reporter(self) -> "FeishuReporter | None":
        return self.r

    def handle_agent_run(self, chat_id: str, prompt: str):
        reporter = FeishuReporter(client=self.client, chat_id=chat_id)

        self.r = reporter
        self.sess.append(Message(role=ROLE_USER, content=prompt))
        try:
            self.engine.run(self.sess, reporter)
        except Exception as e:
            reporter.send_msg(f"❌ Agent 运行崩溃: {e}")


class FeishuReporter(Reporter):
    def __init__(self, client: lark.Client, chat_id: str):
        self.client = client
        self.chat_id = chat_id

    def send_msg(self, text: str):
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
