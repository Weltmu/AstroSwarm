"""无头配置：JSON 存取（config_home/config.json）。"""
import json
import logging
import os
import shutil
import time
from pathlib import Path

from . import platform_info

DEFAULTS = {
    "port": 7860,
    "bot_port": 12113,
    "qq_app_id": "",
    "qq_app_secret": "",
    "qq_app_token": "",
    # 第三方 OneBot 协议端（NapCat / LLOneBot 等）：默认反向 WS，协议端来连我们
    "qq_channel": "onebot",
    "qq_onebot_mode": "reverse",
    "qq_onebot_host": "127.0.0.1",
    "qq_onebot_port": 0,
    "qq_onebot_path": "/onebot/v11/ws",
    "qq_onebot_token": "",
    "qq_onebot_listen_host": "127.0.0.1",
    # 智能体档案（李清菡等）
    "agent_profile_enabled": False,
    "agent_profile_id": "star_helper",
    # 李清菡档案接管 QQ 后，只回 owner_qq 的私聊 —— 不填就「机器人收到消息但一声不吭」
    "agent_owner_qq": "",
    "agent_groups": "",
    "agent_address_words": "",
    "agent_persona_mode": "",
    "ai_provider": "deepseek",
    "ai_api_key": "",
    "ai_base_url": "https://api.deepseek.com",
    "ai_model": "deepseek-v4-flash",
    # 与桌面端对齐：平台开关 / 视觉模型 / 唤醒词。
    # 这几个键不在白名单里时，控制台改了会被静默丢弃，表现就是「机器人一声不吭」。
    "ai_platforms": {"qq": True, "wechat": True, "feishu": True, "telegram": True},
    "vision_api_url": "",
    "vision_api_key": "",
    "vision_model": "",
    "agent_wake_words": "",
    "agent_wake_auto": True,
    # 本地人设工坊：当前启用的人设 id（空 = 没启用）。无头端从控制台启用/停用时写这里，
    # deploy.build_settings 读它 → 机器人进程拿到 ASTROSWARM_PERSONAS_ALLOWED。
    "local_persona_id": "",
    # 星群账号服务地址（登录 / 认领 / 兑换 / 拉权益都走它）。
    # **留空 = 用官方托管服务**（https://astroswarm.cn/api/account，见 auth.account_base）。
    #
    # 必须是空串，不能写死官方地址：DEFAULTS 里的值会被当成「配置里有值」，
    #   auth.account_base() 就会压住环境变量 ASTROSWARM_ACCOUNT_BASE 和 systemd 的
    #   Environment=。留空才能让「配置 > 环境变量 > 官方默认」这条优先级成立。
    "account_base": "",
    # 档位表（plans.json）位置：留空 = 用包内自带的 astroswarm_linux/plans.json。
    # 自建账号服务时指向服务端那份档位定义文件，两侧的「全解锁」口径就一致。
    # 故意不放进 SAFE_KEYS：这是运维在配置文件/环境变量里设的，不给控制台 API 改。
    "plans_file": "",
    "account_email": "",
    "account_token": "",
    "plan": "none",
    "plan_expires_at": 0,
    "owned_plugins": [],
    "entitlement_sig": "",
    "entitlement_machine": "",
}

SAFE_KEYS = {
    "port": int,
    "bot_port": int,
    "qq_app_id": str,
    "qq_app_secret": str,
    "qq_app_token": str,
    "qq_channel": str,
    "qq_onebot_mode": str,
    "qq_onebot_host": str,
    "qq_onebot_port": int,
    "qq_onebot_path": str,
    "qq_onebot_token": str,
    "qq_onebot_listen_host": str,
    "ai_provider": str,
    "ai_api_key": str,
    "ai_base_url": str,
    "ai_model": str,
    # 智能体档案：不在白名单里时控制台改了 owner QQ / 群号会被静默丢弃，
    # 表现就是「机器人收到消息却一声不吭」。
    "agent_profile_enabled": bool,
    "agent_profile_id": str,
    "agent_owner_qq": str,
    "agent_groups": str,
    "agent_address_words": str,
    "agent_persona_mode": str,
    "ai_platforms": dict,
    "vision_api_url": str,
    "vision_api_key": str,
    "vision_model": str,
    "agent_wake_words": str,
    "agent_wake_auto": bool,
    "local_persona_id": str,
    "account_base": str,
}


def config_path() -> Path:
    return platform_info.config_home() / "config.json"


def last_good_path() -> Path:
    return config_path().with_name(config_path().name + ".bak")


def _salvage(raw: str) -> dict:
    """从坏配置文本里逐字段抢救：对每个默认键找最后一个 `"键": <值>` 再 raw_decode。

    为什么要抢救：文件被截断/写到一半时前半段往往还是完好的，整份丢成默认值等于把
    用户登录态（account_token）一起删了 —— 而那是重新进控制台的**唯一凭据**，
    丢了就只能上服务器手改文件（见 load()）。类型对不上默认值的字段一律不要。
    """
    out = {}
    if not raw:
        return out
    decoder = json.JSONDecoder()
    for key, default in DEFAULTS.items():
        marker = '"%s"' % key
        idx = raw.rfind(marker)
        if idx < 0:
            continue
        pos = idx + len(marker)
        while pos < len(raw) and raw[pos] in " \t\r\n":
            pos += 1
        if pos >= len(raw) or raw[pos] != ":":
            continue
        pos += 1
        while pos < len(raw) and raw[pos] in " \t\r\n":
            pos += 1
        try:
            value, _ = decoder.raw_decode(raw, pos)
        except Exception:  # noqa: BLE001 —— 这个字段也坏了，跳过继续救下一个
            continue
        if isinstance(default, bool) and not isinstance(value, bool):
            continue
        if isinstance(default, int) and not isinstance(default, bool) and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            continue
        if isinstance(default, str) and not isinstance(value, str):
            continue
        if isinstance(default, (list, dict)) and not isinstance(value, type(default)):
            continue
        out[key] = value
    return out


def load() -> dict:
    """读配置；解析失败时**不再静默吞掉**。

    except 后直接返回默认值是不行的：紧接着一次 save() 就会把默认值写回文件，
    用户的登录态 / 会员 / 已购插件会无声消失。
    所以坏文件另存一份 .corrupt.<时间>，指出上一份好配置（.bak）在哪，写 error 日志，
    并在返回值里带上 _config_error（save() 不会把下划线字段写回文件）。
    """
    data = dict(DEFAULTS)
    path = config_path()
    if not path.exists():
        return data
    raw = ""
    try:
        raw = path.read_text(encoding="utf-8")
        loaded = json.loads(raw)
        if not isinstance(loaded, dict):
            raise ValueError("config.json 顶层不是 JSON 对象")
        data.update(loaded)
        return data
    except Exception as exc:  # noqa: BLE001
        bak = path.with_name(path.name + ".corrupt." + time.strftime("%Y%m%d-%H%M%S"))
        try:
            shutil.copy(path, bak)
            bak_txt = str(bak)
        except Exception:  # noqa: BLE001
            bak_txt = ""
        good = last_good_path()
        good_ok = False
        if good.exists():
            try:
                good_ok = isinstance(json.loads(good.read_text(encoding="utf-8")), dict)
            except Exception:  # noqa: BLE001
                good_ok = False
        # 抢救坏文件里还能读出来的字段：整份退回默认值会让 account_token 变空，
        # 控制台连原来正确的 token 也 401。
        rescued = _salvage(raw)
        data.update(rescued)
        logging.getLogger("astroswarm").error(
            "config.json 解析失败（%s）；坏文件已备份到 %s。已从坏文件里抢救回 %d 个字段%s；"
            "上一份好配置：%s。其余字段按默认值运行，请尽快在控制台重新保存一次配置。",
            exc, bak_txt or "<备份失败>", len(rescued),
            ("（含 account_token，登录态保住了）" if rescued.get("account_token") else ""),
            good if good_ok else "<无>",
        )
        data["_config_error"] = "%s: %s" % (type(exc).__name__, exc)
        data["_config_backup"] = bak_txt
        data["_config_last_good"] = str(good) if good_ok else ""
        data["_config_rescued"] = sorted(rescued)
        return data


def restore_last_good() -> dict:
    """把上一份好配置（config.json.bak）恢复回来；没有就返回 {ok: False}。"""
    good = last_good_path()
    path = config_path()
    if not good.exists():
        return {"ok": False, "error": "没有可回滚的备份"}
    try:
        data = json.loads(good.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("备份不是 JSON 对象")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "备份也坏了：%s" % exc}
    if path.exists():
        shutil.copy(path, path.with_name(path.name + ".broken."
                                        + time.strftime("%Y%m%d-%H%M%S")))
    save(data)
    return {"ok": True, "restored": True, "plan": data.get("plan")}


def save(cfg: dict) -> dict:
    """原子写：临时文件 + fsync + os.replace，避免半个文件把配置写坏。

    不能直接 write_text 覆盖：写到一半断电/进程被杀就是一个截断的 JSON，再 load 一次
    就成了默认值。每次覆盖前把当前这份能正常解析的配置留一份到 config.json.bak，供回滚。
    """
    merged = {
        **DEFAULTS,
        **{k: v for k, v in cfg.items() if not str(k).startswith("_")},
    }
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if isinstance(json.loads(path.read_text(encoding="utf-8")), dict):
                shutil.copy(path, last_good_path())
        except Exception:  # noqa: BLE001
            pass                     # 旧文件本来就坏，不用留
    elif not last_good_path().exists():
        # 第一次保存（新装机器）也先落一份默认值当回滚目标，否则这次写坏就没有副本可退。
        try:
            last_good_path().write_text(
                json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:  # noqa: BLE001 —— 备份写不出来不该挡住本次保存
            pass
    tmp = path.with_name(path.name + ".tmp")
    payload = json.dumps(merged, ensure_ascii=False, indent=2)
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    try:                       # 目录项也落盘，掉电才不会丢
        dfd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except Exception:  # noqa: BLE001
        pass
    return merged
