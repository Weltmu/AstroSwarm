# -*- coding: utf-8 -*-
"""桌面端档位闸门：与无头端 / 账号服务端必须同一套 plans.json 语义。

起因：桌面端以前按 plan 名判「全解锁」（monthly 也 full=True），
月费档就能装遍付费包，与服务端下载口的口径不一致。现在两端都读 plans.json。
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_gate_ptr_")))
# 无头端模块会去读它的配置目录，隔离到临时目录，别碰本机真实配置
os.environ.setdefault("XDG_CONFIG_HOME", tempfile.mkdtemp(prefix="qbm_gate_cfg_"))
os.environ.setdefault("XDG_DATA_HOME", os.environ["XDG_CONFIG_HOME"])

from qbotmanager.core import license as lic  # noqa: E402
from qbotmanager.core import plans as dplans  # noqa: E402

FUTURE = time.time() + 86400 * 30
PAST = time.time() - 10
CASES = [
    ("permanent", 0),
    ("monthly", FUTURE),
    ("quarterly", FUTURE),
    ("yearly", FUTURE),
    ("monthly", PAST),
    ("trial", FUTURE),
    ("none", 0),
    ("nonsense", FUTURE),
]


def _trust_plan():
    lic.verify_entitlement = lambda *a, **k: True


def _gate(plan, exp, owned=None):
    orig = lic.load_license
    try:
        lic.load_license = lambda: {
            "plan": plan, "plan_expires_at": exp, "owned_plugins": owned or []}
        return lic.feature_gate()
    finally:
        lic.load_license = orig


def test_plans_json_same_in_desktop_and_headless():
    """两份 plans.json 必须一字不差（改档位要两边一起改）。"""
    desk = json.loads(
        (ROOT / "src" / "qbotmanager" / "assets" / "plans.json").read_text(encoding="utf-8"))
    head = json.loads(
        (ROOT / "src" / "astroswarm_linux" / "plans.json").read_text(encoding="utf-8"))
    desk.pop("_comment", None)
    head.pop("_comment", None)
    assert desk == head, "桌面端与无头端的 plans.json 不一致"
    assert desk["permanent"]["all_plugins"] is True
    for pid in ("monthly", "quarterly", "yearly"):
        assert desk[pid]["all_plugins"] is False, pid


def test_desktop_and_headless_logic_agree():
    """两端的档位判定必须给出同样结论（防止只改一边）。"""
    from astroswarm_linux import plans as hplans

    for plan, exp in CASES:
        assert dplans.allows_all(plan) == hplans.allows_all(plan), plan
        assert dplans.is_member(plan, exp) == hplans.is_member(plan, exp), (plan, exp)
        assert dplans.all_plugins(plan, exp) == hplans.all_plugins(plan, exp), (plan, exp)


def test_plans_table_is_configurable(monkeypatch, tmp_path):
    """档位表可改：自建部署把 monthly 标成 all_plugins 才放行（读文件，不写死代码）。"""
    p = tmp_path / "plans.json"
    p.write_text(json.dumps({"monthly": {"all_plugins": True}}), encoding="utf-8")
    monkeypatch.setenv(dplans.PLANS_FILE_ENV, str(p))
    assert dplans.allows_all("monthly") is True
    assert dplans.allows_all("permanent") is False   # 表里没定义 → 不默认放行
    monkeypatch.delenv(dplans.PLANS_FILE_ENV, raising=False)
    assert dplans.allows_all("monthly") is False


def test_gate_only_permanent_unlocks_all_plugins():
    _trust_plan()
    for plan, exp in (("monthly", FUTURE), ("quarterly", FUTURE),
                      ("yearly", FUTURE), ("trial", FUTURE)):
        gate = _gate(plan, exp)
        assert gate["full"] is False and gate["all_plugins"] is False, (plan, gate)
    assert _gate("permanent", 0)["full"] is True


def test_gate_member_covers_paid_channels_but_not_trial():
    """微信等付费通道看 member：月费/季费/年费/永久都算，3 天试用不算。"""
    _trust_plan()
    for plan in ("permanent", "monthly", "quarterly", "yearly"):
        assert _gate(plan, FUTURE)["member"] is True, plan
    assert _gate("permanent", 0)["member"] is True
    assert _gate("trial", FUTURE)["member"] is False
    assert _gate("none", 0)["member"] is False
    assert _gate("monthly", PAST)["member"] is False


def test_gate_without_signature_is_free():
    import importlib

    importlib.reload(lic)
    orig = lic.load_license
    try:
        lic.load_license = lambda: {"plan": "permanent"}
        gate = lic.feature_gate()
        assert gate["full"] is False and gate["member"] is False
        assert "签名" in gate["reason"]
        ent = lic.entitlements()
        assert ent["full"] is False and ent["member"] is False
    finally:
        lic.load_license = orig
