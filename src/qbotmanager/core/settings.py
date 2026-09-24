import os
import json
import logging
import secrets
import shutil
import uuid
import tempfile
from pathlib import Path

from ..constants import (
    DEFAULT_NONEBOT_PORT,
    DIR_BOT, DIR_DOWNLOADS, DIR_LOGS, DIR_PYTHON,
    PIP_INDEX, POINTER_DIR, POINTER_FILE,
    PYTHON_VERSION,
)
from .agent_profile import DEFAULT_PROFILE_ID

RECENT_FILE = POINTER_DIR / "recent_roots.json"
logger = logging.getLogger("qbotmanager")


class Settings:
    """管理器配置。所有数据保存在用户选择的根目录下的 settings.json。"""

    # 坏配置抢救时留下的标记（正常加载时为空；UI 据此提示用户）
    config_error = ""
    config_backup = ""
    config_last_good = ""
    config_rescued: tuple = ()

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.python_version: str = PYTHON_VERSION
        self._python_exe: str = ""            # 实际使用的 Python 路径（空 = 自动探测）
        self.python_source: str = ""          # system / venv / embedded / ""
        self.pip_index: str = PIP_INDEX
        self.nonebot_port: int = DEFAULT_NONEBOT_PORT
        self.ws_token: str = secrets.token_hex(16)
        self.superusers: list = []
        self.deployed: dict = {}              # 各步骤完成标记
        self.account_qq: str = ""             # 已登录的 QQ 号（字符串）
        self.qq_channel: str = "onebot"       # QQ 通道：onebot（第三方 OneBot 协议，默认）；official 已下线仅兼容
        self.qq_official_appid: str = ""      # 官方机器人 AppID
        self.qq_official_token: str = ""      # 官方机器人 Token
        self.qq_official_secret: str = ""     # 官方机器人 AppSecret
        self.qq_official_sandbox: bool = False  # 官方机器人沙箱模式
        # ---- 第三方 OneBot 协议端（不内置、不分发，用户自行安装）----
        self.qq_onebot_host: str = "127.0.0.1"      # 协议端地址
        self.qq_onebot_port: int = 3001             # 协议端正向 WS 端口
        self.qq_onebot_path: str = "/onebot/v11/ws" # 正向 WS 路径
        self.qq_onebot_token: str = ""              # 访问令牌（可空）
        self.qq_onebot_mode: str = "reverse"        # 连接方式：reverse（反向 WS，协议端来连，默认）/ forward（正向 WS）
        self.qq_onebot_listen_host: str = "127.0.0.1"  # 反向模式监听地址（协议端在其他设备/容器时填 0.0.0.0）
        # ---- dsh（DeepSeek Harness）QQ 群聊 AI 通道 ----
        self.dsh_enabled: bool = False        # dsh 通道总开关（启用后 QQ 由 dsh 接管）
        self.dsh_require_mention: bool = True  # 群聊必须 @ 机器人才触发
        self.dsh_model: str = ""              # 模型覆盖（空 = 跟随 AI 大脑）
        self.dsh_provider: str = ""           # provider 覆盖（空 = deepseek-official）
        self.dsh_api_key: str = ""            # API Key 覆盖（空 = 跟随 AI 大脑）
        self.dsh_node_exe: str = ""           # Node.js 路径（空 = 自动探测 PATH）
        # ---- 外观与背景视频 ----
        self.bg_video_enabled: bool = True    # 是否启用动态背景
        self.bg_video_path: str = ""          # 背景视频路径（空 = 自动查找默认背景）
        self.bg_video_autoplay: bool = True
        self.bg_video_loop: bool = True
        self.bg_mask_strength: float = 0.68   # 0.4 ~ 0.9 遮罩强度
        self.bg_brightness: int = 0           # 视频亮度 -100 ~ 100
        self.animations_enabled: bool = True  # 是否启用界面动效
        self.bg_image_enabled: bool = False   # 图片背景开关（优先于视频）
        self.bg_image_path: str = ""          # 图片背景路径
        self.theme: str = "glass"             # UI 主题：glass（极光玻璃）/ swiss（瑞士极简）
        self.accent: str = "default"          # 极光玻璃的强调色（THEMES 键）
        self.glass_effect: str = "default"    # UI 框质感：default/liquid/frosted
        self.ui_opacity: int = 70             # UI 框透明度（%）
        self.ui_color: str = "#FFFFFF"        # UI 框颜色（瑞士极简卡片底色，默认白）
        self.ai_enabled: bool = True          # 内置 AI 插件总开关（启动机器人时注入 AI_DISABLED）
        self.nonebot_enabled: bool = True     # NoneBot 总开关
        self.ai_platforms: dict = {           # AI 大脑在各平台的启用开关（默认全开）
            "qq": True,
            "wechat": True,
            "feishu": True,
            "telegram": True,
        }
        self.auto_start_services: bool = False   # 启动程序时自动启动全部服务
        self.auto_launch_on_boot: bool = False   # 开机自动启动程序
        self.developer_mode: bool = False        # 开发者模式（恢复第三方插件安装，后果自负）
        self.beginner_mode: bool = True          # 小白模式（默认只显示常用功能）
        # ---- 智能体档案（李清菡等可选 AI 预设） ----
        self.agent_profile_enabled: bool = False   # 智能体档案总开关（默认关）
        self.agent_profile_id: str = DEFAULT_PROFILE_ID
        self.agent_wake_words: list = []          # 唤醒词（空 = 档案默认）
        self.agent_wake_auto: bool = True         # 人格变化时自动重新生成
        self.agent_owner_openid: str = ""         # “你同学”官方 openid（留空 = 专属命令降级）
        self.local_persona_id: str = ""           # 本地人设工坊当前启用的人设 id（空 = 未启用）
        # ---- 视觉模型（图片描述/生成，用户自填 key） ----
        self.vision_api_url: str = "https://api.siliconflow.cn/v1"
        self.vision_api_key: str = ""
        self.vision_model: str = "Qwen/Qwen3-Omni-30B-A3B-Instruct"

    # ---------- 路径 ----------
    @property
    def downloads_dir(self) -> Path:
        return self.root / DIR_DOWNLOADS

    @property
    def python_dir(self) -> Path:
        return self.root / DIR_PYTHON

    @property
    def python_exe(self) -> Path:
        """当前 Python 运行时路径；未指定时回退到内置目录。"""
        if self._python_exe:
            return Path(self._python_exe)
        return self.python_dir / "python.exe"

    @python_exe.setter
    def python_exe(self, value):
        self._python_exe = str(value) if value else ""

    @property
    def bot_dir(self) -> Path:
        return self.root / DIR_BOT

    @property
    def logs_dir(self) -> Path:
        return self.root / DIR_LOGS

    @property
    def venv_python(self) -> Path:
        return self.bot_dir / ".venv" / "Scripts" / "python.exe"

    @property
    def plugins_dir(self) -> Path:
        return self.bot_dir / "src" / "plugins"

    @property
    def bot_env_file(self) -> Path:
        return self.bot_dir / ".env"

    @property
    def settings_file(self) -> Path:
        return self.root / "settings.json"

    def ensure_dirs(self):
        for d in (self.root, self.downloads_dir, self.python_dir,
                  self.bot_dir, self.logs_dir, self.plugins_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---------- 部署状态 ----------
    @property
    def required_deploy_steps(self) -> tuple:
        return ("python", "deps", "bot")

    def is_deployed(self) -> bool:
        """全部关键步骤完成后才算部署完成；防止“半部署”状态下跳过向导。"""
        return all(bool(self.deployed.get(k)) for k in self.required_deploy_steps)

    # ---------- 持久化 ----------
    def to_dict(self) -> dict:
        return {
            "root": str(self.root),
            "python_version": self.python_version,
            "python_exe": self._python_exe,
            "python_source": self.python_source,
            "pip_index": self.pip_index,
            "nonebot_port": self.nonebot_port,
            "ws_token": self.ws_token,
            "superusers": self.superusers,
            "deployed": self.deployed,
            "account_qq": self.account_qq,
            "qq_channel": self.qq_channel,
            "qq_official_appid": self.qq_official_appid,
            "qq_official_token": self.qq_official_token,
            "qq_official_secret": self.qq_official_secret,
            "qq_official_sandbox": self.qq_official_sandbox,
            "qq_onebot_host": self.qq_onebot_host,
            "qq_onebot_port": self.qq_onebot_port,
            "qq_onebot_path": self.qq_onebot_path,
            "qq_onebot_token": self.qq_onebot_token,
            "qq_onebot_mode": self.qq_onebot_mode,
            "qq_onebot_listen_host": self.qq_onebot_listen_host,
            "dsh_enabled": self.dsh_enabled,
            "dsh_require_mention": self.dsh_require_mention,
            "dsh_model": self.dsh_model,
            "dsh_provider": self.dsh_provider,
            "dsh_api_key": self.dsh_api_key,
            "dsh_node_exe": self.dsh_node_exe,
            "bg_video_enabled": self.bg_video_enabled,
            "bg_video_path": self.bg_video_path,
            "bg_video_autoplay": self.bg_video_autoplay,
            "bg_video_loop": self.bg_video_loop,
            "bg_mask_strength": self.bg_mask_strength,
            "bg_brightness": self.bg_brightness,
            "animations_enabled": self.animations_enabled,
            "bg_image_enabled": self.bg_image_enabled,
            "bg_image_path": self.bg_image_path,
            "theme": self.theme,
            "accent": self.accent,
            "glass_effect": self.glass_effect,
            "ui_opacity": self.ui_opacity,
            "ui_color": self.ui_color,
            "ai_enabled": self.ai_enabled,
            "nonebot_enabled": self.nonebot_enabled,
            "ai_platforms": self.ai_platforms,
            "auto_start_services": self.auto_start_services,
            "auto_launch_on_boot": self.auto_launch_on_boot,
            "developer_mode": self.developer_mode,
            "beginner_mode": self.beginner_mode,
            "agent_profile_enabled": self.agent_profile_enabled,
            "agent_profile_id": self.agent_profile_id,
            "agent_wake_words": self.agent_wake_words,
            "agent_wake_auto": self.agent_wake_auto,
            "agent_owner_openid": self.agent_owner_openid,
            "local_persona_id": self.local_persona_id,
            "vision_api_url": self.vision_api_url,
            "vision_api_key": self.vision_api_key,
            "vision_model": self.vision_model,
        }

    def save(self):
        """原子写配置：唯一临时名 + fsync + os.replace，并留一份 .bak 供回滚。

        固定临时文件名在并发保存时会写到同一个 fd；直接覆盖则写到一半断电就成了
        截断的 JSON，再读一次就退成默认值（端口/token/API Key 全丢）。
        """
        self.ensure_dirs()
        path = self.settings_file
        bak = self._last_good_file()
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        if path.exists():
            try:
                if isinstance(json.loads(path.read_text(encoding="utf-8")), dict):
                    shutil.copy(path, bak)
            except (ValueError, OSError):
                pass          # 旧文件本来就坏，不值得留
        elif not bak.exists():
            try:          # 第一次保存也先落一份默认值当回滚目标
                bak.write_text(payload, encoding="utf-8")
            except OSError:
                pass
        tmp = path.with_name("%s.%d.%s.tmp" % (path.name, os.getpid(), uuid.uuid4().hex[:8]))
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        try:                  # 目录项也落盘，掉电才不会丢
            dfd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except Exception:     # noqa: BLE001 —— Windows 打不开目录，忽略
            pass
        try:
            POINTER_DIR.mkdir(parents=True, exist_ok=True)
            POINTER_FILE.write_text(json.dumps({"root": str(self.root)}), encoding="utf-8")
            self._remember_root()
        except OSError:
            logger.warning("写入安装根指针失败")

    def _remember_root(self):
        """把安装根目录记入最近列表，指针丢失时 find_root 可自动找回。"""
        try:
            root_path = Path(self.root).resolve()
            tmp_path = Path(tempfile.gettempdir()).resolve()
            if root_path.is_relative_to(tmp_path):
                # 系统临时目录下的根不记入最近列表：
                # 测试/调试残留一旦写入，find_root 兜底会带回假安装根
                return
        except OSError:
            pass
        try:
            roots = []
            if RECENT_FILE.exists():
                try:
                    roots = json.loads(RECENT_FILE.read_text(encoding="utf-8"))
                    if not isinstance(roots, list):
                        roots = []
                except (ValueError, OSError):
                    roots = []
            key = str(self.root)
            if key in roots:
                roots.remove(key)
            roots.insert(0, key)
            RECENT_FILE.write_text(json.dumps(roots[:5], ensure_ascii=False), encoding="utf-8")
        except OSError:
            logger.warning("记录最近安装目录失败")

    @classmethod
    def load(cls, root: str | Path) -> "Settings":
        s = cls(root)
        p = s.settings_file
        if p.exists():
            raw = ""
            try:
                raw = p.read_text(encoding="utf-8")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("settings.json 顶层不是 JSON 对象")
            except (ValueError, OSError) as e:
                data = s._recover_settings(p, raw, e)
            s._apply(data)
            if data.get("_config_error"):
                s.config_error = str(data.get("_config_error") or "")
                s.config_backup = str(data.get("_config_backup") or "")
                s.config_last_good = str(data.get("_config_last_good") or "")
                s.config_rescued = tuple(data.get("_config_rescued") or ())
        return s

    def _apply(self, data: dict) -> None:
        """把配置字典套到本对象上（字段级容错：单个字段坏了只影响它自己）。"""

        self.python_version = data.get("python_version", self.python_version)
        self._python_exe = data.get("python_exe", self._python_exe) or ""
        self.python_source = data.get("python_source", self.python_source) or ""
        self.pip_index = data.get("pip_index", self.pip_index)
        try:
            self.nonebot_port = int(data.get("nonebot_port", self.nonebot_port))
        except (TypeError, ValueError):
            # 单个字段损坏不应拖垮整个配置（否则后面的凭证/外观全部丢失）
            self.nonebot_port = DEFAULT_NONEBOT_PORT
        self.ws_token = data.get("ws_token", self.ws_token)
        self.superusers = data.get("superusers", self.superusers) or []
        self.deployed = data.get("deployed", self.deployed) or {}
        self.account_qq = data.get("account_qq", self.account_qq)
        self.qq_channel = data.get("qq_channel", self.qq_channel) or "onebot"
        if self.qq_channel not in ("official", "onebot"):
            self.qq_channel = "onebot"
        self.qq_official_appid = data.get("qq_official_appid", self.qq_official_appid) or ""
        self.qq_official_token = data.get("qq_official_token", self.qq_official_token) or ""
        self.qq_official_secret = data.get("qq_official_secret", self.qq_official_secret) or ""
        self.qq_official_sandbox = bool(data.get("qq_official_sandbox", self.qq_official_sandbox))
        self.qq_onebot_host = data.get("qq_onebot_host", self.qq_onebot_host) or "127.0.0.1"
        try:
            self.qq_onebot_port = int(data.get("qq_onebot_port", self.qq_onebot_port))
        except (TypeError, ValueError):
            self.qq_onebot_port = 3001
        self.qq_onebot_path = data.get("qq_onebot_path", self.qq_onebot_path) or "/onebot/v11/ws"
        self.qq_onebot_token = data.get("qq_onebot_token", self.qq_onebot_token) or ""
        self.qq_onebot_mode = str(
            data.get("qq_onebot_mode", self.qq_onebot_mode) or "reverse"
        ).lower()
        if self.qq_onebot_mode not in ("reverse", "forward"):
            self.qq_onebot_mode = "reverse"
        self.qq_onebot_listen_host = (
            str(data.get("qq_onebot_listen_host", self.qq_onebot_listen_host) or "")
            .strip() or "127.0.0.1"
        )
        self.dsh_enabled = bool(data.get("dsh_enabled", self.dsh_enabled))
        self.dsh_require_mention = bool(data.get("dsh_require_mention", self.dsh_require_mention))
        self.dsh_model = data.get("dsh_model", self.dsh_model) or ""
        self.dsh_provider = data.get("dsh_provider", self.dsh_provider) or ""
        self.dsh_api_key = data.get("dsh_api_key", self.dsh_api_key) or ""
        self.dsh_node_exe = data.get("dsh_node_exe", self.dsh_node_exe) or ""
        self.bg_video_enabled = bool(data.get("bg_video_enabled", self.bg_video_enabled))
        self.bg_video_path = data.get("bg_video_path", self.bg_video_path) or ""
        self.bg_video_autoplay = bool(data.get("bg_video_autoplay", self.bg_video_autoplay))
        self.bg_video_loop = bool(data.get("bg_video_loop", self.bg_video_loop))
        try:
            self.bg_mask_strength = float(data.get("bg_mask_strength", self.bg_mask_strength))
            self.bg_mask_strength = max(0.3, min(0.95, self.bg_mask_strength))
        except (TypeError, ValueError):
            self.bg_mask_strength = 0.68
        try:
            self.bg_brightness = max(-100, min(100, int(data.get("bg_brightness", self.bg_brightness))))
        except (TypeError, ValueError):
            self.bg_brightness = 0
        self.animations_enabled = bool(data.get("animations_enabled", self.animations_enabled))
        self.bg_image_enabled = bool(data.get("bg_image_enabled", self.bg_image_enabled))
        self.bg_image_path = data.get("bg_image_path", self.bg_image_path) or ""
        self.theme = data.get("theme", self.theme) or "glass"
        self.accent = str(data.get("accent", self.accent) or "default")
        self.glass_effect = data.get("glass_effect", self.glass_effect) or "default"
        try:
            self.ui_opacity = max(10, min(95, int(data.get("ui_opacity", self.ui_opacity))))
        except (TypeError, ValueError):
            self.ui_opacity = 70
        self.ui_color = str(data.get("ui_color", self.ui_color) or "#FFFFFF").strip() or "#FFFFFF"
        self.ai_enabled = bool(data.get("ai_enabled", self.ai_enabled))
        self.nonebot_enabled = bool(data.get("nonebot_enabled", self.nonebot_enabled))
        self.auto_start_services = bool(data.get("auto_start_services", self.auto_start_services))
        self.auto_launch_on_boot = bool(data.get("auto_launch_on_boot", self.auto_launch_on_boot))
        self.developer_mode = bool(data.get("developer_mode", self.developer_mode))
        self.beginner_mode = bool(data.get("beginner_mode", self.beginner_mode))
        self.agent_profile_enabled = bool(data.get("agent_profile_enabled", self.agent_profile_enabled))
        self.agent_profile_id = str(data.get("agent_profile_id", self.agent_profile_id)
                                 or DEFAULT_PROFILE_ID)
        self.agent_owner_openid = str(data.get("agent_owner_openid", self.agent_owner_openid)
                                   or "").strip()
        raw_wake = data.get("agent_wake_words")
        if isinstance(raw_wake, list):
            self.agent_wake_words = [
                str(x).strip() for x in raw_wake if str(x).strip()]
        else:
            self.agent_wake_words = list(self.agent_wake_words)
        self.agent_wake_auto = bool(data.get("agent_wake_auto", self.agent_wake_auto))
        self.local_persona_id = str(
            data.get("local_persona_id", self.local_persona_id) or "")
        self.vision_api_url = str(data.get("vision_api_url", self.vision_api_url) or "").strip()
        self.vision_api_key = str(data.get("vision_api_key", self.vision_api_key) or "").strip()
        self.vision_model = str(data.get("vision_model", self.vision_model) or "").strip()
        raw_platforms = data.get("ai_platforms")
        if isinstance(raw_platforms, dict):
            defaults = dict(self.ai_platforms)
            defaults.update({
                k: bool(v) for k, v in raw_platforms.items()
                if k in defaults
            })
            self.ai_platforms = defaults
        else:
            self.ai_platforms = dict(self.ai_platforms)

    # ---- 坏配置抢救：坏文件另存 .corrupt.<时间>，逐字段救回，再用 .bak 兜底 ----
    def _last_good_file(self):
        return self.settings_file.with_name(self.settings_file.name + ".bak")

    @staticmethod
    def _salvage(raw: str, defaults: dict) -> dict:
        """从坏配置文本里逐字段抢救：为每个已知键找最后一个 `"键": <值>` 再 raw_decode。

        文件被截断/写到一半时前半段往往还是好的，整份丢成默认值等于把 QQ 端口、
        OneBot token、AI Key 一起删了。类型对不上默认值的字段一律不要。
        """
        out = {}
        if not raw:
            return out
        decoder = json.JSONDecoder()
        for key, default in defaults.items():
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
            except Exception:  # noqa: BLE001 —— 这个字段也坏了，跳过救下一个
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

    def _recover_settings(self, path, raw: str, exc: Exception) -> dict:
        """解析失败时的兜底：坏文件留证 + 逐字段抢救 + 上一份好配置兜底。

        绝不静默退成默认值：紧接着一次 save() 就会把默认值写回文件，
        用户的端口/token/API Key/外观会无声消失。
        """
        import time as _time

        data = self.to_dict()
        bak = self._last_good_file()
        bad_copy = ""
        try:
            target = path.with_name(path.name + ".corrupt." +
                                     _time.strftime("%Y%m%d-%H%M%S"))
            shutil.copy(path, target)
            bad_copy = str(target)
        except OSError:
            pass
        good_ok = False
        if bak.exists():
            try:
                saved = json.loads(bak.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    data.update({k: v for k, v in saved.items() if k in data})
                    good_ok = True
            except (ValueError, OSError):
                good_ok = False
        rescued = self._salvage(raw, self.to_dict())
        data.update(rescued)
        data["_config_error"] = "%s: %s" % (type(exc).__name__, exc)
        data["_config_backup"] = bad_copy
        data["_config_last_good"] = str(bak) if good_ok else ""
        data["_config_rescued"] = sorted(rescued)
        logger.error(
            "settings.json 解析失败（%s）；坏文件已备份到 %s；从坏文件里抢救回 %d 个字段%s；"
            "上一份好配置：%s。请尽快在「设置」里保存一次配置。",
            exc, bad_copy or "<备份失败>", len(rescued),
            ("（含 QQ/OneBot token 或 AI Key，凭证保住了）"
             if any(k.endswith("token") or k.endswith("key") or k.endswith("api_key")
                    for k in rescued) else ""),
            str(bak) if good_ok else "<无>",
        )
        return data

    def restore_last_good(self) -> dict:
        """把上一份好配置（settings.json.bak）恢复回来；没有就返回 {ok: False}。"""
        import time as _time

        bak = self._last_good_file()
        if not bak.exists():
            return {"ok": False, "error": "没有可回滚的备份"}
        try:
            data = json.loads(bak.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("备份不是 JSON 对象")
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": "备份也坏了：%s" % exc}
        if self.settings_file.exists():
            try:
                shutil.copy(self.settings_file, self.settings_file.with_name(
                    self.settings_file.name + ".broken." + _time.strftime("%Y%m%d-%H%M%S")))
            except OSError:
                pass
        self._apply(data)
        self.save()
        return {"ok": True, "restored": True}



    @classmethod
    def find_root(cls) -> Path | None:
        if POINTER_FILE.exists():
            try:
                data = json.loads(POINTER_FILE.read_text(encoding="utf-8"))
                root = Path(data.get("root", "")).expanduser()
                if cls._plausible_root(root):
                    return root
            except (ValueError, OSError) as e:
                logger.warning("读取安装根指针失败: %s", e)
        # 兜底：指针丢失时从最近安装目录列表找回
        if RECENT_FILE.exists():
            try:
                for item in json.loads(RECENT_FILE.read_text(encoding="utf-8")):
                    root = Path(str(item)).expanduser()
                    if cls._plausible_root(root):
                        return root
            except (ValueError, OSError) as e:
                logger.warning("从最近目录找回安装根失败: %s", e)
        return None

    @staticmethod
    def _plausible_root(root: Path) -> bool:
        """安装根必须存在且已部署；系统临时目录下的目录一律不认。

        防止测试/调试把 %TEMP% 下的临时部署写进指针或最近列表后，
        find_root 兜底又把程序带回到一个“假安装根”，导致日志目录、
        bot 进程等全部跑偏。
        """
        if not (root.is_dir() and (root / "settings.json").exists()):
            return False
        try:
            root_res = root.resolve()
            tmp_res = Path(tempfile.gettempdir()).resolve()
            if root_res.is_relative_to(tmp_res):
                return False
        except OSError:
            pass
        return True
