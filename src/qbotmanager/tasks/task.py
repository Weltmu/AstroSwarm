"""统一任务系统：任务状态模型与信号协议。"""
import time
from dataclasses import dataclass, field
from enum import Enum

from .qtcompat import QObject, Signal

from ..core.exceptions import CancelledError as TaskCancelled


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskState:
    """一个任务的完整可观测状态。UI 只读这个对象 + 订阅信号。"""
    task_id: str
    task_name: str
    category: str                    # service / install / background
    status: TaskStatus = TaskStatus.PENDING
    current_stage: str = ""
    progress: int = -1               # -1 = 忙碌不确定
    current: int = 0
    total: int = 0
    message: str = ""
    error: str | None = None
    start_time: float = 0.0
    end_time: float | None = None
    retryable: bool = False
    payload: object = None
    result: dict = field(default_factory=dict)
    worker_cls: object = None        # 用于 retry
    extra: dict = field(default_factory=dict)
    logs: list = field(default_factory=list)   # [(ts, level, msg)]，上限 300 条

    def add_log(self, level: str, msg: str):
        self.logs.append((time.time(), level, str(msg)))
        if len(self.logs) > 300:
            del self.logs[: len(self.logs) - 300]


class TaskSignals(QObject):
    """统一信号协议（所有信号第一个参数均为 task_id）。"""
    started = Signal(str, str)                      # task_id, task_name
    stage_changed = Signal(str, str, int, int, str) # task_id, stage, current, total, message
    progress_changed = Signal(str, int)             # task_id, percent(-1=busy)
    log = Signal(str, str, str)                     # task_id, level(INFO/OK/WARN/ERROR), message
    status_changed = Signal(str, str)               # task_id, status
    error = Signal(str, str, str)                   # task_id, stage, message
    finished = Signal(str, str, dict)               # task_id, status(success/failed/cancelled), result
