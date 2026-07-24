# internal/provider/claude.py
# 对应 Go 版: internal/provider/claude.go
# 使用 Anthropic 官方 Python SDK（Messages API 协议），Base URL 指向智谱的兼容端点。
import json
import os

import anthropic

from internal.schema.message import (
    Message,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    ToolCall,
    ToolDefinition,
    Usage,
)


class ClaudeProvider:
    def __init__(self, client: anthropic.Anthropic, model: str):
        self.client = client
        self.model = model

    def generate(self, msgs: list[Message], available_tools: list[ToolDefinition] | None) -> Message:
        # 1. 把内部统一格式的消息翻译为 Anthropic Messages API 的格式
        anthropic_msgs = []
        system_prompt = ""

        for msg in msgs:
            if msg.role == ROLE_SYSTEM:
                # Anthropic 协议中 system prompt 是独立的顶层参数，不放进 messages
                system_prompt = msg.content
            elif msg.role == ROLE_USER:
                if msg.tool_call_id != "":
                    # 工具执行结果：以 tool_result block 的形式包装在 user 消息中
                    anthropic_msgs.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content,
                            "is_error": False,
                        }],
                    })
                else:
                    anthropic_msgs.append({
                        "role": "user",
                        "content": [{"type": "text", "text": msg.content}],
                    })
            elif msg.role == ROLE_ASSISTANT:
                blocks = []
                # 即使 content 是空的，也要填充一个空的 text block，否则引发 1214 错误
                blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    # 手动构造 tool_use block（arguments 是 JSON 字符串，需要解析回 dict）
                    try:
                        input_map = json.loads(tc.arguments) if tc.arguments else {}
                    except json.JSONDecodeError:
                        input_map = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": input_map,
                    })
                if blocks:
                    anthropic_msgs.append({"role": "assistant", "content": blocks})

        # 2. 翻译工具定义：input_schema 里的 properties / required 拆出来填充
        anthropic_tools = []
        for tool_def in available_tools or []:
            properties = {}
            required = []

            if isinstance(tool_def.input_schema, dict):
                properties = tool_def.input_schema.get("properties", {})
                required = tool_def.input_schema.get("required", [])

            anthropic_tools.append({
                "name": tool_def.name,
                "description": tool_def.description,
                "input_schema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            })

        params = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": anthropic_msgs,
        }

        if system_prompt != "":
            params["system"] = system_prompt

        if anthropic_tools:
            params["tools"] = anthropic_tools

        try:
            resp = self.client.messages.create(**params)
        except Exception as e:
            raise RuntimeError(f"Claude/Zhipu API 请求失败: {e}") from e

        # 3. 把模型响应翻译回内部统一格式
        result_msg = Message(role=ROLE_ASSISTANT)

        for block in resp.content:
            if block.type == "text":
                result_msg.content += block.text
            elif block.type == "tool_use":
                args_str = json.dumps(block.input, ensure_ascii=False)
                result_msg.tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=args_str,
                ))

        # 【新增】提取并封装 Token 消耗 (Claude 特有的 Usage 字段名)
        if resp.usage.input_tokens > 0 or resp.usage.output_tokens > 0:
            result_msg.usage = Usage(
                prompt_tokens=int(resp.usage.input_tokens),
                completion_tokens=int(resp.usage.output_tokens),
            )

        return result_msg


def new_zhipu_claude_provider(model: str) -> ClaudeProvider:
    """对应 Go 版的 NewZhipuClaudeProvider 构造函数"""
    api_key = os.getenv("ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError("请设置 ZHIPU_API_KEY 环境变量")
    base_url = "https://open.bigmodel.cn/api/anthropic"
    return ClaudeProvider(
        client=anthropic.Anthropic(api_key=api_key, base_url=base_url),
        model=model,
    )
