"""DeepSeek 大脑：OpenAI 兼容 chat/completions + function calling 决策循环"""
import json
import logging

import httpx



MAX_HISTORY_TOTAL = 4000   # 喂给大脑的历史总字数上限
MAX_HISTORY_ITEM = 800     # 单条历史消息字数上限
MAX_USER_TEXT = 2000       # 当前用户消息字数上限


def _fit_history(history):
    """从最近往回裁剪历史：单条限长、总量限长，防止上下文爆炸。"""
    out = []
    total = 0
    for row in reversed(history or []):
        try:
            role = str(row["role"] or "user")
            text = str(row["text"] or "")
        except Exception:  # noqa: BLE001
            role = "user"
            text = ""
        if len(text) > MAX_HISTORY_ITEM:
            text = text[:MAX_HISTORY_ITEM] + "…（已截断）"
        out.append({"role": role, "text": text})
        total += len(text)
        if total >= MAX_HISTORY_TOTAL:
            break
    return list(reversed(out))


class Brain:
    def __init__(self, cfg):
        self.cfg = cfg
        self.headers = {
            "Authorization": f"Bearer {cfg.ds_api_key}",
            "Content-Type": "application/json",
        }

    async def _chat_once(self, messages, tools):
        payload = {
            "model": self.cfg.ds_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.8,
            "max_tokens": self.cfg.ds_max_tokens,
        }
        async with httpx.AsyncClient(timeout=150) as client:
            r = await client.post(f"{self.cfg.ds_api_url}/chat/completions", headers=self.headers, json=payload)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]

    async def think(self, system, history, user_text, tools, tool_exec, max_rounds=6):
        """跑完整决策循环，返回最终回复文本（空串 = 不想说话）"""
        history = _fit_history(history)
        user_text = (user_text or "")[:MAX_USER_TEXT]
        messages = [{"role": "system", "content": system}]
        for row in history:
            messages.append({"role": row["role"], "content": row["text"]})
        messages.append({"role": "user", "content": user_text})

        for _ in range(max_rounds):
            msg = await self._chat_once(messages, tools)
            messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
            if not msg.get("tool_calls"):
                return (msg.get("content") or "").strip()
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                logging.info("调用工具 %s args=%s", name, args)
                result = await tool_exec(name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result,
                })
        return ""
