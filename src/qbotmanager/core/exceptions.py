"""统一取消异常：core 层在长任务中被取消时抛出，由任务系统识别为“已取消”而非失败。"""


class CancelledError(RuntimeError):
    """任务被用户取消。"""