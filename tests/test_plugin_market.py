# -*- coding: utf-8 -*-
"""官方插件市场测试：清单解析、插件条目校验、manifest 适配器校验、下载校验。"""
import base64
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if not os.environ.get("QBM_POINTER_DIR"):
    os.environ["QBM_POINTER_DIR"] = str(Path(tempfile.mkdtemp(prefix="qbm_test_ptr_")))

from qbotmanager.core import plugin_market  # noqa: E402


def _entry(overrides=None):
    e = {
        "id": "daily-motto",
        "name": "每日一言",
        "version": "1.0.0",
        "category": "功能扩展",
        "description": "每天一句",
        "url": "https://astroswarm.cn/plugins/daily-motto-1.0.0.zip",
        "sha256": "abc",
        "adapters": ["qq_official", "wechat_ilink"],
    }
    e.update(overrides or {})
    return e


def test_parse_market_list_and_object():
    raw_list = json.dumps([_entry()], ensure_ascii=False)
    out = plugin_market.parse_market(raw_list)
    assert out and out[0]["id"] == "daily-motto"
    raw_obj = json.dumps({"categories": ["智能体档案", "功能扩展"], "plugins": [_entry()]},
                         ensure_ascii=False)
    out = plugin_market.parse_market(raw_obj)
    assert out and out[0]["name"] == "每日一言"


def test_parse_market_filters_bad_entries():
    raw = json.dumps([_entry(), {"id": ""}, {"name": "no-id"}, "junk"], ensure_ascii=False)
    out = plugin_market.parse_market(raw)
    assert len(out) == 1 and out[0]["id"] == "daily-motto"


def test_parse_market_bad_json_returns_empty():
    assert plugin_market.parse_market("not json") == []
    assert plugin_market.parse_market("") == []


def test_validate_market_plugin():
    assert plugin_market.validate_market_plugin(_entry()) is None
    assert plugin_market.validate_market_plugin(_entry({"url": ""})) is not None
    assert plugin_market.validate_market_plugin(_entry({"sha256": ""})) is not None
    assert plugin_market.validate_market_plugin(_entry({"version": ""})) is not None
    # 明文 http / 非白名单域名 / 伪装子域一律拒绝
    assert plugin_market.validate_market_plugin(
        _entry({"url": "https://example.com/plugins/x.zip"})) is not None
    assert plugin_market.validate_market_plugin(
        _entry({"url": "https://evil.example.com/x.zip"})) is not None
    assert plugin_market.validate_market_plugin(
        _entry({"url": "https://astroswarm.cn.evil.example.com/x.zip"})) is not None
    assert plugin_market.validate_market_plugin(
        _entry({"url": "https://astroswarm.cn/plugins/x.zip"})) is None


def test_url_allowlist():
    ok = plugin_market.url_allowed
    assert ok("https://astroswarm.cn/plugins/market.json") is True
    assert ok("https://www.astroswarm.cn/x.zip") is True
    assert ok("https://cdn.astroswarm.cn/x.zip") is True
    assert ok("http://astroswarm.cn/x.zip") is False       # 明文一律拒
    assert ok("https://example.com/x.zip") is False
    assert ok("https://evil.example.com/x.zip") is False
    assert ok("https://astroswarm.cn.evil.example.com/x.zip") is False
    assert ok("ftp://astroswarm.cn/x.zip") is False
    assert ok("") is False
    os.environ["QBM_MARKET_ALLOW_HOSTS"] = "cdn.example.com"
    try:
        assert ok("https://cdn.example.com/x.zip") is True
        assert ok("http://cdn.example.com/x.zip") is False   # 追加主机也必须是 https
    finally:
        os.environ.pop("QBM_MARKET_ALLOW_HOSTS", None)


def test_verify_manifest_signature():
    """签名覆盖清单原始字节：改一个字节 / 换签名 / 换公钥 / 坏 base64 都必须失败。"""
    from nacl.signing import SigningKey

    sk = SigningKey.generate()
    pub = sk.verify_key.encode().hex()
    raw = json.dumps({"plugins": [_entry()]}, ensure_ascii=False).encode("utf-8")
    good = base64.b64encode(sk.sign(raw).signature).decode()
    assert plugin_market.verify_manifest(raw, good, pub) is True
    assert plugin_market.verify_manifest(raw + b" ", good, pub) is False
    assert plugin_market.verify_manifest(raw, base64.b64encode(b"x" * 64).decode(), pub) is False
    assert plugin_market.verify_manifest(
        raw, good, SigningKey.generate().verify_key.encode().hex()) is False
    assert plugin_market.verify_manifest(raw, "not-base64!!", pub) is False
    assert plugin_market.verify_manifest(raw, "", pub) is False


def test_fetch_market_fails_closed_without_valid_signature():
    """清单没签名 / 签名不对 → 一条都不返回；签名对了才加载。"""
    from nacl.signing import SigningKey

    raw = json.dumps({"plugins": [_entry()]}, ensure_ascii=False).encode("utf-8")
    market = "https://astroswarm.cn/plugins/market.json"

    def opener_factory(sig):
        def _opener(url):
            return sig if str(url).endswith(".sig") else raw
        return _opener

    def not_found(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    # 1) 签名文件拿不到 → 空
    assert plugin_market.fetch_market(market, opener=not_found) == []
    # 2) 签名对不上 → 空，并且给出能展示给用户的原因
    assert plugin_market.fetch_market(market, opener=opener_factory("AAAA")) == []
    assert "签名" in plugin_market.LAST_ERROR
    # 3) 明文 http 清单地址 → 直接拒绝（不发请求）
    calls = []
    assert plugin_market.fetch_market(
        "https://example.com/plugins/market.json",
        opener=lambda u: calls.append(u) or raw) == []
    assert calls == [] and "白名单" in plugin_market.LAST_ERROR
    # 4) 正确签名 → 正常解析（用测试自己的密钥对走完整流程）
    sk = SigningKey.generate()
    sig = base64.b64encode(sk.sign(raw).signature).decode()
    got = plugin_market.fetch_market(
        market, opener=opener_factory(sig), public_key_hex=sk.verify_key.encode().hex())
    assert got and got[0]["id"] == "daily-motto"
    assert plugin_market.LAST_ERROR == ""


def test_download_plugin_rejects_off_allowlist_url():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_mkt_block_"))
    dest = tmp / "x.zip"
    calls = []
    for bad in ("http://astroswarm.cn/plugins/x.zip",
                "https://example.com/plugins/x.zip",
                "https://evil.example.com/x.zip",
                "https://astroswarm.cn.evil.example.com/x.zip"):
        try:
            plugin_market.download_plugin(bad, dest, opener=lambda u: calls.append(u) or b"x")
            raise AssertionError("非白名单地址应被拒绝：" + bad)
        except RuntimeError as e:
            assert "白名单" in str(e), e
    assert calls == [] and not dest.exists()


def _make_zip(path, manifest):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("daily-motto/plugin.json", json.dumps(manifest, ensure_ascii=False))
        z.writestr("daily-motto/__init__.py", "# -*- coding: utf-8 -*-\n")


def test_read_and_validate_manifest():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_mkt_"))
    zpath = tmp / "p.zip"
    _make_zip(zpath, {
        "id": "daily-motto", "name": "每日一言", "version": "1.0.0",
        "adapters": ["qq_official"],
    })
    manifest = plugin_market.read_plugin_manifest(zpath)
    assert manifest and manifest["id"] == "daily-motto"
    assert plugin_market.validate_plugin_manifest(manifest) is None


def test_validate_manifest_rejects_unsupported_adapter():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_mkt2_"))
    zpath = tmp / "p.zip"
    _make_zip(zpath, {
        "id": "napcat-tool", "name": "NapCat 工具", "version": "1.0.0",
        "adapters": ["onebot_v11"],
    })
    manifest = plugin_market.read_plugin_manifest(zpath)
    err = plugin_market.validate_plugin_manifest(manifest)
    assert err is not None and "不兼容" in err


def test_validate_manifest_requires_fields():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_mkt3_"))
    zpath = tmp / "p.zip"
    _make_zip(zpath, {"id": "x"})
    manifest = plugin_market.read_plugin_manifest(zpath)
    assert plugin_market.validate_plugin_manifest(manifest) is not None


def test_download_plugin_checks_sha256():
    tmp = Path(tempfile.mkdtemp(prefix="qbm_mkt4_"))
    zpath = tmp / "src.zip"
    _make_zip(zpath, {"id": "daily-motto", "name": "每日一言", "version": "1.0.0",
                      "adapters": ["qq_official"]})
    data = zpath.read_bytes()
    good = hashlib.sha256(data).hexdigest()
    dest = tmp / "out.zip"
    plugin_market.download_plugin(
        "https://astroswarm.cn/plugins/p.zip", dest, sha256=good,
        opener=lambda url: data)
    assert dest.exists() and dest.read_bytes() == data

    bad_dest = tmp / "bad.zip"
    try:
        plugin_market.download_plugin(
            "https://astroswarm.cn/plugins/p.zip", bad_dest, sha256="0" * 64,
            opener=lambda url: data)
        raise AssertionError("sha256 不匹配应抛错")
    except RuntimeError:
        assert not bad_dest.exists() or bad_dest.read_bytes() != data


def test_download_plugin_forbidden_friendly_error():
    """服务端返回 401/403 时，应给中文提示（可手动去官网下载），而不是裸 HTTP 错误。"""
    tmp = Path(tempfile.mkdtemp(prefix="qbm_mkt_auth_"))
    dest = tmp / "out.zip"

    def forbidden_opener(url):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    try:
        plugin_market.download_plugin(
            "https://astroswarm.cn/plugins/p.zip", dest, opener=forbidden_opener)
        raise AssertionError("403 应抛 RuntimeError")
    except RuntimeError as e:
        assert "拒绝" in str(e) and "下载" in str(e)
        assert not dest.exists()


def test_authed_opener_sends_token():
    """默认下载 opener 应带上已登录星群账号的 Bearer token。"""
    seen = {}

    class FakeResp:
        def read(self):
            return b"zip-bytes"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout=20):
        seen["auth"] = req.get_header("Authorization")
        seen["timeout"] = timeout
        return FakeResp()

    with mock.patch.object(plugin_market, "_account_token", return_value="tok-123"), \
            mock.patch.object(plugin_market.urllib.request, "urlopen", fake_urlopen):
        opener = plugin_market._authed_opener(timeout=7)
        assert opener("https://astroswarm.cn/plugins/p.zip") == b"zip-bytes"
    assert seen.get("auth") == "Bearer tok-123"
    assert seen.get("timeout") == 7


def test_settings_developer_mode_roundtrip():
    from qbotmanager.core.settings import Settings
    tmp = Path(tempfile.mkdtemp(prefix="qbm_devmode_"))
    s = Settings(tmp)
    s.ensure_dirs()
    s.developer_mode = True
    s.save()
    s2 = Settings.load(tmp)
    assert s2.developer_mode is True
    assert Settings(tmp).developer_mode is False


def test_plugin_access_tiers():
    """商店权益判定：2026-09 起能力包全部免费，任何档位/未登录都可装。"""
    free = _entry({"tier": "free"})
    member = _entry({"id": "member-pack", "tier": "member"})
    buy = _entry({"id": "pro-pack", "tier": "buy"})

    # 旧清单里写 tier=member/buy 的条目现在也一律免费放行
    for e in (free, member, buy, _entry({"tier": "unknown"})):
        for ent in ({}, {"full": False}, {"full": False, "member": True},
                    {"full": True, "owned_plugins": ["pro-pack"]}):
            access = plugin_market.plugin_access(e, ent)
            assert access["allowed"] is True, (e, ent, access)
            assert access["label"] == "免费", access

    # entry_tier 恒为 free（旧档位字段不再影响判定）
    assert plugin_market.entry_tier(member) == "free"
    assert plugin_market.entry_tier(buy) == "free"
    assert plugin_market.entry_tier(_entry({})) == "free"


if __name__ == "__main__":
    test_parse_market_list_and_object()
    print("OK parse_market")
    test_parse_market_filters_bad_entries()
    print("OK parse_market_filter")
    test_parse_market_bad_json_returns_empty()
    print("OK parse_market_bad_json")
    test_validate_market_plugin()
    print("OK validate_market_plugin")
    test_url_allowlist()
    print("OK url_allowlist")
    test_verify_manifest_signature()
    print("OK verify_manifest_signature")
    test_fetch_market_fails_closed_without_valid_signature()
    print("OK fetch_market_fails_closed_without_valid_signature")
    test_download_plugin_rejects_off_allowlist_url()
    print("OK download_plugin_rejects_off_allowlist_url")
    test_read_and_validate_manifest()
    print("OK read_validate_manifest")
    test_validate_manifest_rejects_unsupported_adapter()
    print("OK validate_manifest_adapter")
    test_validate_manifest_requires_fields()
    print("OK validate_manifest_fields")
    test_download_plugin_checks_sha256()
    print("OK download_plugin_sha256")
    test_download_plugin_forbidden_friendly_error()
    print("OK download_plugin_forbidden_friendly_error")
    test_authed_opener_sends_token()
    print("OK authed_opener_sends_token")
    test_settings_developer_mode_roundtrip()
    print("OK settings_developer_mode_roundtrip")
    test_plugin_access_tiers()
    print("OK plugin_access_tiers")
