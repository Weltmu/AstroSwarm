"""硬休眠状态机：睡着后只有你同学能叫醒，其他人无法互动，到起床时间自然醒"""
import logging
import random
import time
from datetime import datetime
from zoneinfo import ZoneInfo


class SleepManager:
    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = getattr(cfg, "sleep_enabled", True)
        self.state = "awake"        # awake | asleep
        self.sleep_start = 0
        self.wake_ts = 0
        self.greeted = False

    def _hour(self, now):
        return datetime.fromtimestamp(now, ZoneInfo(self.cfg.tz)).hour

    def _fmt(self, ts):
        return datetime.fromtimestamp(ts, ZoneInfo(self.cfg.tz)).strftime("%H:%M")

    def sample_duration_hours(self):
        r = random.random()
        if r < 0.6:
            return random.uniform(6, 8)      # 6~8 小时概率最大
        return random.uniform(self.cfg.sleep_min_hours, self.cfg.sleep_max_hours)

    def enter_sleep(self, now):
        if not self.enabled:
            return
        self.state = "asleep"
        self.sleep_start = now
        self.wake_ts = now + self.sample_duration_hours() * 3600
        self.greeted = False
        logging.info("进入休眠，预计 %s 醒来（仅你同学可叫醒）", self._fmt(self.wake_ts))

    def should_enter_sleep(self, now, last_active):
        if not self.enabled:
            return False
        if self.state != "awake":
            return False
        h = self._hour(now)
        if 4 <= h < self.cfg.sleep_bedtime_hour:
            return False
        if now - last_active < self.cfg.sleep_idle_minutes * 60:
            return False
        return True

    def on_message(self, now, is_owner):
        """返回 reply / ignore / woke_owner"""
        if not self.enabled:
            return "reply"
        if self.state == "awake":
            return "reply"
        if is_owner:
            self.state = "awake"
            self.greeted = False
            logging.info("你同学把她叫醒了")
            return "woke_owner"
        return "ignore"

    def tick(self, now):
        """心跳：到起床时间自然醒。返回 (event, greet_type)"""
        if not self.enabled:
            return None, None
        if self.state == "asleep" and now >= self.wake_ts:
            self.state = "awake"
            return "woke", self._greet_type(now)
        return None, None

    def _greet_type(self, now):
        h = self._hour(now)
        if 5 <= h < 11:
            return "morning"
        if 11 <= h < 14:
            return "noon"
        if 14 <= h < 18:
            return "afternoon"
        return None

    def describe(self):
        if not self.enabled:
            return ""
        if self.state == "asleep":
            return "你在睡觉（只有你同学能叫醒你）"
        return ""

