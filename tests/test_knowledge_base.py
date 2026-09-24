# -*- coding: utf-8 -*-
"""本地知识库测试：文档入库/检索/删除 + AI 内置 knowledge_search 工具。"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_test_ptr_")))

from qbotmanager.core import knowledge_base  # noqa: E402
from qbotmanager.core.settings import Settings  # noqa: E402


def test_add_search_delete():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_kb_"))
    s = Settings(tmp)
    s.ensure_dirs()
    text = ("AstroSwarm 星群是一款 Windows 桌面多平台 AI 机器人管理工具，"
            "支持 QQ 与微信统一大脑、本地记忆、插件生态。" * 3)
    knowledge_base.add_document(s, "产品介绍.md", text)
    docs = knowledge_base.list_documents(s)
    assert len(docs) == 1 and docs[0]["title"] == "产品介绍.md"
    res = knowledge_base.search(s, "星群 机器人 管理", top_k=3)
    assert res and res[0]["doc"] == "产品介绍.md"
    assert "AstroSwarm" in res[0]["snippet"]
    knowledge_base.delete_document(s, docs[0]["id"])
    assert knowledge_base.list_documents(s) == []
    print("OK knowledge add_search_delete")


def test_builtin_knowledge_search_tool():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_kb_tool_"))
    s = Settings(tmp)
    s.ensure_dirs()
    knowledge_base.add_document(
        s, "定价.md", "星群会员每月 20 元，永久版 599 元（首发 499 元）。")
    os.environ["ASTROSWARM_KNOWLEDGE_DIR"] = str(knowledge_base.docs_dir(s))

    from qbotmanager.core.agent.runtime import get_runtime
    from qbotmanager.core.agent.tool import ToolContext

    rt = get_runtime()
    out = rt.execute(
        "knowledge_search", {"query": "会员 永久版 价格"},
        ToolContext(permissions=set()))
    data = json.loads(out)
    assert data["ok"] is True
    assert data["results"] and "会员" in data["results"][0]["snippet"]
    print("OK knowledge builtin_tool")


if __name__ == "__main__":
    test_add_search_delete()
    test_builtin_knowledge_search_tool()
