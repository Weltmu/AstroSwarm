# -*- coding: utf-8 -*-
"""插件工坊配置：独立的生成模型（与「AI 大脑」的 API 完全分开）。

用户 2026-09-27 拍板：工坊只允许"有 agent 编码能力"的强模型
（DeepSeek / ChatGPT(OpenAI) / Claude(Anthropic) / 智谱 GLM / 通义千问 / Kimi）；
没配这几家就拒绝生成 —— 小模型写出来的插件会烂，影响体验。

配置文件：<机器人根>/workshop/config.json
{"provider": "deepseek", "api_url": "...", "api_key": "...", "model": "..."}
"""
import json
from pathlib import Path

from ..ai_config import normalize_api_url

WORKSHOP_PROVIDERS = (
    {"key": "deepseek", "name": "DeepSeek", "protocol": "openai",
     "url": "https://api.deepseek.com", "model": "deepseek-chat"},
    {"key": "openai", "name": "ChatGPT（OpenAI）", "protocol": "openai",
     "url": "https://api.openai.com/v1", "model": "gpt-5.6"},
    {"key": "anthropic", "name": "Claude（Anthropic）", "protocol": "anthropic",
     "url": "https://api.anthropic.com", "model": "claude-sonnet-5"},
    {"key": "zhipu", "name": "智谱 GLM", "protocol": "openai",
     "url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-5.2"},
    {"key": "dashscope", "name": "通义千问（百炼）", "protocol": "openai",
     "url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "model": "qwen3.7-flash"},
    {"key": "moonshot", "name": "Kimi（Moonshot）", "protocol": "openai",
     "url": "https://api.moonshot.cn/v1", "model": "kimi-k3"},
)
PROVIDER_KEYS = tuple(p["key"] for p in WORKSHOP_PROVIDERS)
AGENT_CAPABLE_HINT = "DeepSeek / ChatGPT / Claude / 智谱 GLM / 通义千问 / Kimi"


def provider_defaults(key: str) -> dict:
    for item in WORKSHOP_PROVIDERS:
        if item["key"] == str(key or "").strip():
            return dict(item)
    return {}


def config_file(settings) -> Path:
    return Path(settings.root) / "workshop" / "config.json"


def load(settings) -> dict:
    """读工坊配置（无文件返回空 dict；不抛异常）。"""
    path = config_file(settings)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def resolved(settings) -> dict:
    """工坊配置 + 服务商默认值；provider 不认识就原样返回。"""
    data = load(settings)
    key = str(data.get("provider") or "").strip()
    merged = dict(data)
    defaults = provider_defaults(key)
    if defaults:
        merged["provider"] = key
        merged["protocol"] = defaults["protocol"]
        merged.setdefault("api_url", defaults["url"])
        merged.setdefault("model", defaults["model"])
        merged["provider_name"] = defaults["name"]
    else:
        merged["protocol"] = "openai"
        merged["provider_name"] = "未配置"
    if merged.get("api_url"):
        merged["api_url"] = normalize_api_url(str(merged["api_url"]))
    return merged


def save(settings, data: dict) -> dict:
    """保存工坊配置；服务商必须在白名单里（工坊只认强模型）。"""
    key = str((data or {}).get("provider") or "").strip()
    if key not in PROVIDER_KEYS:
        raise ValueError(
            f"工坊只支持这些服务商：{AGENT_CAPABLE_HINT}（当前填的是 {key or '空'}）")
    defaults = provider_defaults(key)
    clean = {
        "provider": key,
        "api_url": normalize_api_url(str((data or {}).get("api_url")
                                        or defaults["url"])),
        "api_key": str((data or {}).get("api_key") or "").strip(),
        "model": str((data or {}).get("model") or defaults["model"]).strip(),
    }
    path = config_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return clean


def is_ready(settings) -> tuple:
    """(能不能生成, 大白话原因)。原因只给人看，不暴露密钥。"""
    cfg = resolved(settings)
    key = str(cfg.get("provider") or "")
    if key not in PROVIDER_KEYS:
        return False, (f"还没给插件工坊配模型。工坊必须用强模型（{AGENT_CAPABLE_HINT}），"
                       "不然生成的插件容易不能用。")
    if not cfg.get("api_key"):
        return False, f"插件工坊的 {cfg.get('provider_name')} 还没填 API Key。"
    if not cfg.get("model"):
        return False, "插件工坊还没选模型名。"
    return True, f"已配置：{cfg.get('provider_name')} · {cfg.get('model')}"


def mask_key(key: str) -> str:
    key = str(key or "")
    if len(key) <= 8:
        return "*" * len(key)
    return key[:4] + "*" * (len(key) - 8) + key[-4:]
