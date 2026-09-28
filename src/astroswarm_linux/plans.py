"""档位权益（plans.json）：档位表由账号服务下发，这里只做读取与兜底。

与账号服务端是**同一套语义**：

    member = 档位有效且未过期（微信通道看这个判定；3 天试用不算）

    表里的 all_plugins 是历史字段：2026-09 起能力包全部免费开源，
    运行时不再按档位放行；现在只有微信通道还看 member。

档位表从哪来（优先级从高到低）：
    1. config.json 的 plans_file
    2. 环境变量 ASTROSWARM_PLANS_FILE
    3. 包内自带的 <本模块目录>/plans.json
    4. 本文件里的 _DEFAULT_PLANS（= 官方 plans.json 的内容）

档位判定统一读 plans.json，且只认服务器签名过的档位：
只按 plan 名判会让本地改一行 config 就「全解锁」。
"""
import json
import os
import time
from pathlib import Path

PLANS_FILE_ENV = "ASTROSWARM_PLANS_FILE"
BUNDLED_PLANS = Path(__file__).resolve().parent / "plans.json"

# 服务端官方档位定义的内容；读不到任何文件时用它兜底。
# **只有显式 all_plugins=true 的档位才是历史意义上的「全解锁」。**
_DEFAULT_PLANS = {
    "permanent": {"all_plugins": True, "min_amount": 0},
    "monthly": {"all_plugins": False, "min_amount": 0.01},
    "quarterly": {"all_plugins": False, "min_amount": 0.01},
    "yearly": {"all_plugins": False, "min_amount": 0.01},
}

# 开通了微信通道的档位。注意 trial 不在其中：3 天试用不算。
MEMBER_PLANS = ("permanent", "monthly", "quarterly", "yearly")


def _read_table(path) -> dict:
    out = {}
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 —— 文件不存在/坏了都退回下一级
        return {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if isinstance(v, dict):
                out[str(k).strip().lower()] = v
    return out


def _candidates():
    """档位表候选文件，按优先级：config.plans_file > 环境变量 > 包内自带。"""
    out = []
    try:
        from . import headless_config

        cfg = str(headless_config.load().get("plans_file") or "").strip()
    except Exception:  # noqa: BLE001
        cfg = ""
    if cfg:
        out.append(Path(cfg).expanduser())
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
    """读档位表。优先级链上第一个能解析出内容的胜出；全失败才用内置缺省表。

    注意「配置里指的文件没了/坏了」要往**下一级**退（退到包内自带那份），
    而不是直接跳到硬编码缺省表：自建服务只要挪一下 plans.json 的位置，无头端就会
    悄悄换成自己那份定义，和服务端口径对不上。
    """
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
    """历史意义上的全解锁 = 该档 all_plugins=true 且未过期。"""
    return allows_all(plan) and active(exp)
