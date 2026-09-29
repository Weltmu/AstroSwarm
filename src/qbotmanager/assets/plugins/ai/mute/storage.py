"""持久化存储模块"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from nonebot.log import logger

import nonebot_plugin_localstore as store


def _beijing_tz():
    """时区对象：系统 tzdata 缺失时回退固定 UTC+8（干净 Windows 上 ZoneInfo 会抛异常）。"""
    try:
        return ZoneInfo("Asia/Shanghai")
    except Exception:  # noqa: BLE001
        from datetime import timedelta, timezone

        return timezone(timedelta(hours=8))


BEIJING_TZ = _beijing_tz()


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    """将时间序列化为 ISO 字符串"""
    return value.isoformat() if value else None


def _deserialize_datetime(value: Any) -> Optional[datetime]:
    """将 ISO 字符串反序列化为时间对象"""
    if not value or not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=BEIJING_TZ)
        return parsed.astimezone(BEIJING_TZ)
    except (TypeError, ValueError):
        return None


class MuteStorage:
    """禁言数据持久化管理器"""

    def __init__(self) -> None:
        self._at_file = store.get_plugin_data_file("at_overrides.json")
        self._states_file = store.get_plugin_data_file("group_states.json")

    def load_at_overrides(self) -> dict[int, bool]:
        """读取群级别的 @ 开关覆盖配置"""
        try:
            if not self._at_file.exists():
                return {}

            raw = json.loads(self._at_file.read_text(encoding="utf-8"))
            return {int(key): bool(value) for key, value in raw.items()}
        except Exception as exception:
            logger.opt(exception=exception).error("加载 @ 开关数据失败")
            return {}

    def save_at_overrides(self, data: dict[int, bool]) -> None:
        """保存群级别的 @ 开关覆盖配置"""
        try:
            serializable = {str(key): value for key, value in data.items()}
            self._at_file.write_text(
                json.dumps(serializable, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exception:
            logger.opt(exception=exception).error("保存 @ 开关数据失败")

    def load_states(self) -> dict[int, dict[str, Any]]:
        """读取群状态、定时任务和长期禁言计划"""
        try:
            if not self._states_file.exists():
                return {}

            raw = json.loads(self._states_file.read_text(encoding="utf-8"))
            return self._deserialize_states(raw)
        except Exception as exception:
            logger.opt(exception=exception).error("加载群状态失败")
            return {}

    def save_states(self, data: dict[int, dict[str, Any]]) -> None:
        """保存群状态、定时任务和长期禁言计划"""
        try:
            serializable = self._serialize_states(data)
            self._states_file.write_text(
                json.dumps(serializable, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exception:
            logger.opt(exception=exception).error("保存群状态失败")

    @staticmethod
    def _serialize_states(data: dict[int, dict[str, Any]]) -> dict[str, Any]:
        """将群状态转换为 JSON 可写入结构"""
        result: dict[str, Any] = {}

        for group_id, state in data.items():
            whole_mute = state.get("whole_mute", {})
            individual_mutes = state.get("individual_mutes", {})
            tasks = state.get("tasks", {})
            plans = state.get("plans", {})

            result[str(group_id)] = {
                "whole_mute": {
                    "enabled": bool(whole_mute.get("enabled", False)),
                    "end_time": _serialize_datetime(whole_mute.get("end_time")),
                    "duration": whole_mute.get("duration"),
                },
                "individual_mutes": {
                    str(user_id): {
                        "end_time": _serialize_datetime(info.get("end_time")),
                        "duration": info.get("duration"),
                        "plan_id": info.get("plan_id"),
                    }
                    for user_id, info in individual_mutes.items()
                },
                "tasks": {
                    task_id: {
                        "type": info.get("type"),
                        "bot_id": info.get("bot_id"),
                        "user_id": info.get("user_id"),
                        "execute_time": _serialize_datetime(info.get("execute_time")),
                        "end_time": _serialize_datetime(info.get("end_time")),
                        "duration": info.get("duration"),
                        "start_minutes": info.get("start_minutes"),
                        "plan_id": info.get("plan_id"),
                        "created_at": _serialize_datetime(info.get("created_at")),
                    }
                    for task_id, info in tasks.items()
                },
                "plans": {
                    plan_id: {
                        "bot_id": info.get("bot_id"),
                        "user_id": info.get("user_id"),
                        "end_time": _serialize_datetime(info.get("end_time")),
                        "next_execute_time": _serialize_datetime(
                            info.get("next_execute_time")
                        ),
                        "segment_end_time": _serialize_datetime(
                            info.get("segment_end_time")
                        ),
                        "created_at": _serialize_datetime(info.get("created_at")),
                        "last_execute_time": _serialize_datetime(
                            info.get("last_execute_time")
                        ),
                    }
                    for plan_id, info in plans.items()
                },
            }

        return result

    @staticmethod
    def _deserialize_states(raw: dict[str, Any]) -> dict[int, dict[str, Any]]:
        """将 JSON 结构恢复为运行时使用的群状态"""
        result: dict[int, dict[str, Any]] = {}

        for group_id_text, state in raw.items():
            whole_mute_raw = state.get("whole_mute", {})
            individual_raw = state.get("individual_mutes", {})
            tasks_raw = state.get("tasks", {})
            plans_raw = state.get("plans", {})

            individual_mutes: dict[int, dict[str, Any]] = {}
            for user_id_text, info in individual_raw.items():
                individual_mutes[int(user_id_text)] = {
                    "end_time": _deserialize_datetime(info.get("end_time")),
                    "duration": info.get("duration", 0),
                    "plan_id": info.get("plan_id"),
                }

            tasks: dict[str, dict[str, Any]] = {}
            for task_id, info in tasks_raw.items():
                tasks[task_id] = {
                    "type": info.get("type"),
                    "bot_id": info.get("bot_id"),
                    "user_id": info.get("user_id"),
                    "execute_time": _deserialize_datetime(info.get("execute_time")),
                    "end_time": _deserialize_datetime(info.get("end_time")),
                    "duration": info.get("duration"),
                    "start_minutes": info.get("start_minutes"),
                    "plan_id": info.get("plan_id"),
                    "created_at": _deserialize_datetime(info.get("created_at")),
                }

            plans: dict[str, dict[str, Any]] = {}
            for plan_id, info in plans_raw.items():
                plans[plan_id] = {
                    "bot_id": info.get("bot_id"),
                    "user_id": info.get("user_id"),
                    "end_time": _deserialize_datetime(info.get("end_time")),
                    "next_execute_time": _deserialize_datetime(
                        info.get("next_execute_time")
                    ),
                    "segment_end_time": _deserialize_datetime(
                        info.get("segment_end_time")
                    ),
                    "created_at": _deserialize_datetime(info.get("created_at")),
                    "last_execute_time": _deserialize_datetime(
                        info.get("last_execute_time")
                    ),
                }

            result[int(group_id_text)] = {
                "whole_mute": {
                    "enabled": bool(whole_mute_raw.get("enabled", False)),
                    "end_time": _deserialize_datetime(whole_mute_raw.get("end_time")),
                    "duration": whole_mute_raw.get("duration"),
                },
                "individual_mutes": individual_mutes,
                "tasks": tasks,
                "plans": plans,
            }

        return result
