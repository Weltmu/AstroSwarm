"""回复节奏行为包读取：真人回复延迟参数。

配置来源优先级：
1. 环境变量 ASTROSWARM_REPLY_RHYTHM 指向的 JSON 文件（外部行为包注入）；
2. 插件目录内 behavior.json（李清菡人设包内置/捆绑）；
3. 代码默认值（与旧版硬编码行为一致）。
"""
import json
import logging
import os
import random
from pathlib import Path

_DEFAULTS = {
    "activity_delay": {
        "busy_long_probability": 0.35,
        "busy_long_seconds": [180, 900],
        "busy_short_seconds": [8, 40],
        "idle_probability": 0.1,
        "idle_seconds": [60, 180],
    }
}

_cache = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    data = {}
    env_path = os.environ.get("ASTROSWARM_REPLY_RHYTHM", "")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path(__file__).resolve().parent / "behavior.json")
    for path in candidates:
        try:
            if path.is_file():
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and "activity_delay" in raw:
                    data = raw
                    break
        except Exception as exc:  # noqa: BLE001
            logging.warning("读取回复节奏配置失败 %s: %s", path, exc)
    if not data:
        data = _DEFAULTS
    _cache = data
    return _cache


def compute_activity_delay(is_busy: bool, rng=None) -> float:
    """按回复节奏配置计算真人回复延迟（秒），返回 0 表示不延迟。"""
    if rng is None:
        rng = random
    cfg = _load().get("activity_delay") or {}
    if is_busy:
        if rng.random() < float(cfg.get("busy_long_probability", 0.35)):
            lo, hi = cfg.get("busy_long_seconds", [180, 900])
            return rng.uniform(float(lo), float(hi))
        lo, hi = cfg.get("busy_short_seconds", [8, 40])
        return rng.uniform(float(lo), float(hi))
    if rng.random() < float(cfg.get("idle_probability", 0.1)):
        lo, hi = cfg.get("idle_seconds", [60, 180])
        return rng.uniform(float(lo), float(hi))
    return 0.0
