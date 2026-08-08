# internal/feishu/approval.py
# 第 16 章：ApprovalManager —— 高危操作的"人在回路"审批：
# 工具执行线程挂起等待，直到人类在飞书里回复 approve/reject。
import logging
import queue
import re
import threading
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class ApprovalResult:
    allowed: bool = False
    reason: str = ""


class ApprovalManager:
    def __init__(self):
        self._mu = threading.Lock()
        # taskID -> 单元素队列（对应 Go 的 chan ApprovalResult, 容量 1）
        self.pending_tasks: dict[str, queue.Queue] = {}

    def wait_for_approval(self, task_id: str, tool_name: str, args: str, reporter) -> tuple[bool, str]:
        ch: queue.Queue = queue.Queue(maxsize=1)

        with self._mu:
            self.pending_tasks[task_id] = ch

        notice_msg = f"""⚠️ **高危操作审批请求**
Agent 试图执行以下动作:
- 工具: {tool_name}
- 参数: {args}

任务 ID: **{task_id}**

👉 请回复 "approve {task_id}" 或 "reject {task_id}" 决定是否放行。"""

        if reporter is not None:
            reporter.send_msg(notice_msg)
        else:
            print(f"\n\033[31m[需要审批 TaskID: {task_id}]\033[0m {notice_msg}")

        log.info("[Approval] 发送审批请求 (TaskID: %s)，线程挂起等待...", task_id)

        # 阻塞当前线程（对应 Go 的 <-ch）
        result: ApprovalResult = ch.get()

        with self._mu:
            del self.pending_tasks[task_id]

        return result.allowed, result.reason

    def resolve_approval(self, task_id: str, allowed: bool, reason: str):
        with self._mu:
            ch = self.pending_tasks.get(task_id)

        if ch is not None:
            log.info("[Approval] 收到飞书审批结果 (TaskID: %s, Allowed: %s)", task_id, allowed)
            ch.put(ApprovalResult(allowed=allowed, reason=reason))


# 全局单例（对应 Go 版的包级变量 GlobalApprovalMgr）
GLOBAL_APPROVAL_MGR = ApprovalManager()


def is_dangerous_command(tool_name: str, args: str) -> bool:
    """检查工具调用是否命中高危特征库（Go 版拦截 >.*\\.go，Python 版对应改为 >.*\\.py）"""
    if tool_name not in ("bash", "write_file", "edit_file"):
        return False

    if tool_name == "bash":
        dangerous_patterns = [r"rm\s+-r", r"sudo\s+", r"drop\s+", r">.*\.py"]
        for p in dangerous_patterns:
            if re.search(p, args):
                return True
    return False
