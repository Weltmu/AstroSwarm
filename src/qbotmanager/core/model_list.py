# -*- coding: utf-8 -*-
"""按用户填的接口地址 + API Key，拉服务商**真实**的模型列表。

为什么不再用写死的预设：服务商上新/改名很快，预设一过期，用户在下拉里
根本选不到自己账号真有的模型（2026-09-29 用户反馈 DeepSeek 预设已过期）。

做法：走各家都提供的 OpenAI 兼容 `GET /models`（Anthropic 走自家
`GET /v1/models`），按 base_url 拼候选地址依次试；拿不到就抛
ModelListError，把「哪一步失败」原样告诉用户，界面保留预设并允许手填，
绝不把用户卡在空下拉上。
"""
import json
import re
import urllib.error
import urllib.request

from .ai_config import normalize_api_url

__all__ = ["ModelListError", "candidate_endpoints", "parse_models",
           "fetch_models", "DEFAULT_TIMEOUT"]

DEFAULT_TIMEOUT = 12.0
_VERSION_SEG = re.compile(r"/v\d+[a-z]*$", re.I)
_MAX_BYTES = 2 * 1024 * 1024


class ModelListError(RuntimeError):
    """拉模型列表失败。消息直接给用户看，绝不带 API Key。"""


def candidate_endpoints(api_url: str, protocol: str = "openai") -> list:
    """按 base_url 拼出候选的「列模型」地址（去重、保持顺序）。"""
    base = normalize_api_url(api_url)
    if not base:
        return []
    if str(protocol or "openai").strip().lower() == "anthropic":
        if base.endswith("/models"):
            return [base]
        if base.endswith("/v1"):
            return [base + "/models"]
        return [base + "/v1/models"]
    if base.endswith("/models"):
        return [base]
    out = [base + "/models"]
    if not _VERSION_SEG.search(base):
        # 根地址（https://api.deepseek.com）或只给了域名时再补一条 v1
        out.append(base + "/v1/models")
    return out


def _push(out: list, value) -> None:
    text = str(value or "").strip()
    if text and text not in out:
        out.append(text)


def parse_models(payload) -> list:
    """吃下各家五花八门的返回结构，只吐出模型名列表。

    覆盖 OpenAI（{"data":[{"id":...}]}）、Anthropic（同 OpenAI 形状）、
    以及 {"models":[...]} / {"model_list":[...]} / 纯数组这几种。
    """
    out = []
    if isinstance(payload, dict):
        for key in ("data", "models", "model_list"):
            items = payload.get(key)
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        _push(out, item.get("id") or item.get("name")
                              or item.get("model"))
                    else:
                        _push(out, item)
        if not out and isinstance(payload.get("id"), str):
            _push(out, payload.get("id"))
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                _push(out, item.get("id") or item.get("name") or item.get("model"))
            else:
                _push(out, item)
    return out


def _headers(api_key: str, protocol: str) -> dict:
    if str(protocol or "openai").strip().lower() == "anthropic":
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Accept": "application/json",
            "User-Agent": "AstroSwarm",
        }
    return {
        "Authorization": "Bearer " + api_key,
        "Accept": "application/json",
        "User-Agent": "AstroSwarm",
    }


def fetch_models(api_url: str, api_key: str, protocol: str = "openai",
                 timeout: float = DEFAULT_TIMEOUT) -> dict:
    """拉模型列表：成功返回 {"models": [...], "endpoint": 实际用的地址}。

    失败抛 ModelListError，消息里只带地址与 HTTP 状态，不带密钥。
    """
    key = (api_key or "").strip()
    if not key:
        raise ModelListError("还没填 API 密钥")
    endpoints = candidate_endpoints(api_url, protocol)
    if not endpoints:
        raise ModelListError("还没填接口地址")
    problems = []
    for url in endpoints:
        req = urllib.request.Request(url, headers=_headers(key, protocol), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(_MAX_BYTES)
        except urllib.error.HTTPError as exc:
            problems.append(f"{url} → HTTP {exc.code}")
            continue
        except urllib.error.URLError as exc:
            problems.append(f"{url} → 连不上（{exc.reason}）")
            continue
        except Exception as exc:  # noqa: BLE001 —— 超时/证书等一律算这一条失败
            problems.append(f"{url} → {exc}")
            continue
        try:
            payload = json.loads(body.decode("utf-8", "ignore") or "{}")
        except ValueError:
            problems.append(f"{url} → 返回的不是 JSON")
            continue
        models = parse_models(payload)
        if models:
            return {"models": sorted(models, key=lambda s: s.lower()),
                    "endpoint": url, "count": len(models)}
        problems.append(f"{url} → 返回里没有模型列表")
    raise ModelListError("；".join(problems[:3]) or "获取失败")
