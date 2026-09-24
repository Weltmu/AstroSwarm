# -*- coding: utf-8 -*-
"""在机器人 venv 里验证 AI 插件可完整加载（NoneBot 初始化后 import ai）。"""
import os
import sys
from pathlib import Path

PLUGINS = Path(r"D:\ai\QBotManager\src\qbotmanager\assets\plugins")
os.chdir(PLUGINS.parent)
sys.path.insert(0, ".")

import nonebot  # noqa: E402

nonebot.init()

nonebot.load_plugins("plugins")
print("AI plugin load OK")
