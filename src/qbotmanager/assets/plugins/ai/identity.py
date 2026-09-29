# -*- coding: utf-8 -*-
"""跨平台身份绑定：同一人在不同平台（QQ / 微信 ClawBot / ...）的 user key 映射。

key 格式：<platform>:<user_id>，如 qq:12345、wechat:o9cq...@im.wechat。
绑定后，任意一个 key 都能解析出整组身份，用于共享用户记忆。
"""
import json
from typing import Dict, List

import nonebot_plugin_localstore as store
from nonebot import logger

IDENTITY_FILE = store.get_plugin_config_file("aichat_identity.json")

_groups: Dict[str, List[str]] = {}  # canonical -> [keys]
_index: Dict[str, str] = {}         # key -> canonical

def load_identity() -> None:
    global _groups, _index
    if IDENTITY_FILE.exists():
        try:
            raw = json.loads(IDENTITY_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _groups = {k: list(v) for k, v in raw.items() if isinstance(v, list)}
                _index = {}
                for canonical, keys in _groups.items():
                    for k in keys:
                        _index[k] = canonical
                return
        except Exception as e:
            logger.warning(f"加载身份绑定失败: {e}")
    _groups = {}
    _index = {}


def save_identity() -> None:
    try:
        IDENTITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        IDENTITY_FILE.write_text(
            json.dumps(_groups, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"保存身份绑定失败: {e}")


def canonical(key: str) -> str:
    return _index.get(key, key)


def resolve(key: str) -> List[str]:
    """返回与 key 同属一组的全部身份 key（含自身）。"""
    c = canonical(key)
    return list(_groups.get(c, [key]))


def bind(key_a: str, key_b: str) -> bool:
    if not key_a or not key_b or key_a == key_b:
        return False
    ca, cb = canonical(key_a), canonical(key_b)
    if ca == cb:
        return False
    group_a = _groups.get(ca, [ca])
    group_b = _groups.get(cb, [cb])
    merged = group_a + group_b
    new_canon = group_a[0]
    _groups.pop(ca, None)
    _groups.pop(cb, None)
    _groups[new_canon] = merged
    for k in merged:
        _index[k] = new_canon
    save_identity()
    return True


def unbind(key: str) -> bool:
    c = canonical(key)
    group = _groups.pop(c, None)
    if group is None:
        return False
    for k in group:
        _index.pop(k, None)
    save_identity()
    return True


def all_bindings() -> List[List[str]]:
    return [list(v) for v in _groups.values() if len(v) > 1]


load_identity()
