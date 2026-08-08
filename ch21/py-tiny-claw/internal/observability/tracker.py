# internal/observability/tracker.py
# 第 18 章：CostTracker —— 用"装饰器模式"包裹真实 Provider，
# 无侵入地统计每次 API 调用的耗时、Token 消耗与费用。
import logging
import time
from dataclasses import dataclass

from internal.context.session import Session
from internal.provider.interface import LLMProvider
from internal.schema.message import Message, ToolDefinition

log = logging.getLogger(__name__)


@dataclass
class Pricing:
    input_price: float = 0.0   # 每百万 Token 的输入价格 (CNY)
    output_price: float = 0.0  # 每百万 Token 的输出价格 (CNY)


# 定价表（对应 Go 版的包级变量 PricingModel）
PRICING_MODEL: dict[str, Pricing] = {
    "glm-4.5-air": Pricing(input_price=0.15, output_price=0.15),
}


class CostTracker(LLMProvider):
    def __init__(self, next_provider: LLMProvider, model_name: str, session: Session | None):
        self.next_provider = next_provider
        self.model_name = model_name
        self.session = session

    def generate(self, msgs: list[Message], available_tools: list[ToolDefinition] | None) -> Message:
        start_time = time.monotonic()

        try:
            resp_msg = self.next_provider.generate(msgs, available_tools)
        except Exception:
            latency = time.monotonic() - start_time
            log.info("[Tracker] ❌ API 调用失败，耗时: %.3fs", latency)
            raise

        latency = time.monotonic() - start_time

        if resp_msg.usage is not None:
            prompt_tokens = resp_msg.usage.prompt_tokens
            completion_tokens = resp_msg.usage.completion_tokens

            cost = 0.0
            price = PRICING_MODEL.get(self.model_name)
            if price is not None:
                cost = (prompt_tokens * price.input_price + completion_tokens * price.output_price) / 1000000.0

            log.info(
                "[Tracker] 📊 API 调用完成 | 耗时: %.3fs | 输入: %d tk | 输出: %d tk | 花费: ¥%.6f",
                latency, prompt_tokens, completion_tokens, cost,
            )

            if self.session is not None:
                self.session.record_usage(prompt_tokens, completion_tokens, cost)
                log.info("[Tracker] 💰 当前会话 (%s) 累计花费: ¥%.6f", self.session.id, self.session.total_cost_cny)
        else:
            log.info("[Tracker] ⚠️ API 调用完成，但未返回 Usage 数据 | 耗时: %.3fs", latency)

        return resp_msg
