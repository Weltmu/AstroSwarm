"""TaskManager：统一任务调度器。

并发规则：
- service   同时最多 1 个（启动/停止/重启/切换互斥）
- install   同时最多 1 个（部署/插件/依赖）
- background 同时最多 1 个（WS 注入、背景视频准备等，可与 service/install 并行）

排队的任务保持 pending 状态；运行中的任务可协作式取消；失败任务可重试。
"""
import time

from .qtcompat import QObject

from .task import TaskState, TaskStatus
from .workers import TaskWorker


class TaskManager(QObject):
    started = TaskWorker.started
    stage_changed = TaskWorker.stage_changed
    progress_changed = TaskWorker.progress_changed
    log = TaskWorker.log
    status_changed = TaskWorker.status_changed
    error = TaskWorker.error
    finished = TaskWorker.finished

    CATEGORY_LIMITS = {"service": 1, "install": 1, "background": 1}
    HISTORY_LIMIT = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self._workers: dict[str, TaskWorker] = {}
        self._states: dict[str, TaskState] = {}
        self._history: list[TaskState] = []
        self._queue: list[dict] = []
        self._seq = 0

    # ------------------------------------------------------------ 提交
    def submit(self, task_name, category, worker_cls, payload=None, retryable=False, **extra) -> str:
        """提交一个任务。worker_cls 的 __init__ 签名：
        (task_id, task_name, category, payload, **extra)
        """
        self._seq += 1
        task_id = f"t{self._seq}"
        state = TaskState(
            task_id=task_id,
            task_name=task_name,
            category=category,
            payload=payload,
            retryable=retryable,
            worker_cls=worker_cls,
            extra=dict(extra),
        )
        self._states[task_id] = state
        entry = {"task_id": task_id, "cls": worker_cls, "state": state}
        if self._can_start(category):
            self._start_entry(entry)
        else:
            self._queue.append(entry)
            self.status_changed.emit(task_id, TaskStatus.PENDING.value)
        return task_id

    def _can_start(self, category) -> bool:
        running = sum(
            1 for s in self._states.values()
            if s.category == category and s.status == TaskStatus.RUNNING
        )
        return running < self.CATEGORY_LIMITS.get(category, 1)

    def _start_entry(self, entry: dict):
        state: TaskState = entry["state"]
        try:
            worker: TaskWorker = entry["cls"](
                task_id=state.task_id,
                task_name=state.task_name,
                category=state.category,
                payload=state.payload,
                **state.extra,
            )
        except Exception as e:  # noqa: BLE001
            state.status = TaskStatus.FAILED
            state.error = str(e)
            state.end_time = time.time()
            self._finalize(state)
            self.error.emit(state.task_id, "创建任务", str(e))
            self.finished.emit(state.task_id, TaskStatus.FAILED.value, {"error": str(e)})
            return
        self._workers[state.task_id] = worker
        worker.started.connect(lambda tid, name, st=state: self._on_started(st, tid, name))
        worker.stage_changed.connect(lambda tid, s, c, t, m, st=state: self._on_stage(st, tid, s, c, t, m))
        worker.progress_changed.connect(lambda tid, p, st=state: self._on_progress(st, tid, p))
        worker.log.connect(lambda tid, lv, msg, st=state: self._on_log(st, tid, lv, msg))
        worker.status_changed.connect(lambda tid, sts, st=state: self._on_status(st, tid, sts))
        worker.error.connect(lambda tid, stage, msg, st=state: self._on_error(st, tid, stage, msg))
        worker.finished.connect(lambda tid, sts, res, st=state: self._on_finished(st, tid, sts, res))
        worker.start()

    # ------------------------------------------------------------ 信号落地
    def _on_started(self, state: TaskState, tid, name):
        state.status = TaskStatus.RUNNING
        state.start_time = time.time()
        self.started.emit(tid, name)
        self.status_changed.emit(tid, TaskStatus.RUNNING.value)

    def _on_stage(self, state: TaskState, tid, stage, current, total, message):
        state.current_stage = stage
        state.current = current
        state.total = total
        state.message = message
        self.stage_changed.emit(tid, stage, current, total, message)

    def _on_progress(self, state: TaskState, tid, pct):
        state.progress = pct
        self.progress_changed.emit(tid, pct)

    def _on_log(self, state: TaskState, tid, level, msg):
        state.add_log(level, msg)
        self.log.emit(tid, level, msg)

    def _on_status(self, state: TaskState, tid, status):
        state.status = TaskStatus(status)
        self.status_changed.emit(tid, status)

    def _on_error(self, state: TaskState, tid, stage, msg):
        state.error = msg
        self.error.emit(tid, stage, msg)

    def _on_finished(self, state: TaskState, tid, status, result):
        state.status = TaskStatus(status)
        state.end_time = time.time()
        state.result = result or {}
        self._workers.pop(tid, None)
        self._states.pop(tid, None)
        self._history.append(state)
        if len(self._history) > self.HISTORY_LIMIT:
            del self._history[: len(self._history) - self.HISTORY_LIMIT]
        self.finished.emit(tid, status, result)
        self._pump()

    def _finalize(self, state: TaskState):
        """创建 worker 即失败时直接进入历史。"""
        self._states.pop(state.task_id, None)
        self._history.append(state)
        if len(self._history) > self.HISTORY_LIMIT:
            del self._history[: len(self._history) - self.HISTORY_LIMIT]

    def _pump(self):
        for category in self.CATEGORY_LIMITS:
            if self._can_start(category):
                for entry in list(self._queue):
                    if entry["state"].category == category:
                        self._queue.remove(entry)
                        self._start_entry(entry)
                        break

    # ------------------------------------------------------------ 查询/控制
    def get(self, task_id) -> TaskState | None:
        st = self._states.get(task_id)
        if st is not None:
            return st
        for h in reversed(self._history):
            if h.task_id == task_id:
                return h
        return None

    def active_states(self) -> list:
        return [s for s in self._states.values()]

    def recent_states(self, n=20) -> list:
        active = [s for s in self._states.values()]
        history = list(reversed(self._history))
        return (active + history)[:n]

    def cancel(self, task_id) -> bool:
        for entry in self._queue:
            if entry["task_id"] == task_id:
                self._queue.remove(entry)
                st: TaskState = entry["state"]
                st.status = TaskStatus.CANCELLED
                st.end_time = time.time()
                self._finalize(st)
                self.status_changed.emit(task_id, TaskStatus.CANCELLED.value)
                self.finished.emit(task_id, TaskStatus.CANCELLED.value, {})
                # 队列里可能还有同类别任务在等待：取消后立即放行下一个
                self._pump()
                return True
        worker = self._workers.get(task_id)
        if worker is not None:
            worker.cancel()
            return True
        return False

    def retry(self, task_id) -> str | None:
        st = self.get(task_id)
        if st is None or not st.retryable:
            return None
        return self.submit(
            st.task_name, st.category, st.worker_cls,
            payload=st.payload, retryable=True, **st.extra,
        )

    def has_active(self, category=None) -> bool:
        for s in self._states.values():
            if s.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                if category is None or s.category == category:
                    return True
        return False
