"""工具函数与命令解析模块"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import ceil
from typing import Literal, Optional, Set, Tuple, TypeVar
from zoneinfo import ZoneInfo

from nonebot.adapters.onebot.v11 import Message, MessageSegment


def _beijing_tz():
    """时区对象：系统 tzdata 缺失时回退固定 UTC+8（干净 Windows 上 ZoneInfo 会抛异常）。"""
    try:
        return ZoneInfo("Asia/Shanghai")
    except Exception:  # noqa: BLE001
        from datetime import timezone

        return timezone(timedelta(hours=8))


BEIJING_TZ = _beijing_tz()
MAX_SINGLE_MUTE_MINUTES = 30 * 24 * 60
LONG_MUTE_BUFFER_MINUTES = 24 * 60
STATUS_PAGE_SIZE = 5
MAX_MONTHS = 12
MAX_DAILY_DURATION_MINUTES = 24 * 60

HELP_ALIASES = {"帮助", "help", "菜单"}
USAGE_ALIASES = {"使用细则"}
STATUS_ALIASES = {"查看状态", "状态", "群状态", "禁言状态", "查看禁言状态"}
SELF_MUTE_ALIASES = {"禁我", "把我禁言", "给我禁言"}
QUESTION_PREFIXES = ("要不要", "能不能", "可不可以", "可以不可以", "行不行", "是否")
QUESTION_SUFFIXES = ("吗", "么", "呢", "?", "？")
WHOLE_TARGET_KEYWORDS = (
    "全员",
    "全体",
    "所有人",
    "全部人",
    "全群",
    "全群成员",
    "全体成员",
)
WHOLE_MUTE_PREFIXES = (
    "全员禁言",
    "全体禁言",
    "全群禁言",
    "给全员禁言",
    "给全体禁言",
    "把全员禁言",
    "把全体禁言",
    "开启全员禁言",
    "开启全体禁言",
    "开始全员禁言",
    "开始全体禁言",
    "禁言全员",
    "禁言全体",
    "始终禁言",
)
WHOLE_UNMUTE_PHRASES = {
    "解禁全员",
    "解禁全体",
    "解禁所有人",
    "取消全员",
    "取消全体",
    "取消所有人",
    "取消全员禁言",
    "取消全体禁言",
    "解除全员",
    "解除全体",
    "解除所有人",
    "解除全员禁言",
    "解除全体禁言",
    "关闭全员禁言",
    "关闭全体禁言",
    "全员解禁",
    "全体解禁",
    "所有人解禁",
    "全员解除",
    "全体解除",
    "所有人解除",
    "始终禁言取消",
    "始终禁言解除",
    "始终禁言关闭",
}
CURRENT_CANCEL_KEYWORDS = ("当前", "现在", "正在")
SCHEDULED_CANCEL_KEYWORDS = ("定时", "计划", "任务", "未来")
ALL_CANCEL_KEYWORDS = (
    "所有禁言",
    "全部禁言",
    "所有禁言状态",
    "全部禁言状态",
    "全部状态",
    "所有状态",
    "全都取消",
)
AT_TOGGLE_ENABLE_PHRASES = {
    "开启at",
    "打开at",
    "启用at",
    "开启@",
    "打开@",
    "启用@",
}
AT_TOGGLE_DISABLE_PHRASES = {
    "关闭at",
    "关掉at",
    "停用at",
    "关闭@",
    "关掉@",
    "停用@",
}
WEEKDAY_MAP = {
    "一": 0,
    "二": 1,
    "三": 2,
    "四": 3,
    "五": 4,
    "六": 5,
    "日": 6,
    "天": 6,
}
CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
UNTIL_CONNECTOR_PATTERN = r"(?:到|至|直到)"
DELAY_CONNECTOR_PATTERN = r"(?:后|之后|以后)"
DAILY_KEYWORDS = ("每天", "每日")


@dataclass(slots=True)
class TargetInfo:
    """消息中的目标信息"""

    user_ids: list[int] = field(default_factory=list)
    has_at_all: bool = False


@dataclass(slots=True)
class ParsedCommand:
    """命令解析结果"""

    kind: Literal[
        "help",
        "usage",
        "status",
        "status_detail",
        "at_toggle",
        "self_mute",
        "mute",
        "cancel",
        "invalid",
    ]
    target_scope: Literal["none", "users", "whole", "self", "all_users"] = "none"
    user_ids: list[int] = field(default_factory=list)
    duration_minutes: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    repeat_kind: Literal["none", "daily"] = "none"
    daily_start_minutes: Optional[int] = None
    cancel_scope: Literal["current", "scheduled", "all"] = "current"
    detail_section: Optional[Literal["current", "scheduled", "daily", "long", "all"]] = None
    page: int = 1
    at_toggle_enabled: Optional[bool] = None
    error_message: Optional[str] = None


@dataclass(slots=True)
class DurationParseResult:
    """时长解析结果"""

    minutes: Optional[int] = None
    error: Optional[str] = None


@dataclass(slots=True)
class DateTimeMatch:
    """时间表达式匹配结果"""

    dt: datetime
    start_index: int
    end_index: int
    explicit_date: bool


@dataclass(slots=True)
class ClockMatch:
    """时刻表达式匹配结果"""

    hour: int
    minute: int
    start_index: int
    end_index: int


@dataclass(slots=True)
class TimingParseResult:
    """禁言时间参数解析结果"""

    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    uses_schedule: bool = False
    error: Optional[str] = None


@dataclass(slots=True)
class DailyTimingParseResult:
    """每日禁言时间参数解析结果"""

    start_minutes: Optional[int] = None
    duration_minutes: Optional[int] = None
    error: Optional[str] = None


def normalize_text(text: str) -> str:
    """将文本标准化，便于后续解析"""
    normalized = text.lower().strip()
    replacements = {
        "：": ":",
        "，": " ",
        "　": " ",
        "；": " ",
        "、": " ",
        "（": " ",
        "）": " ",
        "【": " ",
        "】": " ",
        "“": '"',
        "”": '"',
        "\n": " ",
        "\t": " ",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)

    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def is_question_like(text: str) -> bool:
    """判断一句话是否更像询问而不是命令"""
    normalized = normalize_text(text)
    if any(normalized.startswith(prefix) for prefix in QUESTION_PREFIXES):
        return True
    return normalized.endswith(QUESTION_SUFFIXES)


def parse_target_info(
    message: Message,
    exclude_user_ids: Optional[Set[int]] = None,
) -> TargetInfo:
    """解析消息中的 @ 目标"""
    exclude_user_ids = exclude_user_ids or set()
    user_ids: list[int] = []
    seen: set[int] = set()
    has_at_all = False

    for segment in message:
        if segment.type != "at":
            continue

        raw_target = str(segment.data.get("qq", "")).strip()
        if not raw_target:
            continue

        if raw_target == "all":
            has_at_all = True
            continue

        if not raw_target.isdigit():
            continue

        user_id = int(raw_target)
        if user_id in exclude_user_ids or user_id in seen:
            continue

        seen.add(user_id)
        user_ids.append(user_id)

    return TargetInfo(user_ids=user_ids, has_at_all=has_at_all)


def parse_at_targets(
    message: Message,
    exclude_user_ids: Optional[Set[int]] = None,
) -> list[int]:
    """兼容旧逻辑，返回普通 @ 用户列表"""
    return parse_target_info(message, exclude_user_ids=exclude_user_ids).user_ids


def build_at_message(user_ids: list[int]) -> Message:
    """构建 @ 多个用户的消息"""
    message = Message()
    for index, user_id in enumerate(user_ids):
        if index > 0:
            message += " "
        message += MessageSegment.at(user_id)
    return message


def _parse_plain_number(text: str) -> Optional[int]:
    """解析阿拉伯数字或常见中文数字"""
    stripped = text.strip()
    if not stripped:
        return None

    if stripped.isdigit():
        return int(stripped)

    if stripped == "半":
        return 30

    if stripped == "一刻":
        return 15

    if stripped == "三刻":
        return 45

    if all(character in CHINESE_DIGITS or character == "十" for character in stripped):
        if stripped == "十":
            return 10

        if "十" not in stripped:
            value = 0
            for character in stripped:
                value = value * 10 + CHINESE_DIGITS[character]
            return value

        left, _, right = stripped.partition("十")
        tens = 1 if not left else CHINESE_DIGITS[left]
        ones = 0 if not right else CHINESE_DIGITS[right]
        return tens * 10 + ones

    return None


def _apply_period(hour: int, period: Optional[str]) -> int:
    """根据时间段修正小时数"""
    if period in {"凌晨"}:
        return 0 if hour == 12 else hour
    if period in {"早上", "早晨", "上午"}:
        return 0 if hour == 12 else hour
    if period == "中午":
        if hour == 0:
            return 12
        return hour if hour >= 11 else hour + 12
    if period in {"下午", "傍晚", "晚上", "今晚"}:
        if hour < 12:
            return hour + 12
    return hour


def _parse_clock_expression(text: str) -> Optional[Tuple[int, int, int]]:
    """解析时钟表达式，返回 (小时, 分钟, 消耗长度)"""
    colon_match = re.match(
        r"(?P<period>凌晨|早上|早晨|上午|中午|下午|傍晚|晚上)?\s*"
        r"(?P<hour>\d{1,2})[:：](?P<minute>\d{2})",
        text,
    )
    if colon_match:
        hour = int(colon_match.group("hour"))
        minute = int(colon_match.group("minute"))
        if hour > 23 or minute > 59:
            return None

        hour = _apply_period(hour, colon_match.group("period"))
        if hour > 23:
            return None
        return hour, minute, colon_match.end()

    point_match = re.match(
        r"(?P<period>凌晨|早上|早晨|上午|中午|下午|傍晚|晚上)?\s*"
        r"(?P<hour>[零〇一二三四五六七八九十两\d]{1,3})点"
        r"(?P<minute>半|一刻|三刻|[零〇一二三四五六七八九十两\d]{1,3}分?)?",
        text,
    )
    if not point_match:
        return None

    hour = _parse_plain_number(point_match.group("hour"))
    if hour is None:
        return None

    minute_token = point_match.group("minute")
    if not minute_token:
        minute = 0
    elif minute_token == "半":
        minute = 30
    elif minute_token == "一刻":
        minute = 15
    elif minute_token == "三刻":
        minute = 45
    else:
        minute = _parse_plain_number(minute_token.removesuffix("分"))
        if minute is None:
            return None

    if hour > 23 or minute > 59:
        return None

    hour = _apply_period(hour, point_match.group("period"))
    if hour > 23:
        return None

    return hour, minute, point_match.end()


def _find_first_clock_expression(text: str) -> Optional[ClockMatch]:
    """在文本中寻找第一个时刻表达式"""
    for index, character in enumerate(text):
        if character.isspace():
            continue

        if character not in "凌晨早上晨上午中午下午傍晚晚0123456789零〇一二三四五六七八九十两":
            continue

        match = _parse_clock_expression(text[index:])
        if match is None:
            continue

        hour, minute, length = match
        return ClockMatch(
            hour=hour,
            minute=minute,
            start_index=index,
            end_index=index + length,
        )

    return None


def _resolve_date_from_prefix(
    prefix: Optional[str],
    now: datetime,
) -> Optional[Tuple[datetime.date, bool, Optional[str]]]:
    """根据日期前缀解析出目标日期"""
    if not prefix:
        return now.date(), False, None

    prefix = prefix.strip()
    if prefix in {"今天"}:
        return now.date(), True, None
    if prefix in {"今晚"}:
        return now.date(), True, "今晚"
    if prefix in {"今早", "今晨"}:
        return now.date(), True, "早上"
    if prefix == "明天":
        return (now + timedelta(days=1)).date(), True, None
    if prefix == "明晚":
        return (now + timedelta(days=1)).date(), True, "晚上"
    if prefix in {"明早", "明晨"}:
        return (now + timedelta(days=1)).date(), True, "早上"
    if prefix == "后天":
        return (now + timedelta(days=2)).date(), True, None

    if prefix.startswith("下周"):
        weekday_text = prefix[-1]
        weekday = WEEKDAY_MAP.get(weekday_text)
        if weekday is None:
            return None

        days_until_next_week = 7 - now.weekday()
        next_week_start = (now + timedelta(days=days_until_next_week)).date()
        return next_week_start + timedelta(days=weekday), True, None

    return None


def _parse_datetime_prefix(
    text: str,
    now: datetime,
    reference_time: Optional[datetime] = None,
) -> Optional[DateTimeMatch]:
    """从文本开头解析时间表达式"""
    stripped = text.lstrip()
    offset = len(text) - len(stripped)
    candidate = stripped

    candidate = re.sub(r"^(在|于|从)\s*", "", candidate)
    prefix_match = re.match(
        r"(?P<prefix>今天|今晚|今早|今晨|明天|明晚|明早|明晨|后天|下周[一二三四五六日天])?\s*",
        candidate,
    )
    if prefix_match is None:
        return None

    prefix = prefix_match.group("prefix")
    prefix_end = prefix_match.end()
    date_info = _resolve_date_from_prefix(prefix, now)
    if date_info is None:
        return None

    target_date, explicit_date, inherited_period = date_info
    clock_match = _parse_clock_expression(candidate[prefix_end:])
    if clock_match is None:
        return None

    hour, minute, clock_length = clock_match
    if inherited_period:
        hour = _apply_period(hour, inherited_period)

    if hour > 23 or minute > 59:
        return None

    if explicit_date:
        matched_time = datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=BEIJING_TZ,
        )
        if matched_time <= now and prefix in {"今天", "今晚", "今早", "今晨"}:
            return None
    else:
        base = reference_time or now
        matched_time = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if matched_time <= base:
            matched_time += timedelta(days=1)

    consumed = prefix_end + clock_length
    return DateTimeMatch(
        dt=matched_time,
        start_index=offset,
        end_index=offset + consumed,
        explicit_date=explicit_date,
    )


def _find_first_datetime(
    text: str,
    now: datetime,
    reference_time: Optional[datetime] = None,
) -> Optional[DateTimeMatch]:
    """在文本中寻找第一个时间表达式"""
    for index, character in enumerate(text):
        if character.isspace():
            continue

        if character not in "今明后下凌晨早上晨上午中午下午傍晚晚0123456789零〇一二三四五六七八九十两":
            continue

        match = _parse_datetime_prefix(text[index:], now, reference_time=reference_time)
        if match is None:
            continue

        match.start_index += index
        match.end_index += index
        return match

    return None


def _find_all_datetimes(text: str, now: datetime) -> list[DateTimeMatch]:
    """按出现顺序提取文本中的时间表达式"""
    matches: list[DateTimeMatch] = []
    offset = 0
    reference_time: Optional[datetime] = None

    while offset < len(text):
        match = _find_first_datetime(text[offset:], now, reference_time=reference_time)
        if match is None:
            break

        match.start_index += offset
        match.end_index += offset
        matches.append(match)
        offset = match.end_index
        reference_time = match.dt

    return matches


def _is_time_only_text(text: str, now: datetime) -> bool:
    """判断一段前缀文本是否只由时间表达式和连接词组成"""
    remaining = text.strip()
    if not remaining:
        return True

    remaining = re.sub(r"^(在|于|从)\s*", "", remaining)
    reference_time: Optional[datetime] = None
    while remaining:
        match = _parse_datetime_prefix(remaining, now, reference_time=reference_time)
        if match is None or match.start_index != 0:
            return False

        reference_time = match.dt
        remaining = remaining[match.end_index :].strip()
        remaining = re.sub(
            rf"^(?:{UNTIL_CONNECTOR_PATTERN}|然后|再|开始|起)\s*",
            "",
            remaining,
        )
        remaining = re.sub(r"^(在|于|从)\s*", "", remaining)

    return True


def _extract_delay_minutes(text: str) -> Optional[int]:
    """从文本中提取“多久后”表达，返回分钟数"""
    normalized = normalize_text(text)
    delay_match = re.search(
        rf"(?P<delay>[零〇一二三四五六七八九十两\d]+\s*"
        rf"(秒钟|秒|sec|secs|second|seconds|s|分钟|分|min|mins|minute|minutes|m|"
        rf"小时|时|hour|hours|hr|hrs|h|天|day|days|d|个月|月|mon|month|months))\s*"
        rf"{DELAY_CONNECTOR_PATTERN}",
        normalized,
    )
    if delay_match is None:
        return None

    result = parse_duration(delay_match.group("delay"))
    if result.error or result.minutes is None:
        return None
    return result.minutes


def _looks_like_invalid_clock(text: str) -> bool:
    """判断文本中是否包含明显不合法的时间写法"""
    if re.search(r"\d{1,2}[:：]\d{2}", text):
        return True
    return bool(re.search(r"[零〇一二三四五六七八九十两\d]{1,3}点", text))


def parse_duration(text: str) -> DurationParseResult:
    """解析时长文本，返回分钟数"""
    normalized = normalize_text(text)
    if not normalized:
        return DurationParseResult()

    if normalized.isdigit():
        return DurationParseResult(minutes=int(normalized))

    number_pattern = r"(?P<value>[零〇一二三四五六七八九十两\d]{1,3})"
    patterns: list[Tuple[str, float, bool]] = [
        (
            rf"{number_pattern}\s*(秒钟|秒|sec|secs|second|seconds|s)(?![a-z\u4e00-\u9fff])",
            1 / 60,
            False,
        ),
        (
            rf"{number_pattern}\s*(分钟|分|min|mins|minute|minutes|m)(?![a-z\u4e00-\u9fff])",
            1,
            False,
        ),
        (
            rf"{number_pattern}\s*(小时|时|hour|hours|hr|hrs|h)(?![a-z\u4e00-\u9fff])",
            60,
            False,
        ),
        (
            rf"{number_pattern}\s*(天|day|days|d)(?![a-z\u4e00-\u9fff])",
            24 * 60,
            False,
        ),
        (
            rf"{number_pattern}\s*(个月|月|mon|month|months)(?![a-z\u4e00-\u9fff])",
            30 * 24 * 60,
            True,
        ),
    ]

    for pattern, multiplier, is_month in patterns:
        match = re.search(pattern, normalized)
        if not match:
            continue

        value = _parse_plain_number(match.group("value"))
        if value is None:
            continue
        if is_month and value > MAX_MONTHS:
            return DurationParseResult(error="月份时长最多只能写到 12 个月喵~")

        return DurationParseResult(minutes=max(1, ceil(value * multiplier)))

    if re.search(r"\d+\s*(个月|月|mon|month|months)", normalized):
        return DurationParseResult(error="月份时长最多只能写到 12 个月喵~")

    if re.search(r"\d+\s*(天|day|days|d|小时|时|hour|hours|h|分钟|分|min|minute|minutes|秒钟|秒|sec|second|seconds|s)", normalized):
        return DurationParseResult(error="时长写法不太对，猫猫没看懂喵~")

    return DurationParseResult()


def parse_time_range(text: str, now: Optional[datetime] = None) -> TimingParseResult:
    """解析禁言时间参数"""
    now = now or datetime.now(BEIJING_TZ)
    normalized = normalize_text(text)
    if not normalized:
        return TimingParseResult()

    delay_match = re.search(
        rf"(?P<delay>[零〇一二三四五六七八九十两\d]+\s*"
        rf"(秒钟|秒|sec|secs|second|seconds|s|分钟|分|min|mins|minute|minutes|m|"
        rf"小时|时|hour|hours|hr|hrs|h|天|day|days|d|个月|月|mon|month|months))\s*"
        rf"{DELAY_CONNECTOR_PATTERN}",
        normalized,
    )
    if delay_match is not None:
        delay_result = parse_duration(delay_match.group("delay"))
        if delay_result.error:
            return TimingParseResult(error=delay_result.error)
        if delay_result.minutes is None:
            return TimingParseResult(error="多久后开始的写法不太对，猫猫没看懂喵~")

        start_time = now + timedelta(minutes=delay_result.minutes)
        remainder = normalized[delay_match.end() :].strip()

        until_match = re.search(rf"{UNTIL_CONNECTOR_PATTERN}\s*(.+)$", remainder)
        if until_match:
            end_match = _find_first_datetime(
                until_match.group(1),
                now,
                reference_time=start_time,
            )
            if end_match is None:
                return TimingParseResult(error="结束时间写法不太对，猫猫没看懂喵~")
            if end_match.dt <= start_time:
                return TimingParseResult(error="结束时间要晚于开始时间喵~")

            duration_minutes = max(
                1,
                ceil((end_match.dt - start_time).total_seconds() / 60),
            )
            return TimingParseResult(
                start_time=start_time,
                end_time=end_match.dt,
                duration_minutes=duration_minutes,
                uses_schedule=True,
            )

        duration_result = parse_duration(remainder)
        if duration_result.error:
            return TimingParseResult(error=duration_result.error)
        if duration_result.minutes is not None:
            end_time = start_time + timedelta(minutes=duration_result.minutes)
            return TimingParseResult(
                start_time=start_time,
                end_time=end_time,
                duration_minutes=duration_result.minutes,
                uses_schedule=True,
            )

        return TimingParseResult(
            start_time=start_time,
            uses_schedule=True,
        )

    datetime_matches = _find_all_datetimes(normalized, now)
    if not datetime_matches:
        duration_result = parse_duration(normalized)
        if duration_result.error:
            return TimingParseResult(error=duration_result.error)

        if _looks_like_invalid_clock(normalized):
            return TimingParseResult(error="时间写法不合法，猫猫没法安排喵~")

        return TimingParseResult(duration_minutes=duration_result.minutes)

    if len(datetime_matches) >= 2:
        start_time = datetime_matches[0].dt
        end_time = datetime_matches[1].dt
        if end_time <= start_time:
            return TimingParseResult(error="结束时间要晚于开始时间喵~")

        duration_minutes = max(1, ceil((end_time - start_time).total_seconds() / 60))
        return TimingParseResult(
            start_time=start_time,
            end_time=end_time,
            duration_minutes=duration_minutes,
            uses_schedule=True,
        )

    only_match = datetime_matches[0]
    prefix = normalized[: only_match.start_index].strip()
    suffix = normalized[only_match.end_index :].strip()

    if re.search(rf"{UNTIL_CONNECTOR_PATTERN}\s*$", prefix):
        if only_match.dt <= now:
            return TimingParseResult(error="结束时间已经过去啦，换个未来时间再试试喵~")

        duration_minutes = max(1, ceil((only_match.dt - now).total_seconds() / 60))
        return TimingParseResult(
            end_time=only_match.dt,
            duration_minutes=duration_minutes,
            uses_schedule=False,
        )

    duration_result = parse_duration(suffix)
    if duration_result.error:
        return TimingParseResult(error=duration_result.error)
    if duration_result.minutes is not None:
        end_time = only_match.dt + timedelta(minutes=duration_result.minutes)
        return TimingParseResult(
            start_time=only_match.dt,
            end_time=end_time,
            duration_minutes=duration_result.minutes,
            uses_schedule=True,
        )

    if re.search(UNTIL_CONNECTOR_PATTERN, suffix):
        return TimingParseResult(error="结束时间写法不太对，猫猫没看懂喵~")

    return TimingParseResult(
        start_time=only_match.dt,
        uses_schedule=True,
    )


def parse_daily_time_range(text: str) -> DailyTimingParseResult:
    """解析每日禁言时间参数"""
    normalized = normalize_text(text)
    keyword_matches = list(re.finditer(r"(?:每天|每日)\s*", normalized))
    if not keyword_matches:
        return DailyTimingParseResult()

    daily_keyword_match = None
    daily_clock_match = None
    for keyword_match in keyword_matches:
        suffix = normalized[keyword_match.end() :]
        clock_match = _find_first_clock_expression(suffix)
        if clock_match is None:
            continue

        daily_keyword_match = keyword_match
        daily_clock_match = ClockMatch(
            hour=clock_match.hour,
            minute=clock_match.minute,
            start_index=keyword_match.end() + clock_match.start_index,
            end_index=keyword_match.end() + clock_match.end_index,
        )
        break

    if daily_keyword_match is None or daily_clock_match is None:
        return DailyTimingParseResult(error="“每天”后面要接具体时刻喵，比如每天10点或每天下午八点半~")

    start_minutes = daily_clock_match.hour * 60 + daily_clock_match.minute
    remainder = normalize_text(
        f"{normalized[:daily_keyword_match.start()]} {normalized[daily_clock_match.end_index:]}"
    )

    until_match = re.search(rf"{UNTIL_CONNECTOR_PATTERN}\s*(.+)$", remainder)
    if until_match:
        end_clock_match = _find_first_clock_expression(until_match.group(1))
        if end_clock_match is None:
            return DailyTimingParseResult(error="每日禁言的结束时刻写得不太清楚，猫猫没看懂喵~")

        end_minutes = end_clock_match.hour * 60 + end_clock_match.minute
        duration_minutes = end_minutes - start_minutes
        if duration_minutes <= 0:
            duration_minutes += 24 * 60

        return DailyTimingParseResult(
            start_minutes=start_minutes,
            duration_minutes=duration_minutes,
        )

    duration_result = parse_duration(remainder)
    if duration_result.error:
        return DailyTimingParseResult(error=duration_result.error)
    if duration_result.minutes is not None:
        if duration_result.minutes > MAX_DAILY_DURATION_MINUTES:
            return DailyTimingParseResult(error="每日禁言单次持续时间不能超过 24 小时喵~")
        return DailyTimingParseResult(
            start_minutes=start_minutes,
            duration_minutes=duration_result.minutes,
        )

    return DailyTimingParseResult(start_minutes=start_minutes)


def format_remaining_time(end_time: datetime, now: Optional[datetime] = None) -> str:
    """将结束时间格式化为可读的剩余时间"""
    now = now or datetime.now(BEIJING_TZ)
    seconds = max(0, int((end_time - now).total_seconds()))

    days, seconds = divmod(seconds, 24 * 3600)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分钟")
    if seconds and not parts:
        parts.append(f"{seconds}秒")

    return "".join(parts) if parts else "0秒"


def format_duration_display(minutes: int) -> str:
    """将分钟数格式化为人类可读的时长"""
    if minutes <= 0:
        return "0分钟"

    days, remaining_minutes = divmod(minutes, 24 * 60)
    hours, remaining_minutes = divmod(remaining_minutes, 60)

    parts: list[str] = []
    if days:
        if days % 30 == 0:
            months = days // 30
            parts.append(f"{months}个月")
            days = 0
        else:
            parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if remaining_minutes:
        parts.append(f"{remaining_minutes}分钟")

    return "".join(parts) if parts else "0分钟"


def format_clock_minutes(total_minutes: int) -> str:
    """将一天内的分钟数格式化为时刻"""
    hours, minutes = divmod(total_minutes % (24 * 60), 60)
    return f"{hours:02d}:{minutes:02d}"


def format_time_display(dt: datetime) -> str:
    """格式化时刻"""
    return dt.strftime("%H:%M")


def format_datetime_display(dt: datetime) -> str:
    """格式化日期与时刻"""
    return dt.strftime("%m-%d %H:%M")


T = TypeVar("T")


def paginate_items(items: list[T], page: int, page_size: int = STATUS_PAGE_SIZE) -> Tuple[list[T], int]:
    """对列表进行简单分页"""
    if page < 1:
        page = 1

    total_pages = max(1, ceil(len(items) / page_size)) if items else 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], total_pages


def parse_status_command(text: str) -> Optional[ParsedCommand]:
    """解析状态类命令"""
    normalized = normalize_text(text)
    compact = normalized.replace(" ", "")
    if compact in STATUS_ALIASES:
        return ParsedCommand(kind="status")

    detail_patterns: list[tuple[str, Literal["current", "scheduled", "daily", "long", "all"]]] = [
        (r"^(?:查看|展开)(?:当前禁言|禁言列表)(?:第(\d+)页)?$", "current"),
        (r"^(?:查看|展开)(?:定时任务|定时禁言|定时禁言列表)(?:第(\d+)页)?$", "scheduled"),
        (r"^(?:查看|展开)(?:每日任务|每日禁言|每日禁言列表)(?:第(\d+)页)?$", "daily"),
        (r"^(?:查看|展开)(?:长期禁言|长期计划|长期禁言计划)(?:第(\d+)页)?$", "long"),
        (r"^(?:查看|展开)(?:全部状态|完整状态)(?:第(\d+)页)?$", "all"),
    ]
    for pattern, section in detail_patterns:
        matched = re.match(pattern, compact)
        if matched:
            page_text = matched.group(1)
            page = int(page_text) if page_text else 1
            return ParsedCommand(kind="status_detail", detail_section=section, page=page)

    return None


def _mentions_whole_target(compact: str) -> bool:
    """判断文本是否明确提到了全员目标"""
    return bool(
        re.search(
            r"(全员|全体|所有人|全部人|全群|全群成员|全体成员)(?=$|的|禁|状|任|未|解|取|关|定|计)",
            compact,
        )
    )


def _mentions_all_users_cancel_target(compact: str) -> bool:
    """判断文本是否明确提到了“所有成员的个人禁言状态”"""
    return bool(
        re.search(
            r"(全员|全体|所有人|全部人|所有成员|全部成员|全群成员|全体成员)的?"
            r"(?:定时禁言|定时任务|未来禁言|禁言|所有禁言|全部禁言|所有禁言状态|全部禁言状态|所有状态|全部状态)",
            compact,
        )
    )


def _looks_like_mute_command(
    normalized: str,
    target_info: TargetInfo,
    now: datetime,
) -> bool:
    """判断文本是否像一条真正的禁言命令，而不是普通聊天"""
    if "禁言" not in normalized:
        return False

    has_target = (
        target_info.has_at_all
        or bool(target_info.user_ids)
        or any(keyword in normalized for keyword in WHOLE_TARGET_KEYWORDS)
    )
    if not has_target:
        return False

    if any(keyword in normalized for keyword in DAILY_KEYWORDS):
        daily_timing = parse_daily_time_range(normalized)
        if daily_timing.start_minutes is not None:
            return True

    if normalized.startswith(("禁言", "定时禁言", "给", "把", "将", "安排")):
        return True

    mute_index = normalized.find("禁言")
    prefix = normalized[:mute_index].strip()
    while prefix:
        new_prefix = re.sub(
            r"(给|把|将|安排|全员|全体|所有人|全部人|全群|全群成员|全体成员)\s*$",
            "",
            prefix,
        ).strip()
        if new_prefix == prefix:
            break
        prefix = new_prefix

    return _is_time_only_text(prefix, now) or _extract_delay_minutes(prefix) is not None


def is_help_command(text: str) -> bool:
    """兼容旧接口，判断是否为帮助命令"""
    return normalize_text(text) in HELP_ALIASES


def is_status_command(text: str) -> bool:
    """兼容旧接口，判断是否为状态命令"""
    return parse_status_command(text) is not None


def is_self_mute_command(text: str) -> bool:
    """兼容旧接口，判断是否为禁我命令"""
    return normalize_text(text) in SELF_MUTE_ALIASES


def is_at_toggle_command(text: str) -> Optional[bool]:
    """兼容旧接口，判断是否为 at 开关命令"""
    normalized = normalize_text(text).replace(" ", "")
    if normalized in AT_TOGGLE_ENABLE_PHRASES:
        return True
    if normalized in AT_TOGGLE_DISABLE_PHRASES:
        return False
    return None


def is_cancel_command(text: str) -> bool:
    """兼容旧接口，判断是否为取消类命令"""
    normalized = normalize_text(text)
    return normalized.startswith(("取消", "解除", "解禁"))


def is_mute_command(text: str) -> bool:
    """兼容旧接口，判断是否为禁言类命令"""
    normalized = normalize_text(text)
    return "禁言" in normalized or normalized.startswith("始终禁言")


def is_whole_unmute_command(text: str) -> bool:
    """兼容旧接口，判断是否为全员解禁命令"""
    normalized = normalize_text(text).replace(" ", "")
    return normalized in WHOLE_UNMUTE_PHRASES


def is_whole_mute_command(text: str) -> bool:
    """兼容旧接口，判断是否为全员禁言命令"""
    normalized = normalize_text(text).replace(" ", "")
    if normalized in WHOLE_UNMUTE_PHRASES:
        return False
    return any(normalized.startswith(prefix.replace(" ", "")) for prefix in WHOLE_MUTE_PREFIXES)


def extract_whole_mute_duration(text: str) -> Optional[int]:
    """兼容旧接口，提取全员禁言时长"""
    result = parse_duration(normalize_text(text))
    return result.minutes


def extract_mute_remaining_text(raw_msg: str, message: Message) -> str:
    """兼容旧接口，保留文本内容供调试使用"""
    del raw_msg
    parts: list[str] = []
    for segment in message:
        if segment.type == "text":
            parts.append(segment.data.get("text", ""))
    return normalize_text(" ".join(parts))


def parse_user_command(
    message: Message,
    plain_text: str,
    *,
    exclude_user_ids: Optional[Set[int]] = None,
    now: Optional[datetime] = None,
) -> Optional[ParsedCommand]:
    """解析用户命令"""
    now = now or datetime.now(BEIJING_TZ)
    normalized = normalize_text(plain_text)
    compact = normalized.replace(" ", "")
    target_info = parse_target_info(message, exclude_user_ids=exclude_user_ids)

    if not normalized:
        return None

    if is_question_like(normalized):
        return None

    if compact in HELP_ALIASES:
        return ParsedCommand(kind="help")

    if compact in USAGE_ALIASES:
        return ParsedCommand(kind="usage")

    status_command = parse_status_command(normalized)
    if status_command is not None:
        return status_command

    at_toggle = is_at_toggle_command(normalized)
    if at_toggle is not None:
        return ParsedCommand(kind="at_toggle", at_toggle_enabled=at_toggle)

    if normalized in SELF_MUTE_ALIASES:
        return ParsedCommand(kind="self_mute", target_scope="self")

    explicit_whole_unmute = compact in WHOLE_UNMUTE_PHRASES
    explicit_whole_mute = any(
        compact.startswith(prefix.replace(" ", "")) for prefix in WHOLE_MUTE_PREFIXES
    )
    has_whole_target = target_info.has_at_all or explicit_whole_mute or _mentions_whole_target(compact)
    has_any_target = has_whole_target or bool(target_info.user_ids)
    has_daily_keyword = any(keyword in normalized for keyword in DAILY_KEYWORDS)
    daily_timing = parse_daily_time_range(normalized) if has_daily_keyword else None

    if target_info.has_at_all and target_info.user_ids:
        return ParsedCommand(
            kind="invalid",
            error_message="不能同时 @ 全体成员和普通成员喵，换一种说法再试试吧~",
        )

    if normalized.startswith(("取消", "解除", "解禁")) or explicit_whole_unmute:
        cancel_scope: Literal["current", "scheduled", "all"] = "current"
        if any(keyword in normalized for keyword in ALL_CANCEL_KEYWORDS):
            cancel_scope = "all"
        elif any(keyword in normalized for keyword in SCHEDULED_CANCEL_KEYWORDS):
            cancel_scope = "scheduled"
        elif any(keyword in normalized for keyword in CURRENT_CANCEL_KEYWORDS):
            cancel_scope = "current"

        if _mentions_all_users_cancel_target(compact):
            return ParsedCommand(
                kind="cancel",
                target_scope="all_users",
                cancel_scope=cancel_scope,
            )

        if explicit_whole_unmute or target_info.has_at_all or _mentions_whole_target(compact):
            return ParsedCommand(
                kind="cancel",
                target_scope="whole",
                cancel_scope=cancel_scope,
            )

        if not target_info.user_ids:
            return None

        return ParsedCommand(
            kind="cancel",
            target_scope="users",
            user_ids=target_info.user_ids,
            cancel_scope=cancel_scope,
        )

    if (
        daily_timing is not None
        and daily_timing.error
        and "禁言" in normalized
        and has_any_target
    ):
        return ParsedCommand(kind="invalid", error_message=daily_timing.error)

    mute_intent = explicit_whole_mute or _looks_like_mute_command(
        normalized,
        target_info,
        now,
    )
    if not mute_intent:
        return None

    if has_whole_target:
        if daily_timing is not None and daily_timing.start_minutes is not None:
            return ParsedCommand(
                kind="mute",
                target_scope="whole",
                repeat_kind="daily",
                daily_start_minutes=daily_timing.start_minutes,
                duration_minutes=daily_timing.duration_minutes,
            )

        timing = parse_time_range(normalized, now=now)
        if timing.error:
            return ParsedCommand(kind="invalid", error_message=timing.error)

        return ParsedCommand(
            kind="mute",
            target_scope="whole",
            duration_minutes=timing.duration_minutes,
            start_time=timing.start_time,
            end_time=timing.end_time,
        )

    if not target_info.user_ids:
        return ParsedCommand(kind="invalid", error_message="要先 @ 目标成员，猫猫才知道该对谁下手喵~")

    if daily_timing is not None and daily_timing.start_minutes is not None:
        return ParsedCommand(
            kind="mute",
            target_scope="users",
            user_ids=target_info.user_ids,
            repeat_kind="daily",
            daily_start_minutes=daily_timing.start_minutes,
            duration_minutes=daily_timing.duration_minutes,
        )

    timing = parse_time_range(normalized, now=now)
    if timing.error:
        return ParsedCommand(kind="invalid", error_message=timing.error)

    return ParsedCommand(
        kind="mute",
        target_scope="users",
        user_ids=target_info.user_ids,
        duration_minutes=timing.duration_minutes,
        start_time=timing.start_time,
        end_time=timing.end_time,
    )
