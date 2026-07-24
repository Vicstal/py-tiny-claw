# internal/provider/openai.py
# 对应 Go 版: internal/provider/openai.go
# 使用 OpenAI 官方 Python SDK（Chat Completions 协议），Base URL 指向智谱的兼容端点。
import os

import openai

from internal.schema.message import (
    Message,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    ToolCall,
    ToolDefinition,
    Usage,
)


class OpenAIProvider:
    def __init__(self, client: openai.OpenAI, model: str):
        self.client = client
        self.model = model

    def generate(self, msgs: list[Message], available_tools: list[ToolDefinition] | None) -> Message:
        # 1. 把内部统一格式的消息翻译为 OpenAI Chat Completions 的格式
        openai_msgs = []

        for msg in msgs:
            if msg.role == ROLE_SYSTEM:
                openai_msgs.append({"role": "system", "content": msg.content})

            elif msg.role == ROLE_USER:
                if msg.tool_call_id != "":
                    # 工具执行结果在 OpenAI 协议中是独立的 "tool" 角色消息
                    openai_msgs.append({
                        "role": "tool",
                        "content": msg.content,
                        "tool_call_id": msg.tool_call_id,
                    })
                else:
                    openai_msgs.append({"role": "user", "content": msg.content})

            elif msg.role == ROLE_ASSISTANT:
                ast_param: dict = {"role": "assistant"}

                # 即使是空字符串 ""，也要发给智谱，否则会触发 1214 错误码
                ast_param["content"] = msg.content

                if len(msg.tool_calls) > 0:
                    tool_calls = []
                    for tc in msg.tool_calls:
                        tool_calls.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                # OpenAI 协议中 arguments 本身就是 JSON 字符串
                                "arguments": tc.arguments,
                            },
                        })
                    ast_param["tool_calls"] = tool_calls

                openai_msgs.append(ast_param)

        # 2. 翻译工具定义为 function tool 格式
        openai_tools = []
        for tool_def in available_tools or []:
            params_schema = tool_def.input_schema if isinstance(tool_def.input_schema, dict) else {}

            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool_def.name,
                    "description": tool_def.description,
                    "parameters": params_schema,
                },
            })

        params = {
            "model": self.model,
            "messages": openai_msgs,
        }
        if openai_tools:
            params["tools"] = openai_tools

        try:
            resp = self.client.chat.completions.create(**params)
        except Exception as e:
            raise RuntimeError(f"OpenAI/Zhipu API 请求失败: {e}") from e
        if len(resp.choices) == 0:
            raise RuntimeError("API 返回了空的 Choices")

        # 3. 把模型响应翻译回内部统一格式
        choice = resp.choices[0].message
        result_msg = Message(
            role=ROLE_ASSISTANT,
            content=choice.content or "",
        )

        for tc in choice.tool_calls or []:
            if tc.type == "function":
                result_msg.tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                ))

        # 【新增】提取 Usage 信息
        if resp.usage is not None and (resp.usage.prompt_tokens > 0 or resp.usage.completion_tokens > 0):
            result_msg.usage = Usage(
                prompt_tokens=int(resp.usage.prompt_tokens),
                completion_tokens=int(resp.usage.completion_tokens),
            )

        return result_msg


def new_zhipu_openai_provider(model: str) -> OpenAIProvider:
    """对应 Go 版的 NewZhipuOpenAIProvider 构造函数"""
    api_key = os.getenv("ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError("请设置 ZHIPU_API_KEY 环境变量")
    base_url = "https://open.bigmodel.cn/api/paas/v4/"
    return OpenAIProvider(
        client=openai.OpenAI(api_key=api_key, base_url=base_url),
        model=model,
    )
