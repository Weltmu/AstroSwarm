# -*- coding: utf-8 -*-
"""NoneBot 官方/社区插件市场在线搜索。

星群桌面端内置 NoneBot 内核，用户可在「设置 → 开发者模式」开启后，在线搜索
NoneBot 官方商店（https://registry.nonebot.dev）里的社区开源插件。

本模块只负责拉取清单 / 搜索 / 兼容性判定，真正的 pip 安装与 pyproject 注册
交给 plugins.install_store_plugin 处理。来自社区的开源插件未经星群校验，
其源码、可用性、许可协议由各自作者负责；默认不安装 GPL/AGPL 类插件，
商业使用前请用户自行核对许可证。
"""
from __future__ import annotations

import json
import urllib.request

REGISTRY_URLS = [
    "https://registry.nonebot.dev/plugins.json",
    # CDN 镜像（主源被墙/超时时兜底）
    "https://cdn.jsdelivr.net/gh/nonebot/registry@results/plugins.json",
]

# 星群当前支持的 NoneBot 协议适配器：
#   QQ 官方机器人 / OneBot V11（NapCat 等）/ 微信 iLink（ClawBot）
SUPPORTED_ADAPTERS = (
    "nonebot.adapters.qq",
    "nonebot.adapters.onebot.v11",
    "nonebot.adapters.ilink",
    "nonebot_adapter_ilink",
)


def fetch_registry(timeout: int = 15) -> list:
    """拉取 NoneBot 官方插件清单，按顺序尝试主源与 CDN 镜像。

    返回条目列表（dict）；全部失败时抛出 RuntimeError（含最后一个错误）。
    """
    last_err: Exception | None = None
    for url in REGISTRY_URLS:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "AstroSwarm/1.0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                return [e for e in data if isinstance(e, dict)]
            raise ValueError("返回格式不是列表")
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    raise RuntimeError("无法连接 NoneBot 插件市场: %s" % last_err)


def search_plugins(entries: list, query: str = "") -> list:
    """按查询词过滤条目（名称/模块名/PyPI 包名/简介/作者）。空查询返回全部。"""
    q = (query or "").strip().lower()
    if not q:
        return list(entries)
    out = []
    for e in entries:
        hay = " ".join(
            [
                str(e.get("name") or ""),
                str(e.get("module_name") or ""),
                str(e.get("project_link") or ""),
                str(e.get("desc") or ""),
                str(e.get("author") or ""),
            ]
        ).lower()
        if q in hay:
            out.append(e)
    return out


def adapter_compat(entry: dict) -> tuple:
    """返回 (是否兼容当前协议, 提示文字)。

    supported_adapters 为 None / 空列表表示未声明限制（通常通用）；
    声明列表只要与星群支持的适配器有交集即可装。
    """
    ad = entry.get("supported_adapters")
    if ad is None:
        return True, "未声明协议限制（通常通用）"
    if not isinstance(ad, list) or not ad:
        return True, "未声明协议限制（通常通用）"
    hits = [a for a in ad if str(a) in SUPPORTED_ADAPTERS]
    if hits:
        return True, "兼容当前协议"
    return False, "不兼容当前协议（声明: %s）" % ", ".join(str(a) for a in ad)
