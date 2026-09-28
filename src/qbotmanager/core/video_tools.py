# -*- coding: utf-8 -*-
"""背景视频工具：默认背景查找。

视频档位/转码/缓存体系已于 2026-08-18 移除：程序直接播放用户原视频，
不再生成分档缓存（imageio-ffmpeg 依赖一并移除）。
"""
import os
import sys
from pathlib import Path

OFFLINE_DIR_NAME = "离线包"
DEFAULT_BG_DIR_NAME = "默认背景"


def find_default_background(settings) -> Path | None:
    """按优先级查找背景视频：
    1) settings.bg_video_path（显式指定）
    2) exe 旁 / 仓库 release 的 离线包/默认背景/*.mp4
    3) 安装根目录 背景/*.mp4
    """
    if settings.bg_video_path:
        p = Path(settings.bg_video_path)
        if p.exists() and p.is_file():
            return p

    candidates = []
    try:
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir / OFFLINE_DIR_NAME / DEFAULT_BG_DIR_NAME)
        candidates.append(exe_dir.parent / "release" / OFFLINE_DIR_NAME / DEFAULT_BG_DIR_NAME)
    except Exception:  # noqa: BLE001
        pass
    candidates.append(Path(__file__).resolve().parents[3] / "release" / OFFLINE_DIR_NAME / DEFAULT_BG_DIR_NAME)
    candidates.append(Path(os.getcwd()) / "release" / OFFLINE_DIR_NAME / DEFAULT_BG_DIR_NAME)
    candidates.append(settings.root / "背景")

    for c in candidates:
        try:
            if not c.is_dir():
                continue
            for p in sorted(c.glob("*.mp4")) + sorted(c.glob("*.mkv")) + sorted(c.glob("*.mov")):
                if p.stat().st_size > 1024 * 1024:
                    return p
        except OSError:
            continue
    return None
