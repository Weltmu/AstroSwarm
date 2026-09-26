"""档位权益（plans.json）：档位表由账号服务下发，这里只做读取与兜底。

桌面端、Linux 无头端与账号服务端用的是**同一套语义**：

    member = 档位有效且未开通判断只看它（微信通道看这个判定；trial 不算）

    表里的 all_plugins 是历史字段：2026-09 起插件与能力包全部免费开源，
    运行时不再按档位放行；现在只有微信通道还看 member。

档位表从哪来（优先级从高到低）：
    1. 环境变量 ASTROSWARM_PLANS_FILE
    2. 包内自带的 qbotmanager/assets/plans.json
    3. 本文件里的 _DEFAULT_PLANS（= 官方 plans.json 的内容）

`full` 不能按 plan 名判：那样月费档和 3 天试用都会把自己当成「全解锁」；
微信通道看的是另一个判定（is_member）。
"""
import json
import os
import time
from pathlib import Path

PLANS_FILE_ENV = "ASTROSWARM_PLANS_FILE"
BUNDLED_PLANS = Path(__file__).resolve().parent.parent / "assets" / "plans.json"

# 服务端官方档位定义的内容；读不到任何文件时用它兜底。
_DEFAULT_PLANS = {
    "permanent": {"all_plugins": True, "min_amount": 0},
    "monthly": {"all_plugins": False, "min_amount": 0.01},
    "quarterly": {"all_plugins": False, "min_amount": 0.01},
    "yearly": {"all_plugins": False, "min_amount": 0.01},
}

# 开通了微信通道的档位。trial 不在其中：3 天试用不算。
MEMBER_PLANS = ("permanent", "monthly", "quarterly", "yearly")


def _read_table(path) -> dict:
    out = {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 文件不存在/坏了都退回下一级
        return {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                out[str(key).strip().lower()] = value
    return out


def _candidates() -> list:
    """档位表候选文件，按优先级：环境变量 > 包内自带。"""
    out = []
    env = str(os.environ.get(PLANS_FILE_ENV) or "").strip()
    if env:
        out.append(Path(env).expanduser())
    out.append(BUNDLED_PLANS)
    return out


def plans_path():
    """当前生效的档位表文件；一个都读不出来时返回 None（用内置缺省表）。"""
    for path in _candidates():
        if _read_table(path):
            return path
    return None


def load() -> dict:
    """读档位表：优先级链上第一个能解析出内容的胜出，全失败才用内置缺省表。"""
    for path in _candidates():
        table = _read_table(path)
        if table:
            return table
    return dict(_DEFAULT_PLANS)


def info(plan: str) -> dict:
    return load().get(str(plan or "").strip().lower()) or {}


def allows_all(plan: str) -> bool:
    """该档位是否标记 all_plugins（历史字段）。没定义 → False，不默认全放行。"""
    return bool(info(plan).get("all_plugins"))


def active(exp) -> bool:
    """有效期判断：0/负数表示永久（不限期）。"""
    try:
        exp = float(exp or 0)
    except (TypeError, ValueError):
        return False
    return exp <= 0 or exp > time.time()


def is_member(plan: str, exp) -> bool:
    """档位有效且已开通（trial / none / 未定义档位一律 False）。"""
    return str(plan or "").strip().lower() in MEMBER_PLANS and active(exp)


def all_plugins(plan: str, exp) -> bool:
    """全解锁 = 该档 all_plugins=true 且未过期。"""
    return allows_all(plan) and active(exp)
