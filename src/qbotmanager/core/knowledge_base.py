# -*- coding: utf-8 -*-
"""本地知识库（轻量 RAG）：txt/md 文档入库、分块、检索（数据不出本机）。

无第三方依赖：中文按字符二元组 + 英文单词做词袋，检索按重叠打分；
文档量不大时足够用。AI 通过内置 knowledge_search 工具调用。
"""
import hashlib
import json
import re
from pathlib import Path

CHUNK_SIZE = 220
CHUNK_OVERLAP = 40


def docs_dir(settings) -> Path:
    return Path(settings.root) / "knowledge"


def _tokens(text: str) -> list:
    text = (text or "").lower()
    words = re.findall(r"[a-z0-9]+", text)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return words + bigrams


def _chunks(text: str, size: int = CHUNK_SIZE,
            overlap: int = CHUNK_OVERLAP) -> list:
    text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    out = []
    for p in paras:
        if len(p) <= size:
            out.append(p)
            continue
        step = size - overlap
        for i in range(0, len(p), step):
            out.append(p[i:i + size])
    return out or [""]


def _doc_id(title: str) -> str:
    return hashlib.sha1((title or "doc").encode("utf-8")).hexdigest()[:16]


def add_document(settings, title: str, text: str,
                 doc_id: str | None = None) -> dict:
    root = docs_dir(settings)
    root.mkdir(parents=True, exist_ok=True)
    pid = doc_id or _doc_id(title)
    (root / f"{pid}.txt").write_text(
        json.dumps({"title": title, "text": text or ""}, ensure_ascii=False),
        encoding="utf-8")
    return {"ok": True, "id": pid, "title": title,
            "chunks": len(_chunks(text))}


def list_documents(settings) -> list:
    root = docs_dir(settings)
    out = []
    if not root.exists():
        return out
    for f in sorted(root.glob("*.txt")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            out.append({
                "id": f.stem,
                "title": str(data.get("title") or f.stem),
                "chunks": len(_chunks(str(data.get("text") or ""))),
            })
        except (ValueError, OSError):
            continue
    return out


def delete_document(settings, doc_id: str) -> dict:
    f = docs_dir(settings) / f"{doc_id}.txt"
    if f.exists():
        f.unlink()
    return {"ok": True, "id": doc_id}


def search_dir(root, query: str, top_k: int = 3) -> list:
    root = Path(root) if root else None
    if root is None or not root.exists() or not str(query or "").strip():
        return []
    qset = set(_tokens(query))
    scored = []
    for f in sorted(root.glob("*.txt")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        title = str(data.get("title") or f.stem)
        for i, chunk in enumerate(_chunks(str(data.get("text") or ""))):
            overlap = sum(1 for t in qset if t in _tokens(chunk))
            if overlap <= 0:
                continue
            scored.append({
                "doc": title,
                "chunk": i,
                "score": overlap,
                "snippet": chunk[:160],
            })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def search(settings, query: str, top_k: int = 3) -> list:
    return search_dir(docs_dir(settings), query, top_k=top_k)
