from pathlib import Path
import os

APP_NAME = "AstroSwarm"
APP_DISPLAY = "AstroSwarm 星群"
APP_VERSION = "1.2.5"

# ---- Python runtime (for the bot) ----
# 使用 embeddable 精简版：纯解压、不写注册表、不需要管理员权限，
# 避免 MSI 静默安装的各类坑（残留注册、中文路径、服务异常等）。
PYTHON_VERSION = "3.12.10"
PYTHON_EMBED_URLS = (
    "https://mirrors.huaweicloud.com/python/{v}/python-{v}-embed-amd64.zip",
    "https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip",
)
GET_PIP_URLS = (
    "https://mirrors.aliyun.com/pypi/get-pip.py",
    "https://bootstrap.pypa.io/get-pip.py",
)

# ---- 默认端口 ----
DEFAULT_NONEBOT_PORT = 12111

# ---- pip ----
PIP_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"

# 机器人 venv 里安装的基础包
BOT_PACKAGES = ("nonebot2[fastapi]", "nonebot2[httpx]", "nonebot-adapter-qq", "nonebot-plugin-localstore", "nonebot-plugin-apscheduler", "tzdata")
# 内置 AI 插件（assets/plugins/ai）的第三方依赖
AI_PLUGIN_DEPS = ("openai", "mcp", "PyJWT", "cryptography")

# ---- 目录名 ----
DIR_DOWNLOADS = "downloads"
DIR_PYTHON = "python"
DIR_BOT = "bot"
DIR_LOGS = "logs"

# 全局指针文件位置（记录根目录在哪）
# 目录名保持旧名 QBotManager：老客户安装指针/最近目录不因改名失联（2026-08-16 品牌改名）
POINTER_DIR_NAME = "QBotManager"
# QBM_POINTER_DIR 仅供测试隔离：测试进程用它把指针写到临时目录，
# 避免测试中的 Settings.save() 污染真实安装指针（曾导致预览版指向临时测试根）。
POINTER_DIR = Path(os.environ.get(
    "QBM_POINTER_DIR",
    str(Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / POINTER_DIR_NAME),
))
POINTER_FILE = POINTER_DIR / "settings.json"
