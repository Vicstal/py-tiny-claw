# internal/feishu/bot.py
# 对应 Go 版: internal/feishu/bot.go
# 第 22 章：AgentOps 收官改造 ——
# 1) Reporter 通过上下文传递（Go 用 context.WithValue，Python 用 contextvars 对应实现），
#    解决并发场景下 Middleware 如何拿到"当前会话专属 Reporter"的问题；
# 2) 引擎改为工厂模式创建，每个会话动态挂上专属的 CostTracker。
import contextvars
import json
import logging
import os
import sys
import threading
from typing import Callable

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
)

from internal.context.session import GLOBAL_SESSION_MGR, Session
from internal.engine.loop import AgentEngine
from internal.engine.reporter import Reporter
from internal.feishu.approval import GLOBAL_APPROVAL_MGR
from internal.schema.message import Message, ROLE_USER

log = logging.getLogger(__name__)

# ==========================================
# 1. Context 传递机制：解决并发 Reporter 的提取
# ==========================================

# _reporter_var 是上下文中存放 Reporter 的专属变量（对应 Go 的 reporterKey + context.WithValue）
_reporter_var: contextvars.ContextVar[Reporter | None] = contextvars.ContextVar("reporter", default=None)


def context_with_reporter(r: Reporter):
    """将专属的 Reporter 封入当前上下文"""
    return _reporter_var.set(r)


def reporter_from_context() -> Reporter | None:
    """供底层的 Middleware 提取专属的 Reporter 发送审批卡片"""
    return _reporter_var.get()


# ==========================================
# 2. 飞书 Bot 核心调度器
# ==========================================

# AgentEngineFactory 允许每次收到消息时，根据 Session 动态创建引擎
AgentEngineFactory = Callable[[Session], AgentEngine]


class FeishuBot:
    def __init__(self, factory: AgentEngineFactory, work_dir: str):
        app_id = os.getenv("FEISHU_APP_ID")
        app_secret = os.getenv("FEISHU_APP_SECRET")

        if not app_id or not app_secret:
            sys.exit("请设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET")

        client = lark.Client.builder().app_id(app_id).app_secret(app_secret).build()

        self.client = client
        self.app_id = app_id
        self.app_secret = app_secret
        self.work_dir = work_dir  # 保存从入口传来的工作区路径
        self.factory = factory    # 替换掉原来的单一 engine 引用

    def get_event_dispatcher(self) -> lark.EventDispatcherHandler:
        encrypt_key = os.getenv("FEISHU_ENCRYPT_KEY", "")
        verify_token = os.getenv("FEISHU_VERIFY_TOKEN", "")

        def on_message_receive(event: P2ImMessageReceiveV1) -> None:
            content_str = event.event.message.content
            content_str = content_str.removeprefix('{"text":"')
            content_str = content_str.removesuffix('"}')

            chat_id = event.event.message.chat_id
            log.info("[Feishu] 收到会话 %s 消息: %s", chat_id, content_str)

            # 拦截人工审批的特殊口令，并唤醒挂起的 Registry 线程
            if content_str.startswith("approve "):
                task_id = content_str.removeprefix("approve ").strip()
                GLOBAL_APPROVAL_MGR.resolve_approval(task_id, True, "人类管理员已批准操作")
                log.info("[Feishu] 会话 %s: ✅ 已为您批准任务 %s", chat_id, task_id)
                return
            if content_str.startswith("reject "):
                task_id = content_str.removeprefix("reject ").strip()
                GLOBAL_APPROVAL_MGR.resolve_approval(task_id, False, "人类管理员认为该操作存在极高风险，已无情拒绝")
                log.info("[Feishu] 会话 %s: 🚫 已拒绝任务 %s", chat_id, task_id)
                return

            # 如果是普通对话，新开一个线程去启动 Agent，防止阻塞 Webhook
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
        # 为当前并发请求实例化一个专属的 Reporter
        reporter = FeishuReporter(client=self.client, chat_id=chat_id)

        # 1. 获取物理隔离的 Session
        sess = GLOBAL_SESSION_MGR.get_or_create(chat_id, self.work_dir)
        sess.append(Message(role=ROLE_USER, content=prompt))

        # 2. 通过工厂模式，为当前会话生成一个挂好了专属 CostTracker 的新引擎
        eng = self.factory(sess)

        # 3. 【驾驭核心】：将专属的 reporter 塞入上下文并传给引擎！
        #    （本线程内设置 contextvar，引擎并发执行工具时会经由 copy_context 继承下去）
        context_with_reporter(reporter)

        try:
            eng.run(sess, reporter)
        except Exception as e:
            reporter.send_msg(f"❌ Agent 运行崩溃: {e}")


# ==========================================
# 3. 飞书 Reporter 实现
# ==========================================

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
