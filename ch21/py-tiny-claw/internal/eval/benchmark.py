# internal/eval/benchmark.py
# 对应 Go 版: internal/eval/benchmark.go
# 第 20 章：BenchmarkRunner —— 自动化评测：沙箱隔离 + Setup 靶机 + Agent 干活 + 脚本判卷。
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field

from internal.context.session import Session
from internal.engine.loop import AgentEngine
from internal.observability.tracker import CostTracker
from internal.provider.openai import new_zhipu_openai_provider
from internal.schema.message import Message, ROLE_USER
from internal.tools.bash import BashTool
from internal.tools.edit_file import EditFileTool
from internal.tools.read_file import ReadFileTool
from internal.tools.registry import new_registry
from internal.tools.write_file import WriteFileTool

log = logging.getLogger(__name__)


@dataclass
class TestCase:
    """TestCase 定义了一个需要 Agent 去完成并验证的独立任务"""
    id: str = ""               # 用例唯一标识
    name: str = ""             # 用例名称
    setup_script: str = ""     # 【可选】在 Agent 运行前执行的 bash 脚本 (用于初始化靶机代码)
    task_prompt: str = ""      # 发送给 Agent 的任务指令
    validate_script: str = ""  # 【核心】在 Agent 运行结束后执行的 bash 校验脚本。exit 0 视为成功，其他视为失败
    max_turns: int = 0         # 允许 Agent 尝试的最大轮数 (超时算失败)


@dataclass
class TestResult:
    """TestResult 存放单次跑分结果"""
    test_case_id: str = ""
    passed: bool = False
    total_cost_cny: float = 0.0
    duration_ms: int = 0
    error_msg: str = ""


class BenchmarkRunner:
    def __init__(self, model: str):
        self.model_name = model

    def run_suite(self, testcases: list[TestCase]):
        """执行一组评测集，并返回跑分报告"""
        log.info("==================================================")
        log.info("🚀 启动自动化 Harness Benchmark 评估... | 模型: %s", self.model_name)
        log.info("==================================================")

        results: list[TestResult] = []
        passed_count = 0
        total_cost = 0.0

        for tc in testcases:
            log.info("\n>>> ⏳ 正在执行用例 [%s]: %s", tc.id, tc.name)

            res = self.run_single_test(tc)
            results.append(res)

            if res.passed:
                passed_count += 1
                log.info(">>> ✅ 用例 [%s] 测试通过! | 耗时: %dms | 花费: $%.6f", tc.id, res.duration_ms, res.total_cost_cny)
            else:
                log.info(">>> ❌ 用例 [%s] 测试失败! | 错误: %s", tc.id, res.error_msg)
            total_cost += res.total_cost_cny

        # 打印终极报表
        log.info("\n================ 🏆 跑分终极报告 ================")
        log.info("总用例数: %d | 成功数: %d | 成功率: %.2f%%", len(testcases), passed_count, passed_count / len(testcases) * 100)
        log.info("总消耗成本: $%.6f", total_cost)
        log.info("==================================================")

    def run_single_test(self, tc: TestCase) -> TestResult:
        start_time = time.monotonic()

        # 1. 为每个用例创建一个绝对干净的沙箱目录 (物理隔离)
        work_dir = os.getcwd()
        work_dir += f"/workspace/{tc.id}_{int(time.time())}"
        os.makedirs(work_dir, exist_ok=True)

        # 2. (可选) 执行 Setup 脚本准备靶机代码
        if tc.setup_script != "":
            proc = subprocess.run(["bash", "-c", tc.setup_script], cwd=work_dir)
            if proc.returncode != 0:
                return TestResult(test_case_id=tc.id, passed=False, error_msg="靶机 Setup 失败")

        # 3. 组装具备打点能力 (Tracker) 的引擎
        real_provider = new_zhipu_openai_provider(self.model_name)  # 使用真实的 GLM API
        session = Session(tc.id, work_dir)  # 为本次跑分单独建一个 Session 记账
        tracked_provider = CostTracker(real_provider, self.model_name, session)

        registry = new_registry()
        registry.register(ReadFileTool(work_dir))
        registry.register(WriteFileTool(work_dir))
        registry.register(BashTool(work_dir))
        registry.register(EditFileTool(work_dir))

        eng = AgentEngine(tracked_provider, registry, False, False)

        # 4. 让 Agent 开始干活
        session.append(Message(role=ROLE_USER, content=tc.task_prompt))
        # 我们传入一个空的 reporter 屏蔽普通日志，防止刷屏
        try:
            eng.run(session, None)
        except Exception as e:
            return TestResult(test_case_id=tc.id, passed=False, error_msg=f"Agent 崩溃: {e}")

        # 5. 【核心断言】Agent 跑完了，我们来验收成果！
        proc = subprocess.run(["bash", "-c", tc.validate_script], cwd=work_dir, capture_output=True, text=True)
        out = proc.stdout + proc.stderr

        duration = int((time.monotonic() - start_time) * 1000)

        if proc.returncode != 0:
            return TestResult(
                test_case_id=tc.id,
                passed=False,
                total_cost_cny=session.total_cost_cny,
                duration_ms=duration,
                error_msg=f"验证脚本执行失败: {out}",
            )

        return TestResult(
            test_case_id=tc.id,
            passed=True,
            total_cost_cny=session.total_cost_cny,
            duration_ms=duration,
        )
