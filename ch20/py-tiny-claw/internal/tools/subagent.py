# internal/tools/subagent.py
# 第 17 章：spawn_subagent 工具 —— 主 Agent 派出"探路者"子智能体做深度探索，
# 只把精炼的摘要报告带回主上下文。
import json
import logging
from abc import ABC, abstractmethod

from internal.schema.message import ToolDefinition
from internal.tools.registry import BaseTool, Registry

log = logging.getLogger(__name__)


class AgentRunner(ABC):
    """AgentRunner 定义了引擎向外部工具暴露的特定执行能力接口"""

    @abstractmethod
    def run_sub(self, task_prompt: str, read_only_registry: Registry, reporter) -> str:
        ...


class SubagentTool(BaseTool):
    def __init__(self, runner: AgentRunner, read_only_registry: Registry, reporter):
        self.runner = runner
        self.read_only_registry = read_only_registry
        # reporter 不限定具体类型（对应 Go 版的 interface{}），由 run_sub 内部按 Reporter 使用
        self.reporter = reporter

    def name(self) -> str:
        return "spawn_subagent"

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name(),
            description="派出一个专门用于深度探索（Exploration）的子智能体。当你需要阅读大量代码、跨文件查找逻辑时请调用此工具。它在探索完毕后，会给你返回一份极度精炼的摘要报告。",
            input_schema={
                "type": "object",
                "properties": {
                    "task_prompt": {
                        "type": "string",
                        "description": "给子智能体下达的明确探索指令。",
                    },
                },
                "required": ["task_prompt"],
            },
        )

    def execute(self, args: str) -> str:
        try:
            input_args = json.loads(args)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"解析参数失败: {e}") from e

        task_prompt = input_args.get("task_prompt", "")

        log.info("[Subagent] 🚀 主 Agent 发起委派！正在拉起探路者: [%s]...", task_prompt)

        # 【修改】：在接口调用中，将工具持有的 reporter 透传下去
        try:
            summary = self.runner.run_sub(task_prompt, self.read_only_registry, self.reporter)
        except Exception as e:
            return f"子智能体执行失败: {e}"

        log.info("[Subagent] ✅ 子智能体任务结束。报告返回给主干...")

        return f"【子智能体探索报告】:\n{summary}"
