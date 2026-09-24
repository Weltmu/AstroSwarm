"""联网搜索工具：Bing RSS 搜索，返回结构化结果（数据层），
语言表述（怎么告诉用户、怎么带来源）由 agent 负责。

零密钥、纯标准库；失败返回结构化错误码而不是人话文案。
"""
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

SEARCH_URL = "https://cn.bing.com/search"
MAX_RESULTS = 5


def _http_get_text(url, timeout=12):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(300000).decode("utf-8", "ignore")


def web_search(query: str, max_results: int = MAX_RESULTS) -> dict:
    """执行搜索，返回结构化结果 dict；任何失败都返回错误码。"""
    query = (query or "").strip()
    if not query:
        return {"ok": False, "error": "empty_query"}
    q = urllib.parse.quote(query)
    try:
        raw = _http_get_text(f"{SEARCH_URL}?format=rss&q={q}")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "search_failed", "detail": str(exc)}
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return {"ok": False, "error": "parse_failed", "detail": str(exc)}
    items = []
    for item in root.iter("item"):
        title = " ".join((item.findtext("title") or "").split())
        link = (item.findtext("link") or "").strip()
        desc = re.sub(r"<[^>]+>", "", item.findtext("description") or "")
        desc = " ".join(desc.split())[:240]
        if not title:
            continue
        items.append({"title": title, "link": link, "snippet": desc})
        if len(items) >= max_results:
            break
    if not items:
        return {"ok": True, "query": query, "results": []}
    return {"ok": True, "query": query, "results": items}


def handle(ctx, args):
    query = str(args.get("query") or "").strip()
    if not query:
        return json.dumps({"ok": False, "error": "empty_query"},
                          ensure_ascii=False)
    return json.dumps(web_search(query), ensure_ascii=False)
