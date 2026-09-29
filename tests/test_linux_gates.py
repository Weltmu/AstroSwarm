# -*- coding: utf-8 -*-
"""运行时闸门。

统一口径：**只有 plans.json 里该档 all_plugins=true（目前只有 permanent）才全解锁**；
其余档位（含 monthly/quarterly/yearly）和 trial 只放行 owned_plugins 里明确买过的包。

覆盖三处闸门：
  * auth.feature_gate()      —— full（全解锁）/ member（付费会员通道）必须分开
  * deploy._allowed_packs()  —— 机器人实际加载哪些付费能力包
  * tools._entitled()        —— 客户端能不能安装某个付费能力包
外加 api._client_ip() 取 XFF 最后一段。
"""
import json
import time

import pytest

from astroswarm_linux import api, auth, deploy, headless_config, platform_info, plans, tools


FUTURE = time.time() + 30 * 86400
PAST = time.time() - 86400


@pytest.fixture
def cfg_home(tmp_path, monkeypatch):
    """把配置/数据目录都指到临时目录，并让权益验签恒过（签名本身另有测试覆盖）。"""
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path / "config")
    monkeypatch.setattr(platform_info, "data_home", lambda: tmp_path / "data")
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(auth, "verify_entitlement", lambda cfg=None: True)
    return tmp_path


def _set_plan(plan, exp=0, owned=()):
    cfg = headless_config.load()
    cfg["plan"] = plan
    cfg["plan_expires_at"] = exp
    cfg["owned_plugins"] = list(owned)
    headless_config.save(cfg)


# ------------------------------------------------------------------ plans.json
def test_plan_allows_all_only_permanent(monkeypatch, tmp_path):
    p = tmp_path / "plans.json"
    p.write_text(json.dumps({
        "permanent": {"all_plugins": True},
        "monthly": {"all_plugins": False},
        "yearly": {"all_plugins": False},
    }), encoding="utf-8")
    monkeypatch.setenv("ASTROSWARM_PLANS_FILE", str(p))
    assert plans.allows_all("permanent") is True
    assert plans.allows_all("monthly") is False
    assert plans.allows_all("yearly") is False
    assert plans.allows_all("trial") is False        # 没定义的档位 = 不放行
    assert plans.allows_all("") is False
    assert plans.allows_all("PERMANENT") is True     # 大小写不敏感


def test_plan_table_can_open_monthly(monkeypatch, tmp_path):
    """档位表是可改的：自建服务把 monthly 标成 all_plugins 才放行（读文件，不写死代码）。"""
    p = tmp_path / "plans.json"
    p.write_text(json.dumps({"monthly": {"all_plugins": True}}), encoding="utf-8")
    monkeypatch.setenv("ASTROSWARM_PLANS_FILE", str(p))
    assert plans.allows_all("monthly") is True


def test_plan_table_broken_file_falls_back(monkeypatch, tmp_path):
    """文件坏了不能变成「全放行」。"""
    p = tmp_path / "plans.json"
    p.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("ASTROSWARM_PLANS_FILE", str(p))
    assert plans.allows_all("monthly") is False
    assert plans.allows_all("permanent") is True     # 退回包内自带那份


def test_plan_table_missing_file_falls_back_to_bundled(monkeypatch, tmp_path):
    """配置指的文件不存在 → 退到包内自带那份（不是直接跳硬编码缺省表），再不行才用内置表。"""
    monkeypatch.setenv("ASTROSWARM_PLANS_FILE", str(tmp_path / "nope.json"))
    assert plans.load()["monthly"]["all_plugins"] is False
    assert plans.load()["permanent"]["all_plugins"] is True
    assert plans.plans_path() == plans.BUNDLED_PLANS


def test_plan_table_config_key_wins(monkeypatch, tmp_path):
    """config.json 的 plans_file 优先于环境变量（运维改哪儿就按哪儿）。"""
    monkeypatch.setattr(platform_info, "config_home", lambda: tmp_path / "cfg")
    (tmp_path / "cfg").mkdir(parents=True, exist_ok=True)
    env_file = tmp_path / "env.json"
    env_file.write_text(json.dumps({"yearly": {"all_plugins": True}}), encoding="utf-8")
    monkeypatch.setenv("ASTROSWARM_PLANS_FILE", str(env_file))
    assert plans.allows_all("yearly") is True

    cfg_file = tmp_path / "cfg.json"
    cfg_file.write_text(json.dumps({"yearly": {"all_plugins": False}}), encoding="utf-8")
    cfg = headless_config.load()
    cfg["plans_file"] = str(cfg_file)
    headless_config.save(cfg)
    assert plans.allows_all("yearly") is False


def test_bundled_plans_json_matches_server_semantics():
    """包内自带的 plans.json 必须与账号服务端的档位定义同一套语义。"""
    raw = json.loads(
        (plans.BUNDLED_PLANS).read_text(encoding="utf-8"))
    assert raw["permanent"]["all_plugins"] is True
    assert raw["monthly"]["all_plugins"] is False
    assert raw["quarterly"]["all_plugins"] is False
    assert raw["yearly"]["all_plugins"] is False


# -------------------------------------------------------------- feature_gate
def test_feature_gate_permanent_unlocks_all(cfg_home):
    _set_plan("permanent")
    gate = auth.feature_gate()
    assert gate["full"] is True and gate["member"] is True, gate
    assert gate["all_plugins"] is True


def test_feature_gate_monthly_is_member_but_not_all_plugins(cfg_home):
    """回归：月费档不是「全解锁」，full 必须为 False。"""
    _set_plan("monthly", FUTURE)
    gate = auth.feature_gate()
    assert gate["full"] is False, gate
    assert gate["member"] is True, gate              # 微信等付费通道照常
    assert gate["all_plugins"] is False


def test_feature_gate_trial_not_member_not_full(cfg_home):
    """回归：3 天试用（plan=trial）不解锁付费包。"""
    _set_plan("trial", FUTURE)
    gate = auth.feature_gate()
    assert gate["full"] is False and gate["member"] is False, gate


def test_feature_gate_expired_permanent_locks(cfg_home):
    _set_plan("permanent", PAST)
    gate = auth.feature_gate()
    assert gate["full"] is False and gate["member"] is False, gate


def test_feature_gate_none_locks(cfg_home):
    _set_plan("none")
    gate = auth.feature_gate()
    assert gate["full"] is False and gate["member"] is False, gate


def test_feature_gate_requires_signature(cfg_home, monkeypatch):
    """没有账号服务签名时，plan 写什么都不算（改 config.json 白改）。"""
    monkeypatch.setattr(auth, "verify_entitlement", lambda cfg=None: False)
    _set_plan("permanent")
    gate = auth.feature_gate()
    assert gate["full"] is False and gate["member"] is False, gate
    assert "签名" in gate["reason"]


# --------------------------------------------------------------- _allowed_packs
def _install_packs(root, *ids):
    for pid in ids:
        d = root / "tool_packs" / pid
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(
            json.dumps({"id": pid, "name": pid, "version": "1.0.0"}), encoding="utf-8")


def test_allowed_packs_loads_every_installed_pack(cfg_home):
    """能力包已全部免费：装了就加载，不再看档位 / 买断 / 签名。"""
    _install_packs(cfg_home / "data", "eva", "proactive", "memory")
    _install_packs(cfg_home / "data", "timer")
    _set_plan("monthly", FUTURE, owned=["timer"])
    allowed = deploy._allowed_packs()
    assert set(allowed) == {"eva", "proactive", "timer", "memory"}, allowed


def test_allowed_packs_unsigned_still_loads(cfg_home, monkeypatch):
    """没签名（未登录/改过配置）也照常加载，不再退回「只放免费包」。"""
    monkeypatch.setattr(auth, "verify_entitlement", lambda cfg=None: False)
    _install_packs(cfg_home / "data", "eva", "proactive")
    _set_plan("permanent")
    assert set(deploy._allowed_packs()) == {"eva", "proactive"}


def test_allowed_packs_skips_broken_manifest(cfg_home):
    """坏包（manifest 没写 id）仍然跳过：不把垃圾目录当成能力包加载。"""
    _install_packs(cfg_home / "data", "eva")
    bad = cfg_home / "data" / "tool_packs" / "broken"
    bad.mkdir(parents=True, exist_ok=True)
    (bad / "manifest.json").write_text("{}", encoding="utf-8")
    assert deploy._allowed_packs() == ["eva"]


# ------------------------------------------------------------------ _entitled
def test_entitled_is_free_for_every_pack(cfg_home):
    """能力包全免费：trial / 未登录 / 无签名都能装。"""
    _set_plan("trial", FUTURE)
    assert tools._entitled("proactive") is True
    assert tools._entitled("memory") is True
    _set_plan("none", 0, owned=[])
    assert tools._entitled("timer") is True


# ------------------------------------------------------------------ _client_ip
class _Req:
    def __init__(self, peer, headers):
        self.client = type("C", (), {"host": peer})()
        self.headers = headers


def test_client_ip_takes_last_xff_segment():
    """nginx 用 $proxy_add_x_forwarded_for（客户端值在前、真实 IP 在末尾），
    取首段等于让调用方自己决定限流桶键。"""
    req = _Req("127.0.0.1", {"x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    assert api._client_ip(req) == "5.6.7.8"


def test_client_ip_prefers_x_real_ip():
    req = _Req("127.0.0.1", {"x-real-ip": "9.9.9.9", "x-forwarded-for": "1.2.3.4, 5.6.7.8"})
    assert api._client_ip(req) == "9.9.9.9"


def test_client_ip_ignores_headers_from_remote_peer():
    """直连（非回环）时完全不看转发头，否则伪造一个 XFF 就绕过限流。"""
    req = _Req("203.0.113.7", {"x-forwarded-for": "1.2.3.4", "x-real-ip": "1.2.3.4"})
    assert api._client_ip(req) == "203.0.113.7"
