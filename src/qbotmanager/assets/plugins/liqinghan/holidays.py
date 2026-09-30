"""节日感知：公历固定节日 + 2026 农历节日换算后的公历日期（春节/元宵/端午/七夕/中秋/重阳）"""
from datetime import date, timedelta


HOLIDAYS = {
    (1, 1): "元旦",
    (2, 14): "情人节",
    (3, 8): "妇女节",
    (3, 12): "植树节",
    (4, 5): "清明节",
    (5, 1): "劳动节",
    (5, 4): "青年节",
    (6, 1): "儿童节",
    (7, 1): "建党节",
    (8, 1): "建军节",
    (9, 10): "教师节",
    (10, 1): "国庆节",
    (10, 31): "万圣节",
    (11, 11): "双十一",
    (12, 24): "平安夜",
    (12, 25): "圣诞节",
    (12, 31): "跨年夜",
}

# 2026 农历节日（按农历换算成公历）
LUNAR_2026 = {
    date(2026, 2, 17): "春节",
    date(2026, 3, 3): "元宵节",
    date(2026, 6, 19): "端午节",
    date(2026, 8, 19): "七夕",
    date(2026, 8, 27): "中元节",
    date(2026, 9, 25): "中秋节",
    date(2026, 10, 18): "重阳节",
}


def _holiday(d):
    return HOLIDAYS.get((d.month, d.day)) or LUNAR_2026.get(d, "")


def today_holiday(cfg):
    return _holiday(cfg.now().date())


def tomorrow_holiday(cfg):
    return _holiday(cfg.now().date() + timedelta(days=1))
