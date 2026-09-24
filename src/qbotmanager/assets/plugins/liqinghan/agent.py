"""李清菡 Agent 主程序：OneBot 事件 → 大脑自主决策 → 工具执行 → 回复"""
import asyncio
import json
import logging
import os
import random
import re
import time
from collections import deque

from . import games, voice
from .chat_archive import ChatArchive
from .brain import Brain
from .config import Config
from .memory import Store
from .persona import build_system, extract_text, familiarity_stage
from .scheduler import reminder_loop
from .sleep import SleepManager
from .tools import Ctx, Tools


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"   # 区域旗帜
    "\U0001F300-\U0001F64F"   # 符号与表情
    "\U0001F680-\U0001F6FF"   # 交通与地图
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F8FF"
    "\U0001F900-\U0001F9FF"   # 补充表情
    "\U0001FA00-\U0001FAFF"
    "\u2600-\u27BF"           # 杂项符号
    "\u2B00-\u2BFF"
    "\u2190-\u21FF"
    "\uFE0F\u200D"            # 变体选择符 / ZWJ
    "]+",
    re.UNICODE,
)

_END_PHRASES = (
    "不聊了", "先不聊", "不想聊", "不说了", "不贫了", "不和你贫", "不扯了", "不唠了",
    "去上课", "去忙", "忙去了", "去吃饭", "睡觉了", "先撤了", "撤了", "闪了", "溜了",
    "拜拜", "再见", "88", "886", "别烦", "拉黑", "不想理", "下了", "晚安",
    "挂了", "先走", "走啦", "不陪了", "就这样吧", "到此为止", "打住", "散了",
    "改天聊", "下次聊", "回头聊", "有事忙",
)

_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)

_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "半": 0.5}


def _cn_to_int(s):
    """中文数字转整数/半（一=1，半=0.5，十五=15，二十=20）。失败返回 None。"""
    if not s:
        return None
    if s == "半":
        return 0.5
    if "十" in s:
        parts = s.split("十")
        tens = _CN_NUM.get(parts[0], 1) if parts[0] else 1
        ones = _CN_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        n = tens * 10 + ones
        return int(n) if n == int(n) else n
    if len(s) == 1:
        return _CN_NUM.get(s)
    return None

_SLEEP_REPLIES = (
    "行，那我睡了，晚安",
    "好，睡觉啦，明天见",
    "困死了，先睡啦，晚安",
    "行行行，睡了，别吵我",
    "好，晚安，梦里见",
    "知道了，这就睡，晚安",
)

_WAKE_REPLIES = (
    "好啦好啦，醒了醒了",
    "干嘛啊，我睡得正香",
    "行行行，起了起了",
    "醒了醒了，咋了",
    "知道了知道了，不睡了",
)

_SHUT_REPLIES = (
    "行行行，我不说了，你们聊",
    "得嘞，我闭嘴",
    "行，你们聊，我听着",
    "好好好，我不插嘴了",
    "行吧，那我先不说了",
)

_SELF_SLEEP = ("我要睡了", "我睡了", "先睡了", "睡觉了", "晚安", "睡了睡了", "不说了睡了", "去睡了")

_GAME_FALLBACKS = (
    "诶，猜对啦，金币发你了",
    "嘿嘿，答对了",
    "不错嘛，金币到手",
)


def strip_emoji(text):
    return _EMOJI_RE.sub("", text or "").strip()


_INNER_THOUGHT_RE = re.compile(
    r"```thinking.*?```"                                   # 思考代码块
    r"|（[^）]*(内心|思考|OS|os|备注|发出去了|等他回|刚发出|自言自语)[^）]*）"  # 括号内心OS
    r"|^(内心|思考|OS|备注|自言自语)[:：].*$",              # 行首内心标记
    re.M | re.S,
)

_FEEDBACK_RE = re.compile(r"^(已发|已发送|发出去了|嗯，发出去了|发送成功|发过去了|好的，已发)[。!！]?$")


def strip_inner_thoughts(text):
    """去掉 AI 泄漏的内心独白/备注，只留真正要说出口的话"""
    text = _INNER_THOUGHT_RE.sub("", text or "")
    out = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if "发出去了" in ln and ("等他回" in ln or "等她回" in ln):
            continue
        if _FEEDBACK_RE.match(ln):
            continue
        out.append(ln)
    return "\n".join(out).strip()


def split_sentences(text, max_len=30, max_msgs=3):
    """把回复拆成一条条短消息：每行一条（模型用换行表达连续消息），过长行再按标点拆"""
    lines = [s.strip() for s in re.split(r"\n+", text) if s.strip()]
    out = []
    for line in lines:
        if len(line) <= max_len:
            out.append(line)
            continue
        for p in re.split(r"(?<=[。！？!?…])", line):
            p = p.strip()
            if not p:
                continue
            if len(p) <= max_len:
                out.append(p)
                continue
            for sub in re.split(r"(?<=[，,、；;])", p):
                sub = sub.strip()
                if not sub:
                    continue
                if len(sub) <= max_len:
                    out.append(sub)
                else:
                    out.extend(sub[i:i + max_len] for i in range(0, len(sub), max_len))
    # 消息条数上限：超出的往后合并
    while len(out) > max_msgs:
        out[-2] += out[-1]
        out.pop()
    return out


def setup_logging(cfg):
    os.makedirs(os.path.dirname(cfg.log_file), exist_ok=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[
            logging.FileHandler(cfg.log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


class Agent:
    def __init__(self, cfg, channel=None):
        self.cfg = cfg
        os.makedirs(cfg.data_dir, exist_ok=True)
        self._known_groups_file = os.path.join(cfg.data_dir, "known_groups.json")
        self._load_known_groups()
        self.store = Store(os.path.join(cfg.data_dir, "agent.db"))
        self.archive = ChatArchive(cfg)
        self._last_user_ts = {}   # session -> 最近一条用户消息时间（算回复延迟）
        self._pending_tools = {}  # session -> 本轮工具调用记录
        _orig_add = self.store.add_message

        def _archived_add(session, role, qq, group_id, text):
            _orig_add(session, role, qq, group_id, text)
            self._archive_message(session, role, qq, group_id, text)

        self.store.add_message = _archived_add
        self.brain = Brain(cfg)
        self.ob = channel
        self.tools = Tools(cfg, self.store, self.ob)
        self._sent_ids = {}          # 机器人发出的消息 id -> 时间戳（判断"回复了她的消息"）
        self._activity = {}          # group_id -> deque[消息时间戳]（近 10 分钟活跃度）
        self._last_interject = {}    # group_id -> 最近一次搭话时间
        self._interject_counts = {}  # group_id -> {小时键: 次数}
        self._last_group_reply = {}  # group_id -> 最近一次回复时间（每日保底）
        self._last_reply = {}        # "session|user" -> 最近回复时间（对话连续性）
        self._conv_end = {}          # "session|user" -> 结束话题后的冷却截止时间
        self._interest_off = {}      # "session|user" -> 判断"没兴趣"的时间（用于时间刷新）
        self._shut_count = {}        # user_id -> 累计"闭嘴"次数（自动降好感度）
        self._bursts = {}            # session -> 连发任务（可被新消息打断）
        self._thinking = {}          # session -> 正在思考回复的任务（新消息打断旧的）
        self.sleep = SleepManager(cfg)
        self._last_activity = time.time()
        self._roles = {}             # (group_id,user_id) -> (role, ts) 成员角色缓存
        self._mem_scan = {}          # qq -> 上次记忆扫描时间
        self._reply_queues = {}      # session -> asyncio.Queue（微信桥取回复）

    def _archive_message(self, session, role, qq, group_id, text):
        """归档一条消息（只写不读；任何异常都不影响主流程）。"""
        try:
            rec = {
                "session": session or "",
                "role": role,
                "user_id": str(qq or ""),
                "nickname": "",
                "group_id": str(group_id or ""),
                "text": text or "",
            }
            if role == "user":
                try:
                    u = self.store.get_user(str(qq)) if qq else None
                    rec["nickname"] = (u["nickname"] if u and u["nickname"] else "") or ""
                except Exception:  # noqa: BLE001
                    pass
                self._last_user_ts[session] = time.time()
            elif role == "assistant":
                last = self._last_user_ts.pop(session, None)
                if last:
                    rec["reply_ms"] = int((time.time() - last) * 1000)
                tools = self._pending_tools.pop(session, None)
                if tools:
                    rec["tool_calls"] = tools
            self.archive.record(**rec)
        except Exception:  # noqa: BLE001
            logging.exception("聊天归档记录失败（不影响机器人）")

    def _load_known_groups(self):
        """加载历史自动学习到的官方群 openid，避免重启后丢失。"""
        try:
            with open(self._known_groups_file, encoding="utf-8") as f:
                data = json.load(f)
            for g in data.get("groups", []) or []:
                g = str(g).strip()
                if g and g not in self.cfg.groups:
                    self.cfg.groups.append(g)
        except Exception:  # noqa: BLE001
            pass

    def _learn_group(self, group_id):
        """官方通道：被 @ 的群自动加入活跃群（openid 用户看不到，只能学习）。"""
        if group_id in self.cfg.groups:
            return
        self.cfg.groups.append(group_id)
        logging.info("自动学习官方群 group=%s（已加入活跃群）", group_id)
        try:
            os.makedirs(os.path.dirname(self._known_groups_file), exist_ok=True)
            with open(self._known_groups_file, "w", encoding="utf-8") as f:
                json.dump({"groups": self.cfg.groups}, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            logging.warning("自动学习群保存失败：%s", e)

    async def on_event(self, data):
        try:
            post_type = data.get("post_type")
            if post_type == "meta_event":
                return
            if post_type == "message":
                await self.handle_message(data)
            elif post_type == "request":
                if data.get("request_type") == "group":
                    self.store.add_join_request(
                        str(data.get("flag", "")),
                        str(data.get("group_id", "")),
                        str(data.get("user_id", "")),
                        str(data.get("comment", "") or ""),
                    )
                    logging.info(
                        "收到入群申请 group=%s user=%s comment=%s",
                        data.get("group_id"), data.get("user_id"), data.get("comment", ""),
                    )
                else:
                    logging.info("收到其他请求事件：%s", data.get("request_type"))
            elif post_type == "notice":
                if data.get("notice_type") == "group_increase":
                    asyncio.create_task(self._on_member_join(data))
        except Exception as e:  # noqa: BLE001
            logging.exception("事件处理失败")
            try:
                self.archive.record(
                    role="system", error=str(e)[:500],
                    session=str(data.get("session") or ""),
                    user_id=str(data.get("user_id") or ""),
                    group_id=str(data.get("group_id") or ""),
                    text="事件处理失败",
                )
            except Exception:  # noqa: BLE001
                pass

    def _is_addressed(self, data, text, segments):
        """被点名：@她 / 回复她的消息 / 消息里带称呼（李清菡/学姐/姐姐等）"""
        for s in segments or []:
            if not isinstance(s, dict):
                continue
            if s.get("type") == "at":
                if str(s.get("data", {}).get("qq", "")) == self.cfg.bot_qq:
                    return True
            if s.get("type") == "reply":
                if str(s.get("data", {}).get("id", "")) in self._sent_ids:
                    return True
        # 称呼匹配：先剔除"@别人"的名字/标记，避免误伤；英文称呼整词匹配，中文称呼子串匹配
        scan = text or ""
        for s in segments or []:
            if isinstance(s, dict) and s.get("type") == "at":
                qq = str(s.get("data", {}).get("qq", "") or "")
                if qq and qq != self.cfg.bot_qq:
                    name = str(s.get("data", {}).get("name", "") or "")
                    if name:
                        scan = scan.replace(name, "")
        scan = re.sub(r"@[^\s,，。！？!?]+", "", scan)
        for w in self.cfg.address_words:
            w = w.strip()
            if not w:
                continue
            if w.isascii() and w.isalpha():
                if re.search(
                    rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])",
                    scan,
                    re.IGNORECASE,
                ):
                    return True
            elif w in scan:
                return True
        return False

    @staticmethod
    def _extract_images(segments):
        """取消息里的图片段：返回 [{file, url}]"""
        out = []
        for s in segments or []:
            if isinstance(s, dict) and s.get("type") == "image":
                d = s.get("data", {}) or {}
                out.append({"file": str(d.get("file") or ""), "url": str(d.get("url") or "")})
        return out

    @staticmethod
    def _is_shut(text):
        return any(w in text for w in ("闭嘴", "别说话", "别说了", "安静", "消停", "不用你说话", "不需要你说话"))

    @staticmethod
    def _is_sleep(text):
        return any(w in text for w in ("睡觉", "去睡", "睡吧", "休息吧", "闭嘴睡觉", "要睡了", "该睡了"))

    @staticmethod
    def _is_wake(text):
        return any(w in text for w in ("别睡", "醒醒", "起床", "醒了", "醒啦", "快起来", "起来吧", "起来别", "不睡了"))

    # ---- 搭话机会控制 ----
    def _interject_probability(self, group_id):
        now = time.time()
        dq = self._activity.setdefault(group_id, deque())
        while dq and now - dq[0] > self.cfg.activity_window_min * 60:
            dq.popleft()
        n = len(dq)
        p = self.cfg.interject_base + min(self.cfg.interject_max, n * 0.008)
        return min(p, self.cfg.interject_max)

    def _should_interject(self, group_id):
        now = time.time()
        if now - self._last_interject.get(group_id, 0) < self.cfg.interject_cooldown_min * 60:
            return False
        hour_key = int(now // 3600)
        if self._interject_counts.get(group_id, {}).get(hour_key, 0) >= self.cfg.interject_max_per_hour:
            return False
        return random.random() < self._interject_probability(group_id)

    async def _maybe_interject(self, group_id, session, forced=False, state_desc=""):
        if not forced and not self._should_interject(group_id):
            logging.info("搭话机会未触发 group=%s", group_id)
            return
        recent = self.store.recent_messages(session, 20)
        if not recent:
            return
        lines = []
        for r in recent:
            who = self.cfg.persona_name if r["role"] == "assistant" else r["qq"]
            lines.append(f"{who}: {r['text']}")
        user_text = (
            f"[现在时间：{self.cfg.now_str()}]\n群里正在聊：\n" + "\n".join(lines) +
            "\n\n你想不想插一句？想说话就自然简短地说一句（可以顺着聊，也可以开个新话题）；" +
            "先看一遍上面的聊天记录，不要重复问已经问过的问题，不要说重复的话；"
            "直接输出你要插嘴说的那句话本身，不要输出'已发''发出去了'这类备注。"
            "如果觉得没必要说话，就只回复两个字：沉默"
        )
        system = build_system(self.cfg, self.store, self.cfg.bot_qq, group_id, state_desc)
        reply = await self.brain.think(system, [], user_text, [], lambda name, args: "ok")
        if reply and reply.strip() not in ("沉默", "沉默。", "（沉默）"):
            await self._reply(session, "group", group_id, "", reply, split=True)
            now = time.time()
            self._last_interject[group_id] = now
            hour_key = int(now // 3600)
            counts = self._interject_counts.setdefault(group_id, {})
            counts[hour_key] = counts.get(hour_key, 0) + 1
            logging.info("搭话 group=%s：%s", group_id, reply)
        else:
            logging.info("搭话机会 group=%s：AI 选择沉默", group_id)

    async def handle_message(self, data):
        self.tools.set_source(data.get("source", "qq:c2c"))
        msg_type = data.get("message_type")
        user_id = str(data.get("user_id", ""))
        group_id = str(data.get("group_id", "")) if msg_type == "group" else ""
        if user_id == self.cfg.bot_qq:
            return
        if msg_type == "group" and self.cfg.groups and group_id not in self.cfg.groups:
            addressed_to_bot = any(
                isinstance(s, dict)
                and s.get("type") == "at"
                and str(s.get("data", {}).get("qq", "")) == self.cfg.bot_qq
                for s in (data.get("message") or [])
            )
            if addressed_to_bot:
                # 官方 openid 用户填不了，被 @ 即自动加入活跃群
                self._learn_group(group_id)
            else:
                logging.info("忽略非活跃群消息 group=%s", group_id)
                return

        images = self._extract_images(data.get("message", []))
        if images:
            logging.info("图片段 raw=%s", [s.get("data") for s in (data.get("message") or []) if isinstance(s, dict) and s.get("type") == "image"])
        text = extract_text(data.get("message", [])).strip()
        if not text and images:
            text = "[图片]"
        nickname = str(data.get("sender", {}).get("card") or data.get("sender", {}).get("nickname") or "")
        self.store.touch_user(user_id, nickname)
        self.store.reset_outreach(user_id)  # 对方先说话 = 打破僵局

        session = str(data.get("session_key") or "")
        if not session:
            session = f"g:{group_id}" if msg_type == "group" else f"p:{user_id}"
        # 新消息来了，先打断同会话正在连发的回复（伪实时：停掉没发完的）
        # INTERRUPT_ON_MESSAGE=false 时保留回复不打断，保证热闹的群里一定回得出来
        if self.cfg.interrupt_on_message:
            self._cancel_burst(self._talk_key(session, user_id))
        if images:
            self.tools.last_images[session] = images
        self.store.add_message(session, "user", user_id, group_id, text or "[非文本消息]")
        logging.info("收到 %s 来自 %s：%s", session, user_id, text)
        if not text:
            return

        # 你同学规则确定性执行（非管理发链接 → 撤回/禁言），群消息才需要
        if msg_type == "group":
            await self._enforce_rules(data, text)

        is_owner = user_id == self.cfg.owner_qq
        # 确定性禁言命令（不经过大模型）：禁言@某人 / 全员禁言 / 解禁
        if msg_type == "group":
            can_manage = is_owner
            if not can_manage:
                sender_role = str(data.get("member_role", "") or "")
                if sender_role:
                    can_manage = sender_role in ("owner", "admin")
                else:
                    can_manage = await self._member_role(group_id, user_id) in ("owner", "admin")
            # 命令必须是对她说的（@她/回她/你同学直说），"@管理员 把@某人禁言"不是她的命令
            cmd_direct = is_owner or self._is_addressed(data, text, data.get("message", []))
            if can_manage and cmd_direct and await self._parse_mute_command(session, group_id, text, data):
                return
        # 叫醒她：只有你同学能叫醒（硬休眠），其他人喊不醒
        if is_owner and self._is_wake(text) and self.sleep.state != "awake":
            self.sleep.state = "awake"
            self.sleep.greeted = False
            confirm = await self._say(
                f"[现在时间：{self.cfg.now_str()}] 你同学把你叫醒了，回一句简短自然的话（带点刚醒的迷糊/起床气）"
            ) or random.choice(_WAKE_REPLIES)
            await self._reply(session, msg_type, group_id, user_id, confirm, split=True)
            return
        # 让她睡觉：你同学 100%，其他人 60% 概率生效
        if self.cfg.sleep_enabled and self._is_sleep(text):
            if is_owner or random.random() < self.cfg.sleep_other_prob:
                self.sleep.enter_sleep(time.time())
                confirm = await self._say(
                    f"[现在时间：{self.cfg.now_str()}] 有人让你睡觉了，你准备入睡，回一句简短自然的话（可以带点困意）"
                ) or random.choice(_SLEEP_REPLIES)
                await self._reply(session, msg_type, group_id, user_id, confirm, split=True)
                return

        directly = self._is_addressed(data, text, data.get("message", []))
        addressed = directly
        # 群里 @ 了别人（没 @ 机器人）= 别人之间的对话：不搭话、不续聊、不回复
        if msg_type == "group" and not directly:
            has_other_at = any(
                isinstance(s, dict)
                and s.get("type") == "at"
                and str(s.get("data", {}).get("qq", "") or "")
                not in ("", self.cfg.bot_qq)
                for s in (data.get("message", []) or [])
            )
            if has_other_at:
                logging.info("@别人 的消息不响应 group=%s", group_id)
                return
        key = f"{session}|{user_id}"
        now = time.time()
        if not addressed and msg_type == "group":
            if (
                now - self._last_reply.get(key, 0) < self.cfg.conv_window_seconds
                or now - self._last_interject.get(group_id, 0) < self.cfg.interject_anchor_seconds
            ):
                off_ts = self._interest_off.get(key, 0)
                if now > self._conv_end.get(key, 0) or (
                    off_ts and now - off_ts > self.cfg.interest_refresh_hours * 3600
                ):
                    addressed = "interest"  # 交给 AI 做兴趣判断，而不是机械续聊

        self._last_activity = time.time()
        mode = self.sleep.on_message(time.time(), is_owner)
        if mode == "ignore":
            logging.info("休眠中，忽略消息（仅你同学可叫醒）")
            return
        if mode == "woke_owner":
            addressed = True  # 你同学发话 → 一定回应
        state_desc = self.sleep.describe()

        # "闭嘴/别说了"：你同学 100%，其他人 60% 概率生效；只冷落当前对话
        if self._is_shut(text):
            if is_owner or random.random() < self.cfg.shut_other_prob:
                key = f"{session}|{user_id}" if user_id else f"g:{group_id}"
                self._last_reply.pop(key, None)
                self._conv_end[key] = time.time() + self.cfg.conv_end_cooldown
                if user_id:
                    n = self._shut_count.get(user_id, 0) + 1
                    self._shut_count[user_id] = n
                    self.store.adjust_anger(user_id, 10)  # 被喊闭嘴，有点气
                    if n % 3 == 0:
                        self.store.adjust_relationship(user_id, -1)
                        logging.info("反复打扰，好感度 -1 user=%s", user_id)
                confirm = await self._say(
                    f"[现在时间：{self.cfg.now_str()}] 有人让你闭嘴别说了，你回一句简短自然的话（有点无奈但顺从，一两句）"
                ) or random.choice(_SHUT_REPLIES)
                await self._reply(session, msg_type, group_id, user_id, confirm, split=True)
                return

        # 群聊小游戏：进行中时，非点名消息优先当作作答处理
        if msg_type == "group" and not addressed:
            s, outcome, extra = games.submit(self.store, group_id, user_id, text)
            if s and outcome:
                if await self._game_reply(s, outcome, extra, user_id, nickname, session, group_id):
                    return

        # 活跃度记录（用于搭话概率）
        if msg_type == "group":
            self._activity.setdefault(group_id, deque()).append(time.time())
            if group_id not in self._last_group_reply:
                self._last_group_reply[group_id] = time.time()

        if addressed == "interest":
            if self.cfg.interrupt_on_message:
                self._cancel_thinking(self._talk_key(session, user_id))
            task = asyncio.create_task(
                self._interest_reply(session, msg_type, group_id, user_id, text, state_desc, data, images=images)
            )
        elif msg_type == "group" and not addressed:
            if self._should_interject(group_id):
                if self.cfg.interrupt_on_message:
                    self._cancel_thinking(self._talk_key(session, user_id))
            task = asyncio.create_task(self._maybe_interject(group_id, session, state_desc=state_desc))
        else:
            if self.cfg.interrupt_on_message:
                self._cancel_thinking(self._talk_key(session, user_id))
            task = asyncio.create_task(
                self._direct_reply(session, msg_type, group_id, user_id, text, data, state_desc=state_desc, images=images)
            )
        self._thinking[self._talk_key(session, user_id)] = task

    async def _game_reply(self, s, outcome, extra, user_id, nickname, session, group_id):
        """游戏作答结果 → AI 现编反应。返回 True 表示已处理"""
        if outcome == "win":
            desc = f"群友 {nickname}(QQ {user_id}) 猜对了游戏答案（答案：{extra[0]}），奖励 {extra[1]} 金币"
        elif outcome == "hint":
            desc = f"猜数字游戏：群友猜的数字比答案更{extra[0]}（已猜错 {extra[1]} 次）"
        elif outcome == "miss":
            desc = f"谜语游戏：群友答错了（已错 {extra[1]} 次）"
        elif outcome == "rps":
            c = {"rock": "石头", "scissors": "剪刀", "paper": "布"}
            if extra[2] == "win":
                desc = f"石头剪刀布：{nickname} 出{c[extra[0]]}，你出{c[extra[1]]}，TA 赢了，奖励 {extra[3]} 金币"
            elif extra[2] == "draw":
                desc = f"石头剪刀布：{nickname} 出{c[extra[0]]}，你出{c[extra[1]]}，平手"
            else:
                desc = f"石头剪刀布：{nickname} 出{c[extra[0]]}，你出{c[extra[1]]}，TA 输了"
        else:
            return False
        reply = await self._say(
            f"[现在时间：{self.cfg.now_str()}] 群聊小游戏：{desc}。"
            "现编一句简短自然的反应（赢了要开心夸TA/发金币确认，错了可以调侃或给提示），一两句"
        )
        await self._reply(session, "group", group_id, user_id, reply or random.choice(_GAME_FALLBACKS), split=True)
        return True

    def _cancel_thinking(self, session):
        prev = self._thinking.pop(session, None)
        if prev and not prev.done():
            prev.cancel()
            logging.info("打断上一条思考中的回复 session=%s", session)

    async def _interest_reply(self, session, msg_type, group_id, user_id, text, state_desc, data, images=None):
        """不 @ 的续聊：让 AI 自己判断感不感兴趣，感兴趣才接着回"""
        ctx = Ctx(
            cfg=self.cfg,
            store=self.store,
            ob=self.ob,
            sender_qq=user_id,
            sender_role=str(data.get("member_role", "") or ""),
            group_id=group_id,
            session_key=session,
            message_id=str(data.get("message_id", "")),
        )
        system = build_system(self.cfg, self.store, user_id, group_id, state_desc)
        history = self.store.recent_user_context(user_id, session, 12)
        rounds = sum(1 for r in history if r["role"] == "assistant")
        rounds_note = f"你们这一阵已经聊了 {rounds} 轮了，聊得挺久了；" if rounds >= 6 else ""
        img_note = ""
        if images:
            desc = await self._describe_images(ctx, images)
            if desc:
                img_note = f"\nTA 还发来了图片，内容：{desc}"
        prompt = (
            f"[现在时间：{self.cfg.now_str()}] 这个人刚才跟你聊过，现在 TA 又发来：'{self._self_at(text)}'。{img_note}"
            f"{rounds_note}"
            "你对这个话题/这个人还感兴趣吗？感兴趣就自然简短地回一句（可以接着聊，也可以转个新话题）；"
            "不感兴趣、聊够了、或者现在不想理 TA，就只回复两个字：沉默。"
            "聊得差不多时别硬撑：回复短一点、不再开新话题、不再追问，自然地冷淡收住。"
        )
        reply = await self.brain.think(system, history, prompt, self.tools.schemas, self._tool_exec(ctx))
        key = f"{session}|{user_id}"
        if reply and reply.strip() not in ("沉默", "沉默。", "（沉默）"):
            await self._reply(session, msg_type, group_id, user_id, reply, split=True)
            logging.info("兴趣续聊 %s：%s", session, reply)
        else:
            # 没兴趣：冷落一段时间，不再反复被问
            self._conv_end[key] = time.time() + self.cfg.conv_end_cooldown
            self._interest_off[key] = time.time()
            self._last_reply.pop(key, None)
            logging.info("AI 判断不感兴趣，话题结束 %s", key)

    async def _direct_reply(self, session, msg_type, group_id, user_id, text, data, state_desc="", images=None):
        ctx = Ctx(
            cfg=self.cfg,
            store=self.store,
            ob=self.ob,
            sender_qq=user_id,
            sender_role=str(data.get("member_role", "") or ""),
            group_id=group_id,
            session_key=session,
            message_id=str(data.get("message_id", "")),
        )
        system = build_system(self.cfg, self.store, user_id, group_id, state_desc)
        history = self.store.recent_user_context(user_id, session, 12)
        img_note = ""
        if images:
            desc = await self._describe_images(ctx, images)
            if desc:
                img_note = f"\n（对方发来的图片内容：{desc}）"
        reply = await self.brain.think(
            system, history, f"[现在时间：{self.cfg.now_str()}] {self._self_at(text)}{img_note}",
            self.tools.schemas, self._tool_exec(ctx),
        )
        if not reply:
            # 被直接点名却空回复：强制重试一次，不许沉默
            logging.info("直接点名空回复，重试一次 %s", session)
            reply = await self.brain.think(
                system, history,
                f"[现在时间：{self.cfg.now_str()}] 有人直接叫你（{self._self_at(text)}{img_note}），你必须回一句，简短自然，别沉默",
                self.tools.schemas, self._tool_exec(ctx),
            )
        if reply:
            await self._reply(session, msg_type, group_id, user_id, reply, split=True)

    async def _describe_images(self, ctx, images):
        """把当前消息里的图片（最多 3 张）转成文字描述；失败返回空串，不阻塞正常回复"""
        if not images or not self.cfg.sf_api_key:
            return ""
        descs = []
        for img in images[:3]:
            src = img.get("file") or img.get("url") or ""
            if not src:
                continue
            try:
                desc = await self.tools.call("describe_image", {"file": src}, ctx)
            except Exception as e:  # noqa: BLE001
                logging.warning("图片描述异常：%s", e)
                continue
            if desc and not desc.startswith("（") and "失败" not in desc:
                descs.append(desc)
            elif desc:
                logging.warning("图片描述失败：%s", desc[:200])
        if not descs:
            return ""
        if len(images) > 3:
            descs.append(f"（还有 {len(images) - 3} 张没看）")
        return "；".join(descs)

    async def _reply(self, session, msg_type, group_id, user_id, text, split=False):
        text = strip_emoji(text)
        text = strip_inner_thoughts(text)
        if not text:
            return
        # 语音条：仅熟人 + 长难句 + 低概率，发语音代替文字
        if split and self._should_voice(text, user_id):
            if await voice.send_voice(self.cfg, self.ob, session, msg_type, group_id, user_id, text):
                self.store.add_message(session, "assistant", self.cfg.bot_qq, group_id, text)
                logging.info("语音条 %s：%s", session, text)
                return
        if user_id:
            key = f"{session}|{user_id}"
            if any(p in text for p in _END_PHRASES):
                self._last_reply.pop(key, None)
                self._conv_end[key] = time.time() + self.cfg.conv_end_cooldown
                logging.info("结束话题（冷却 %ss）", self.cfg.conv_end_cooldown)
            else:
                self._last_reply[key] = time.time()
        # 她自己说要睡觉 → 真休眠（只有你同学能叫醒，其他人无法互动）
        if self.cfg.sleep_enabled and self.sleep.state == "awake" and any(p in text for p in _SELF_SLEEP):
            self.sleep.enter_sleep(time.time())
            logging.info("她自己说要睡觉，进入休眠")
        segments = split_sentences(text) if split else [text]
        extra = 0.0
        if split and len(segments) > 1:
            # 连发：交给独立任务，中间有打字延迟，可被新消息打断
            self._cancel_burst(self._talk_key(session, user_id))
            self._bursts[self._talk_key(session, user_id)] = asyncio.create_task(
                self._send_burst(session, msg_type, group_id, user_id, segments, extra_delay=extra)
            )
        else:
            if split:
                await asyncio.sleep(
                    extra + min(4.5, max(1.0, 0.7 + len(text) * 0.08)) * random.uniform(0.8, 1.3)
                )
            else:
                await asyncio.sleep(0.5)
            await self._send_segment(session, msg_type, group_id, user_id, segments[0])

    def _should_voice(self, text, user_id):
        """语音条触发：仅熟人（熟悉度>=2 或好感度>=2），仅长句，低概率"""
        if not user_id or not self.cfg.sf_api_key or not self.cfg.voice_model:
            return False
        if len(text) < self.cfg.voice_min_len:
            return False
        profile = self.store.get_user(user_id) if user_id else None
        if not profile:
            return False
        if familiarity_stage(profile) < self.cfg.voice_min_stage and profile["relationship"] < 2:
            return False
        return random.random() < self.cfg.voice_prob

    def _cancel_burst(self, session):
        task = self._bursts.pop(session, None)
        if task and not task.done():
            task.cancel()
            logging.info("连发被打断 session=%s", session)

    @staticmethod
    def _talk_key(session, user_id):
        """会话内按人隔离：群里别人说话不打断正在回复的人。"""
        return f"{session}|{user_id}" if user_id else session

    def _self_at(self, text):
        """把别人 @ 自己的 QQ 号显示成 @我，避免她问'这是谁'。"""
        return str(text or "").replace(f"@{self.cfg.bot_qq}", "@我")

    async def _send_burst(self, session, msg_type, group_id, user_id, segments, extra_delay=0.0):
        try:
            # 第一条之前的打字延迟
            await asyncio.sleep(
                extra_delay + min(4.5, max(1.0, 0.7 + sum(len(s) for s in segments) * 0.06))
                * random.uniform(0.8, 1.3)
            )
            for i, seg in enumerate(segments):
                await self._send_segment(session, msg_type, group_id, user_id, seg)
                if i < len(segments) - 1:
                    # 每条之间的打字延迟（按本条字数）
                    await asyncio.sleep(
                        min(3.0, max(0.8, 0.6 + len(seg) * 0.08)) * random.uniform(0.8, 1.3)
                    )
        except asyncio.CancelledError:
            logging.info("连发剩余片段已取消 session=%s", session)
            raise
        finally:
            key = f"{session}|{user_id}" if user_id else session
            if self._bursts.get(key) is asyncio.current_task():
                self._bursts.pop(key, None)

    async def _send_segment(self, session, msg_type, group_id, user_id, seg):
        if msg_type == "group":
            resp = await self.ob.action("send_group_msg", {"group_id": group_id, "message": seg})
        else:
            resp = await self.ob.action("send_private_msg", {"user_id": user_id, "message": seg})
        if isinstance(resp, dict) and resp.get("message_id"):
            self._sent_ids[str(resp["message_id"])] = time.time()
        if len(self._sent_ids) > 500:
            cutoff = time.time() - 3600
            self._sent_ids = {k: v for k, v in self._sent_ids.items() if v > cutoff}
        self.store.add_message(session, "assistant", self.cfg.bot_qq, group_id, seg)
        self._publish_reply(session, seg)
        logging.info("回复 %s：%s", session, seg)
        if msg_type == "group":
            self._last_group_reply[group_id] = time.time()

    def _publish_reply(self, session, text):
        """把最终回复文本放进会话队列（微信桥等待取回）。"""
        q = self._reply_queues.get(session)
        if q is not None:
            try:
                q.put_nowait(text)
            except Exception:  # noqa: BLE001
                pass

    async def wait_for_reply(self, session, timeout=180):
        """等待 agent 对某会话生成回复（微信桥用），超时返回空串。"""
        q = self._reply_queues.setdefault(session, asyncio.Queue())
        try:
            return await asyncio.wait_for(q.get(), timeout)
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            return ""

    def _tool_exec(self, ctx):
        async def exec_tool(name, args):
            sid = getattr(ctx, "session_key", "") or ""
            start = time.time()
            ok, err = True, ""
            try:
                result = await self.tools.call(name, args, ctx)
            except Exception as e:  # noqa: BLE001
                ok, err = False, str(e)
                raise
            finally:
                try:
                    self._pending_tools.setdefault(sid, []).append({
                        "name": name,
                        "args": args,
                        "ok": ok,
                        "error": err,
                        "ms": int((time.time() - start) * 1000),
                    })
                except Exception:  # noqa: BLE001
                    pass
            return result
        return exec_tool

    async def daily_minimum_loop(self):
        """确保每个活跃群每天至少发言一次"""
        while True:
            await asyncio.sleep(1800)
            if self.sleep.state != "awake":
                continue
            for gid in self.cfg.groups:
                last = self._last_group_reply.get(gid)
                if last and time.time() - last > self.cfg.min_daily_hours * 3600:
                    logging.info("每日保底发言触发 group=%s", gid)
                    await self._maybe_interject(gid, f"g:{gid}", forced=True)

    async def _compose(self, instruction, state_desc=""):
        """让大脑单独写一条消息（早安/晚安/主动私聊用）"""
        gid = self.cfg.groups[0] if self.cfg.groups else ""
        system = build_system(self.cfg, self.store, self.cfg.owner_qq, gid, state_desc)
        ctx = Ctx(cfg=self.cfg, store=self.store, ob=self.ob, sender_qq=self.cfg.owner_qq, group_id=gid)
        reply = await self.brain.think(system, [], instruction, self.tools.schemas, self._tool_exec(ctx))
        if reply and reply.strip() not in ("沉默", "沉默。", "（沉默）"):
            return reply
        return ""

    async def _compose_reminder(self, r):
        """定时提醒到点：让大脑按当前人设组织提醒话术，不套固定模板。"""
        text = str(r.get("text") or "").strip()
        due = str(r.get("due_ts") or "")
        return await self._compose(
            f"[现在时间：{self.cfg.now_str()}] 定时提醒到点了"
            + (f"（原定时间戳 {due}）" if due else "")
            + f"。提醒内容：{text}\n"
            "用你的口吻向对方提醒这件事，简短自然，一两句，"
            "不要说‘这是定时任务/系统提醒’这类话。",
            "定时提醒到点",
        )

    async def _confirm(self, action_desc):
        """让 AI 现场编一句执行确认（避免固定词库感），失败才用兜底语"""
        return await self._say(
            f"[现在时间：{self.cfg.now_str()}] 你刚执行了：{action_desc}。向你同学简短确认一句，自然点，一两句"
        )

    async def _say(self, instruction):
        """让 AI 现场编一句话（无工具），失败返回空串"""
        gid = self.cfg.groups[0] if self.cfg.groups else ""
        system = build_system(self.cfg, self.store, self.cfg.owner_qq, gid)
        reply = await self.brain.think(
            system, [],
            instruction,
            [], lambda name, args: "ok",
        )
        if reply and reply.strip() not in ("沉默", "沉默。", "（沉默）"):
            return reply
        return ""

    async def _on_wake(self, greet):
        self.sleep.greeted = True
        if not greet or not self.cfg.groups:
            return
        word = {"morning": "早安", "noon": "午安", "afternoon": "下午好"}.get(greet, "问候")
        text = await self._compose(
            f"[现在时间：{self.cfg.now_str()}] 你刚睡醒，给群友发一条{word}问候，简短自然，一两句就行",
            "你刚睡醒，还有点迷糊",
        )
        if not text:
            return
        gid = self.cfg.groups[0]
        await self._reply(f"g:{gid}", "group", gid, "", text, split=True)
        if random.random() < self.cfg.greeting_private_chance:
            await self._reply(f"p:{self.cfg.owner_qq}", "private", "", self.cfg.owner_qq, text, split=True)
        logging.info("已发送%s问候：%s", word, text)

    async def _on_bedtime(self):
        now = time.time()
        # 睡前写今日日记（明天醒来能想起）
        try:
            day = self.cfg.today()
            day_start = int(self.cfg.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            rows = self.store.messages_today(day_start, 40)
            if rows:
                transcript = "\n".join(
                    f"{self.cfg.persona_name if r['role'] == 'assistant' else r['qq']}: {r['text']}"
                    for r in reversed(rows)
                )
                diary = await self._compose(
                    f"[现在时间：{self.cfg.now_str()}] 你准备睡觉了。今天发生的事：\n{transcript}\n\n"
                    "写一小段今天的日记（3~5 句，像朋友圈，带点情绪和真实细节，不要总结报告腔），"
                    "明天醒来你会看到它。"
                )
                if diary:
                    self.store.save_diary(day, diary)
                    logging.info("今日日记已保存 %s", day)
        except Exception:  # noqa: BLE001
            logging.exception("写日记失败")
        self.sleep.enter_sleep(now)
        text = await self._compose(
            f"[现在时间：{self.cfg.now_str()}] 你准备睡觉了，跟群友说声晚安，简短自然",
            "你困了，准备睡觉",
        )
        if text and self.cfg.groups:
            gid = self.cfg.groups[0]
            await self._reply(f"g:{gid}", "group", gid, "", text, split=True)
            if random.random() < self.cfg.greeting_private_chance:
                await self._reply(f"p:{self.cfg.owner_qq}", "private", "", self.cfg.owner_qq, text, split=True)
        logging.info("已入睡")

    async def life_loop(self):
        """睡眠心跳：入睡 / 自然醒 / 强制清醒结束"""
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                event, greet = self.sleep.tick(now)
                if event == "woke":
                    await self._on_wake(greet)
                elif event == "resleep":
                    logging.info("没人理，继续睡")
                if self.sleep.should_enter_sleep(now, self._last_activity):
                    await self._on_bedtime()
            except Exception:  # noqa: BLE001
                logging.exception("life_loop 出错")

    async def _compose_outreach(self, qq):
        p = self.store.get_user(qq)
        if p:
            days = max(1, (p["last_seen"] - p["first_seen"]) // 86400 + 1)
            desc = f"QQ {qq}（认识约 {days} 天，聊过 {p['msg_count']} 条）"
        else:
            desc = f"QQ {qq}"
        history = self.store.recent_user_context(qq, f"p:{qq}", 10)
        hist_text = ""
        if history:
            hist_text = "\n".join(
                f"{self.cfg.persona_name if r['role'] == 'assistant' else r['qq']}: {r['text']}"
                for r in history
            )
        return await self._compose(
            f"[现在时间：{self.cfg.now_str()}] 你闲着没事，想找好友 {desc} 私聊一句。"
            f"你们之前聊过：\n{hist_text or '（还没有聊过）'}\n\n"
            "先看上面聊过什么：不要重复问已经问过的问题，不要重复说已经说过的话，找点新鲜的话题。"
            "自然点，像突然想起来找老朋友说话，问问近况或分享个小事，只发一条。"
            "只输出要发给对方的那一句话本身，禁止输出内心想法、备注、括号说明或'发出去了''等他回吧'这类话。"
            "不想发就回复：沉默",
            "你在主动找朋友聊天",
        )

    async def outreach_loop(self):
        """偶尔主动私聊好友；发几次不回就冻结，对方先说话才解冻"""
        while True:
            try:
                await asyncio.sleep(15 * 60)
                now = time.time()
                if self.sleep.state != "awake":
                    continue
                if random.random() > self.cfg.outreach_chance:
                    continue
                # 处理超时未回：未回 +1，冻结判定在下面
                done = set()
                for row in self.store.outreach_rows():
                    qq, last_ts, unanswered = row["qq"], row["last_ts"], row["unanswered"]
                    if last_ts and now - last_ts > self.cfg.outreach_reply_window_h * 3600:
                        self.store.set_outreach(qq, 0, unanswered + 1)
                        done.add(qq)
                        logging.info("外联未回 unanswered=%s qq=%s", unanswered + 1, qq)
                # 挑选一位候选人
                for row in self.store.outreach_candidates():
                    qq = row["qq"]
                    if qq in done or qq == self.cfg.bot_qq:
                        continue
                    o = self.store.get_outreach(qq)
                    if o and o["unanswered"] >= self.cfg.outreach_max_unanswered:
                        continue  # 冻结
                    if o and o["last_ts"] and now - o["last_ts"] < self.cfg.outreach_min_interval_h * 3600:
                        continue
                    text = await self._compose_outreach(qq)
                    if text:
                        await self._reply(f"p:{qq}", "private", "", qq, text, split=True)
                        self.store.set_outreach(qq, int(now), o["unanswered"] if o else 0)
                        logging.info("主动私聊 qq=%s：%s", qq, text)
                    break  # 每轮最多一个
            except Exception:  # noqa: BLE001
                logging.exception("outreach_loop 出错")

    # ---- 记忆自动沉淀：定期把聊天里的重点提炼成长期记忆 ----
    async def memory_loop(self):
        """每 25 分钟：扫描最近的聊天，把值得记住的事（生日/喜好/大事）自动存进记忆"""
        while True:
            await asyncio.sleep(25 * 60)
            try:
                cutoff = int(time.time()) - 4 * 3600
                for qq in self.store.user_ids_since(cutoff):
                    last = self._mem_scan.get(qq, cutoff)
                    rows = self.store.messages_since(qq, last, 50)
                    if not rows:
                        continue
                    self._mem_scan[qq] = rows[-1]["ts"]
                    texts = [r["text"] for r in rows if r["text"] and r["text"] != "[图片]"]
                    if len(texts) < 3:
                        continue
                    facts = await self._extract_facts(qq, texts[-25:])
                    for f in facts:
                        if self.store.remember_if_new(qq, f):
                            logging.info("自动记忆 qq=%s：%s", qq, f)
                        self._maybe_birthday(qq, f)
            except Exception:  # noqa: BLE001
                logging.exception("memory_loop 出错")

    async def _extract_facts(self, qq, texts):
        system = (
            f"你是{self.cfg.persona_name}，负责从聊天记录里提炼值得长期记住的信息。"
            "只提炼：生日、姓名/昵称、职业、学校、爱好、讨厌的事、重大事件、约定承诺。"
            "忽略寒暄和日常废话。每行一条，最多 3 条；没有值得记的就只回复：无"
        )
        user = "聊天记录：\n" + "\n".join(f"- {t}" for t in texts)
        reply = await self.brain.think(system, [], user, [], lambda n, a: "ok")
        facts = []
        for ln in (reply or "").splitlines():
            ln = ln.strip().lstrip("-•*0123456789.、 ")
            if not ln or ln in ("无", "没有", "无。"):
                continue
            if len(ln) < 4 or len(ln) > 60:
                continue
            facts.append(ln)
        return facts[:3]

    def _maybe_birthday(self, qq, fact):
        m = re.search(r"(\d{1,2})月(\d{1,2})[日号]", fact)
        if m:
            self.store.set_birthday(qq, int(m.group(1)), int(m.group(2)), fact[:40])
            logging.info("生日已记录 qq=%s：%s月%s日", qq, m.group(1), m.group(2))

    # ---- 生日祝福：每天早上 9~11 点，谁今天生日就送祝福 ----
    async def birthday_loop(self):
        while True:
            await asyncio.sleep(6 * 3600)
            try:
                now = self.cfg.now()
                if now.hour not in (9, 10, 11):
                    continue
                for row in self.store.birthdays_due(now.month, now.day):
                    qq = row["qq"]
                    key = f"bday_{qq}_{now.year}"
                    if self.store.get_setting(key, ""):
                        continue
                    name = ""
                    u = self.store.get_user(qq)
                    if u and u["nickname"]:
                        name = u["nickname"]
                    text = await self._compose(
                        f"[现在时间：{self.cfg.now_str()}] 今天是 QQ {qq}{('（' + name + '）') if name else ''} 的生日"
                        f"（TA说过：{row['note'] or '生日'}）。给 TA 发一条生日祝福，简短自然真诚，别太肉麻，一两句"
                    )
                    if text and self.cfg.groups:
                        gid = self.cfg.groups[0]
                        await self._reply(f"g:{gid}", "group", gid, "", text, split=True)
                        logging.info("生日祝福已发 qq=%s", qq)
                    self.store.set_setting(key, "1")
            except Exception:  # noqa: BLE001
                logging.exception("birthday_loop 出错")

    # ---- 群管：你同学规则确定性执行 + 入群审批 ----
    @staticmethod
    def _has_url(text):
        return bool(_URL_RE.search(text))

    @staticmethod
    def _parse_mute_minutes(text, now=None):
        """解析禁言时长（分钟）。支持：N分钟/N小时/N天、明天早上10点/今晚8点/下午3点等。
        解析不到返回 None，由调用方用默认值兜底。"""
        import datetime as _dt

        t = text or ""
        m = re.search(r"(\d+|[一二两三四五六七八九十半]+)\s*个?\s*(天|小时|钟头|分钟|分)", t)
        if m:
            raw = m.group(1)
            n = int(raw) if raw.isdigit() else _cn_to_int(raw)
            unit = m.group(2)
            if unit == "天":
                return int(n * 1440)
            if unit in ("小时", "钟头"):
                return int(n * 60)
            return max(1, int(n))
        m = re.search(
            r"(今天|今晚|明天|明早|明晚|后天)?\s*"
            r"(凌晨|早上|上午|中午|下午|晚上)?\s*"
            r"(\d{1,2})\s*点\s*(半)?",
            t,
        )
        if m:
            day, period, hour_s, half = m.groups()
            dt_now = _dt.datetime.fromtimestamp(now if now is not None else time.time())
            day_add = {"明天": 1, "明早": 1, "明晚": 1, "后天": 2}.get(day or "", 0)
            hour = int(hour_s)
            if period in ("下午", "晚上") and hour < 12:
                hour += 12
            elif period == "中午" and hour < 11:
                hour += 12
            elif period == "凌晨" and hour >= 12:
                hour -= 12
            target = dt_now.replace(hour=hour, minute=30 if half else 0, second=0, microsecond=0)
            target += _dt.timedelta(days=day_add)
            if not day and target <= dt_now:
                target += _dt.timedelta(days=1)  # 没说哪天且时间已过 → 视为明天
            return max(1, int((target - dt_now).total_seconds() // 60))
        return None

    async def _parse_mute_command(self, session, group_id, text, data):
        """确定性禁言命令：全员禁言 / 禁言@某人 / 解禁。返回 True 表示已处理"""
        gid = group_id or str(data.get("group_id", ""))
        if not gid or (self.cfg.groups and gid not in self.cfg.groups):
            return False

        uid = str(data.get("user_id") or self.cfg.owner_qq)
        minutes = self._parse_mute_minutes(text) or 5
        all_mode = "全员禁言" in text or "禁言所有人" in text or "禁言全群" in text
        minutes = max(1, min(minutes, self.cfg.mute_all_max_minutes if all_mode else self.cfg.mute_max_minutes))

        # 命令意图判定：禁言必须紧贴 @ 目标（"禁言@某人"/"@某人禁言"/"把@某人禁言"），
        # 聊天里只是提到"禁言"不算命令，防止乱禁人
        marked = ""
        at_map = {}
        for s in data.get("message", []) or []:
            if isinstance(s, dict) and s.get("type") == "at":
                at_map[len(marked)] = str(s.get("data", {}).get("qq", ""))
                marked += "@"
            elif isinstance(s, dict):
                marked += str(s.get("data", {}).get("text", "") or "")
        ban_cmd = bool(re.search(r"(禁言.{0,8}@|@.{0,8}禁言|把.{0,10}@.{0,12}禁言)", marked))
        # 目标取离"禁言/解禁"最近的 @（多个 @ 时不误把第一个当目标）
        kw_pos = marked.find("禁言")
        if kw_pos < 0:
            kw_pos = marked.find("解禁")
        target_qq = ""
        if kw_pos >= 0 and at_map:
            best = min(at_map, key=lambda p: abs(p - kw_pos))
            if abs(best - kw_pos) <= 12:
                target_qq = at_map[best]

        # 全员禁言 / 解除全员禁言
        if all_mode:
            self.store.cancel_unban(gid)
            if "解除" in text:
                resp = await self.ob.action("set_group_whole_ban", {"group_id": gid, "enable": False})
                if isinstance(resp, dict) and resp.get("error"):
                    await self._reply(session, "group", gid, uid,
                                      "官方通道还没开放全员禁言接口，这步做不了", split=True)
                    return True
                await self._reply(session, "group", gid, uid,
                                  await self._confirm("解除了全员禁言") or "好，解除全员禁言了", split=True)
                logging.info("命令：解除全员禁言")
            else:
                resp = await self.ob.action("set_group_whole_ban", {"group_id": gid, "enable": True})
                if isinstance(resp, dict) and resp.get("error"):
                    await self._reply(session, "group", gid, uid,
                                      "官方通道还没开放全员禁言接口，这步做不了", split=True)
                else:
                    self.store.add_reminder("unban", gid, "", minutes)
                    await self._reply(session, "group", gid, uid,
                                      await self._confirm(f"全员禁言 {minutes} 分钟，到点自动解除")
                                      or f"行，全员禁言 {minutes} 分钟，到点自动解除", split=True)
                    logging.info("命令：全员禁言 %s 分钟", minutes)
            return True

        # 没有 @ 的"解除/解禁" → 解除全员禁言（并清掉残留定时器）
        if ("解除" in text or "解禁" in text) and not target_qq:
            self.store.cancel_unban(gid)
            resp = await self.ob.action("set_group_whole_ban", {"group_id": gid, "enable": False})
            if isinstance(resp, dict) and resp.get("error"):
                await self._reply(session, "group", gid, uid,
                                  "官方通道还没开放全员禁言接口，这步做不了", split=True)
            else:
                await self._reply(session, "group", gid, uid,
                                  await self._confirm("解除了全员禁言") or "好，解除禁言了", split=True)
                logging.info("命令：解除全员禁言（无@）")
            return True

        if not target_qq or target_qq == self.cfg.bot_qq:
            return False
        if "解禁" in text and ban_cmd:
            await self.ob.action("set_group_ban", {"group_id": gid, "user_id": target_qq, "duration": 0})
            await self._reply(session, "group", gid, uid,
                              await self._confirm(f"给 QQ {target_qq} 解除了禁言") or "行，给他解禁了", split=True)
            logging.info("命令：解禁 %s", target_qq)
            return True
        if ban_cmd and "禁言" in text:
            role = await self._member_role(gid, target_qq)
            if role in ("owner", "admin"):
                await self._reply(session, "group", gid, uid,
                                  "群主/管理员禁不了，你换个人试试", split=False)
                logging.info("拒绝禁言群主/管理员 %s", target_qq)
                return True
            await self.ob.action("set_group_ban", {"group_id": gid, "user_id": target_qq, "duration": minutes * 60})
            await self._reply(session, "group", gid, uid,
                              await self._confirm(f"把 QQ {target_qq} 禁言了 {minutes} 分钟")
                              or f"行，把他禁了 {minutes} 分钟", split=True)
            logging.info("命令：禁言 %s %s 分钟", target_qq, minutes)
            return True
        return False

    async def _member_role(self, group_id, user_id):
        key = (group_id, user_id)
        now = time.time()
        if key in self._roles and now - self._roles[key][1] < 300:
            return self._roles[key][0]
        role = "member"
        try:
            data = await self.ob.action(
                "get_group_member_info", {"group_id": group_id, "user_id": user_id}
            )
            role = (data or {}).get("role", "member")
        except Exception:  # noqa: BLE001
            logging.warning("查询成员身份失败 group=%s user=%s", group_id, user_id)
        self._roles[key] = (role, now)
        return role

    async def _enforce_rules(self, data, text):
        """链接类规则确定性执行：非管理发链接 → 撤回/禁言"""
        if not self._has_url(text):
            return
        gid = str(data.get("group_id", ""))
        uid = str(data.get("user_id", ""))
        for r in self.store.list_rules():
            rt = r["text"]
            if "链接" not in rt or not (("禁言" in rt) or ("撤回" in rt)):
                continue
            role = str(data.get("member_role", "") or "")
            if not role:
                role = await self._member_role(gid, uid)
            if role in ("owner", "admin"):
                return
            if "撤回" in rt:
                mid = str(data.get("message_id", ""))
                if mid:
                    try:
                        await self.ob.action("delete_msg", {"message_id": mid})
                        logging.info("规则执行：撤回链接消息 mid=%s", mid)
                    except Exception as e:  # noqa: BLE001
                        logging.warning("撤回失败：%s", e)
            if "禁言" in rt:
                m = re.search(r"(\d+)\s*分钟", rt)
                minutes = min(max(int(m.group(1)), 1), self.cfg.mute_max_minutes) if m else 5
                try:
                    await self.ob.action(
                        "set_group_ban", {"group_id": gid, "user_id": uid, "duration": minutes * 60}
                    )
                    logging.info("规则执行：禁言 %s %s 分钟", uid, minutes)
                except Exception as e:  # noqa: BLE001
                    logging.warning("禁言失败：%s", e)
            return

    async def _decide_join(self, r):
        system = build_system(self.cfg, self.store, self.cfg.owner_qq, r["group_id"])
        text = (
            f"[现在时间：{self.cfg.now_str()}] 有人申请加入群 {r['group_id']}"
            f"（QQ {r['user_id']}，验证信息：{r['comment'] or '无'}）。你是群管理，判断是否同意。"
            "只回复两个字：同意 或 拒绝"
        )
        reply = await self.brain.think(system, [], text, [], lambda name, args: "ok")
        return (reply or "").startswith("同意")

    async def join_request_loop(self):
        """超过 N 小时未处理的入群申请 → AI 决策，通过则发欢迎"""
        while True:
            try:
                await asyncio.sleep(10 * 60)
                for r in self.store.pending_join_requests(self.cfg.join_request_delay_h):
                    try:
                        approve = await self._decide_join(r)
                        await self.ob.action(
                            "set_group_add_request",
                            {"flag": r["flag"], "sub_type": "add", "approve": approve,
                             "reason": "欢迎加入" if approve else "暂时不考虑"},
                        )
                        self.store.mark_join_done(r["flag"])
                        logging.info("入群申请处理 flag=%s approve=%s", r["flag"], approve)
                    except Exception as e:  # noqa: BLE001
                        logging.warning("入群审批处理失败：%s", e)
            except Exception:  # noqa: BLE001
                logging.exception("join_request_loop 出错")

    def run_tasks(self):
        """启动后台生命周期任务（NoneBot on_startup 调用）。"""
        return [
            asyncio.create_task(
                reminder_loop(self.cfg, self.store, self.ob,
                              self._compose_reminder)),
            asyncio.create_task(self.daily_minimum_loop()),
            asyncio.create_task(self.life_loop()),
            asyncio.create_task(self.outreach_loop()),
            asyncio.create_task(self.memory_loop()),
            asyncio.create_task(self.birthday_loop()),
        ]

    async def _on_member_join(self, data):
        """新成员入群欢迎（AI 现编，李清菡风格）"""
        gid = str(data.get("group_id", ""))
        uid = str(data.get("user_id", ""))
        if gid not in self.cfg.groups or uid == self.cfg.bot_qq:
            return
        if self.sleep.state != "awake":
            logging.info("休眠中，跳过入群欢迎 group=%s user=%s", gid, uid)
            return
        name = ""
        try:
            info = await self.ob.action(
                "get_group_member_info", {"group_id": gid, "user_id": uid}
            )
            if info:
                name = str(info.get("card") or info.get("nickname") or "")
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(random.uniform(2, 6))  # 真人注意到新人的节奏
        text = await self._compose(
            f"[现在时间：{self.cfg.now_str()}] 有新成员加入了群 {gid}"
            f"（QQ {uid}{('，昵称 ' + name) if name else ''}）。"
            f"发一条简短热情的欢迎消息，一两句，{self.cfg.persona_name}的风格"
            "（可以带点好奇和玩笑），别太长"
        )
        if text:
            await self._reply(f"g:{gid}", "group", gid, "", text, split=True)
            logging.info("入群欢迎 group=%s user=%s：%s", gid, uid, text)


def main():
    cfg = Config(os.path.join(BASE_DIR, ".env"))
    if not cfg.ds_api_key:
        raise SystemExit("缺少 DEEPSEEK_API_KEY，请在 .env 中配置")
    setup_logging(cfg)
    logging.info("%s Agent 启动，model=%s groups=%s",
                 cfg.persona_name, cfg.ds_model, cfg.groups)
    agent = Agent(cfg)
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()
