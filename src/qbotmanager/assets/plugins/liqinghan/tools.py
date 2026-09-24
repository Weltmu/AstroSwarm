"""工具注册表：AI 可自主调用的能力"""
import base64
import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field

import httpx

from . import games, knowledge
from .capabilities import enabled_tools


FACE_MAP = {
    "微笑": 14, "呲牙": 13, "得意": 4, "调皮": 12, "偷笑": 19, "可爱": 20,
    "害羞": 6, "疑问": 31, "发呆": 3, "委屈": 48, "大哭": 9, "惊讶": 0,
    "白眼": 21, "尴尬": 10, "擦汗": 39, "酷": 16, "呕吐": 18, "抓狂": 17,
    "发怒": 11, "闭嘴": 7, "睡觉": 8, "流泪": 5, "难过": 15, "憨笑": 27,
    "奋斗": 29, "咒骂": 30, "嘘": 32, "晕": 33, "衰": 35, "骷髅": 36,
    "敲打": 37, "再见": 38, "鼓掌": 41, "坏笑": 43, "哈欠": 46, "鄙视": 47,
    "阴险": 50, "亲亲": 51, "吓": 52, "可怜": 53, "菜刀": 54, "西瓜": 55,
    "啤酒": 56, "咖啡": 59, "猪头": 61, "玫瑰": 62, "爱心": 65, "心碎": 66,
    "蛋糕": 67,
}


@dataclass
class Ctx:
    cfg: object
    store: object
    ob: object
    sender_qq: str = ""
    sender_role: str = ""
    group_id: str = ""
    session_key: str = ""
    message_id: str = ""


def _f(name, description, params, handler):
    return (name, {"type": "function", "function": {"name": name, "description": description, "parameters": params}}, handler)


class Tools:
    def __init__(self, cfg, store, ob, source="qq:c2c"):
        self.cfg = cfg
        self.store = store
        self.ob = ob
        self.last_images = {}   # session -> 最近收到的图片 [{file,url}, ...]
        self._vision_cache = {}  # sha256|focus -> (ts, 描述)，1 小时有效
        self._all_registry = {}
        self._all_schemas = []
        self._registry = {}
        self._schemas = []
        self._register()
        self.set_source(source)

    def set_source(self, source):
        """按通道来源裁剪可用工具（QQ 群/私聊/微信不同能力）。"""
        allowed = set(enabled_tools(source, list(self._all_registry)))
        self._registry = {k: v for k, v in self._all_registry.items() if k in allowed}
        self._schemas = [s for s in self._all_schemas
                         if s["function"]["name"] in allowed]

    def _register(self):
        entries = [
            _f("get_time", "获取当前时间", {"type": "object", "properties": {}},
               lambda ctx, a: self.cfg.now_str()),
            _f("recall_message", "撤回一条消息（需要管理员权限）", {
                "type": "object",
                "properties": {"message_id": {"type": "string"}},
                "required": ["message_id"]},
               self._recall),
            _f("mute_user", "禁言某个群成员（你有管理员权限，user_id 是对方的QQ号，分钟数自己判断，别超上限）", {
                "type": "object",
                "properties": {"group_id": {"type": "string"}, "user_id": {"type": "string"},
                               "minutes": {"type": "integer", "minimum": 1}},
                "required": ["group_id", "user_id", "minutes"]},
               self._mute),
            _f("mute_all", "全员禁言整个群（你有管理员权限），minutes 分钟后自动解除；只有你同学下达时执行", {
                "type": "object",
                "properties": {"group_id": {"type": "string"}, "minutes": {"type": "integer", "minimum": 1}},
                "required": ["minutes"]},
               self._mute_all),
            _f("read_recent_history", "读取当前会话最近的聊天记录（用于理解上下文）", {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "读多少条，默认20"}}},
               self._history),
            _f("set_reminder", "设置提醒，到点会主动发消息提醒", {
                "type": "object",
                "properties": {"minutes": {"type": "integer", "description": "几分钟后"},
                               "text": {"type": "string", "description": "提醒内容"}},
                "required": ["minutes", "text"]},
               self._remind),
            _f("add_rule", "你同学立规矩：新增一条长期生效的群规则（仅你同学可用）", {
                "type": "object",
                "properties": {"text": {"type": "string"}, "scope": {"type": "string", "enum": ["all", "group", "private"]}},
                "required": ["text"]},
               self._add_rule),
            _f("list_rules", "查看当前生效的所有规则", {"type": "object", "properties": {}},
               self._list_rules),
            _f("remove_rule", "删除一条规则（仅你同学可用）", {
                "type": "object", "properties": {"rule_id": {"type": "integer"}}, "required": ["rule_id"]},
               self._remove_rule),
            _f("checkin", "帮用户完成每日签到赚金币", {"type": "object", "properties": {}},
               lambda ctx, a: self.store.checkin(ctx.sender_qq, self.cfg.today())[2]),
            _f("work", "帮用户打工赚金币（有冷却）", {"type": "object", "properties": {}},
               lambda ctx, a: self.store.work(ctx.sender_qq, self.cfg.work_cooldown_sec)[2]),
            _f("balance", "查询用户金币余额", {"type": "object", "properties": {}},
               lambda ctx, a: f"当前金币余额：{self.store.balance(ctx.sender_qq)}"),
            _f("leaderboard", "查看金币排行榜", {"type": "object", "properties": {}},
               self._leaderboard),
            _f("get_user_profile", "查看某个用户的认识时长与聊天统计", {
                "type": "object", "properties": {"qq": {"type": "string"}}, "required": ["qq"]},
               self._profile),
            _f("set_relationship", "你同学调整对某人的好感度（-10 讨厌 ~ 10 喜欢）", {
                "type": "object",
                "properties": {"qq": {"type": "string"}, "score": {"type": "integer", "minimum": -10, "maximum": 10}},
                "required": ["qq", "score"]},
               self._set_relationship),
            _f("remember", "记住关于某人的一件事（长期记忆，以后聊天能回忆起来）", {
                "type": "object", "properties": {"fact": {"type": "string"}}, "required": ["fact"]},
               self._remember),
            _f("recall", "回忆某人让我记住的事情", {"type": "object", "properties": {}},
               self._recall),
            _f("adjust_anger", "调整对某人的愤怒值（-100~100，负值=消气/原谅，正值=被惹毛更生气）", {
                "type": "object",
                "properties": {"delta": {"type": "integer", "minimum": -100, "maximum": 100}},
                "required": ["delta"]},
               self._adjust_anger),
            _f("product_faq", "查询 AstroSwarm（星群）产品知识库，回答产品相关问题（功能/价格/安装/激活/平台/模型/故障/客服）", {
                "type": "object",
                "properties": {"question": {"type": "string", "description": "客户问的问题"}},
                "required": ["question"]},
               self._product_faq),
            _f("describe_image", "看一张图片并返回它的文字描述（对方刚发的图可直接调用，不用传参数；也可以传 file 指定图片本地路径或网址，focus 指定重点看什么）", {
                "type": "object",
                "properties": {
                    "file": {"type": "string", "description": "图片本地路径或 http(s) 链接，不填则看当前会话最近一张图"},
                    "focus": {"type": "string", "description": "重点看什么，比如'图中文字''人物表情''整体内容'"},
                }},
               self._describe_image),
            _f("start_game", "在群里开一个小游戏当主持（猜数字 number / 谜语 riddle / 石头剪刀布 rps），自己出题、自己当裁判；hint 是题目或开场白，answer 是答案（number/riddle 必须给），reward 是金币奖励", {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["number", "riddle", "rps"]},
                    "hint": {"type": "string", "description": "题目/开场白，比如谜面或'我脑子里想了个1~100的数字'"},
                    "answer": {"type": "string", "description": "答案（猜数字填数字，谜语填谜底；石头剪刀布不用填）"},
                    "reward": {"type": "integer", "description": "猜对奖励多少金币，默认10"},
                },
                "required": ["kind", "hint"]},
               self._start_game),
            _f("game_guess", "代群友提交一次游戏作答，返回判定结果（答对会发金币）", {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "群友的原话/答案"}},
                "required": ["text"]},
               self._game_guess),
            _f("game_end", "提前结束当前进行中的游戏", {"type": "object", "properties": {}},
               self._game_end),
            _f("game_state", "查看当前群里进行中的游戏状态", {"type": "object", "properties": {}},
               self._game_state),
            _f("send_face", "在当前会话发一个 QQ 表情，name 从预置表情里选一个最贴合语气的", {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "表情名：" + "、".join(FACE_MAP.keys())},
                },
                "required": ["name"]},
               self._send_face),
            _f("generate_image", "生成一张图片并发到当前会话（比如拼豆成品图、风景、表情包），prompt 写清画面内容", {
                "type": "object",
                "properties": {"prompt": {"type": "string", "description": "画面描述，越具体越好（主体/风格/氛围）"}},
                "required": ["prompt"]},
               self._generate_image),
        ]
        for name, schema, handler in entries:
            self._all_registry[name] = handler
            self._all_schemas.append(schema)

    @property
    def schemas(self):
        return self._schemas

    async def call(self, name, args, ctx):
        handler = self._registry.get(name)
        if handler is None:
            return f"未知工具 {name}"
        try:
            if hasattr(handler, "__call__"):
                result = handler(ctx, args)
                if hasattr(result, "__await__"):
                    result = await result
                return str(result)
            return str(handler)
        except Exception as e:  # noqa: BLE001
            logging.exception("工具 %s 执行失败", name)
            return f"工具执行失败：{e}"

    # ---- 实现 ----
    async def _recall(self, ctx, a):
        mid = str(a.get("message_id") or ctx.message_id)
        if not mid:
            return "没有可撤回的消息 id"
        await self.ob.action("delete_msg", {"message_id": int(mid)})
        return "已撤回"

    async def _mute(self, ctx, a):
        minutes = max(1, min(int(a.get("minutes", 1)), self.cfg.mute_max_minutes))
        gid = a.get("group_id") or ctx.group_id
        if not gid:
            return "（禁言需要群 ID）"
        if not await self._can_mute(ctx, gid):
            return "（禁言只有你同学或群主/管理员能下令）"
        target = str(a.get("user_id") or "").strip()
        if not target:
            return "（禁言缺少目标 QQ）"
        if target == ctx.sender_qq:
            return "（不能禁言自己）"
        target_role = await self._member_role(ctx, gid, target)
        if target_role in ("owner", "admin"):
            return "（群主/管理员禁不了，换普通成员吧）"
        await self.ob.action(
            "set_group_ban",
            {"group_id": int(gid), "user_id": int(target), "duration": minutes * 60},
        )
        return f"已禁言 {minutes} 分钟"

    async def _member_role(self, ctx, group_id, user_id):
        """查群成员身份，失败默认 member。"""
        try:
            data = await self.ob.action(
                "get_group_member_info", {"group_id": int(group_id), "user_id": int(user_id)}
            )
            return str((data or {}).get("role", "member"))
        except Exception:  # noqa: BLE001
            return "member"

    async def _can_mute(self, ctx, gid):
        """只有你同学或群主/管理员可以下令禁言。"""
        if ctx.sender_qq == self.cfg.owner_qq:
            return True
        if ctx.sender_role in ("owner", "admin"):
            return True
        role = await self._member_role(ctx, gid, ctx.sender_qq)
        return role in ("owner", "admin")

    async def _mute_all(self, ctx, a):
        if ctx.sender_qq != self.cfg.owner_qq:
            return "只有你同学能全员禁言"
        gid = a.get("group_id") or ctx.group_id
        minutes = max(1, min(int(a.get("minutes", 5)), self.cfg.mute_all_max_minutes))
        await self.ob.action("set_group_whole_ban", {"group_id": int(gid), "enable": True})
        self.store.add_reminder("unban", gid, "", minutes)
        return f"已全员禁言 {minutes} 分钟，到点自动解除"

    async def _history(self, ctx, a):
        rows = self.store.recent_messages(ctx.session_key, min(int(a.get("limit", 20)), 30))
        if not rows:
            return "（暂无聊天记录）"
        return "\n".join(f"{r['role']}: {r['text']}" for r in rows)

    async def _remind(self, ctx, a):
        kind = "group" if ctx.group_id else "private"
        target = ctx.group_id or ctx.sender_qq
        minutes = max(1, int(a.get("minutes", 1)))
        text = str(a.get("text") or "").strip()
        rid = self.store.add_reminder(kind, target, text, minutes)
        return json.dumps({
            "ok": True,
            "reminder_id": str(rid or ""),
            "kind": kind,
            "minutes": minutes,
            "text": text,
            "target": target,
            "remind_at": time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(time.time() + minutes * 60)),
        }, ensure_ascii=False)

    async def _add_rule(self, ctx, a):
        if ctx.sender_qq != self.cfg.owner_qq:
            return "只有你同学能立规矩哦"
        rid = self.store.add_rule(ctx.sender_qq, a.get("text", ""), a.get("scope", "all"))
        return f"记住了，新规则已生效（id={rid}）：{a.get('text')}"

    async def _list_rules(self, ctx, a):
        rules = self.store.list_rules()
        if not rules:
            return "（暂无规则）"
        return "\n".join(f"{r['id']}. {r['text']}（{r['scope']}）" for r in rules)

    async def _remove_rule(self, ctx, a):
        if ctx.sender_qq != self.cfg.owner_qq:
            return "只有你同学能删规则"
        self.store.remove_rule(int(a["rule_id"]))
        return "规则已删除"

    async def _leaderboard(self, ctx, a):
        rows = self.store.leaderboard(5)
        if not rows:
            return "（还没有人赚到金币）"
        return "\n".join(f"{i+1}. QQ {r['qq']}：{r['balance']} 金币" for i, r in enumerate(rows))

    async def _profile(self, ctx, a):
        p = self.store.get_user(str(a.get("qq", ctx.sender_qq)))
        if not p:
            return "（还没有这个用户的档案）"
        days = max(1, (p["last_seen"] - p["first_seen"]) // 86400 + 1)
        return f"QQ {p['qq']}：认识约 {days} 天，共聊 {p['msg_count']} 条，好感度 {p['relationship']}"

    async def _set_relationship(self, ctx, a):
        if ctx.sender_qq != self.cfg.owner_qq:
            return "只有你同学能改好感度"
        qq = str(a.get("qq", ""))
        score = max(-10, min(10, int(a.get("score", 0))))
        self.store.set_relationship(qq, score)
        return f"好感度已设置：QQ {qq} → {score}"

    async def _remember(self, ctx, a):
        fact = a.get("fact", "").strip()
        if not fact:
            return "没记下，内容为空"
        self.store.remember(ctx.sender_qq, fact)
        return f"记住了：{fact}"

    async def _recall(self, ctx, a):
        rows = self.store.memories_for(ctx.sender_qq, 10)
        if not rows:
            return "（还没有关于你的记忆）"
        return "、".join(f"'{m['fact']}'" for m in rows)

    async def _adjust_anger(self, ctx, a):
        delta = max(-100, min(100, int(a.get("delta", 0))))
        new = self.store.adjust_anger(ctx.sender_qq, delta)
        return f"愤怒值已调整 {delta:+d}，当前 {new}/100"

    async def _product_faq(self, ctx, a):
        return knowledge.search_faq(a.get("question", ""))

    # ---- 小游戏 ----
    async def _start_game(self, ctx, a):
        if not ctx.group_id:
            return "游戏只能在群里玩哦"
        kind = str(a.get("kind") or "riddle").strip()
        if kind not in ("number", "riddle", "rps"):
            kind = "riddle"
        hint = str(a.get("hint") or "").strip()
        answer = str(a.get("answer") or "").strip()
        reward = max(1, min(int(a.get("reward") or 10), 50))
        if kind in ("number", "riddle") and not answer:
            return "（谜语/猜数字需要先告诉我答案，我才好当裁判）"
        games.start(self.store, ctx.group_id, kind, hint, answer, reward)
        return (
            f"游戏已开始（{kind}），答案我已经记下，猜对奖励 {reward} 金币。"
            f"现在向群友宣布开始并说出题目/规则：{hint or ''}"
        )

    async def _game_guess(self, ctx, a):
        text = str(a.get("text") or "").strip()
        if not ctx.group_id:
            return "游戏只能在群里玩哦"
        s, outcome, extra = games.submit(self.store, ctx.group_id, ctx.sender_qq, text)
        if s is None:
            return "（当前没有进行中的游戏）"
        if outcome is None:
            return "（这不像游戏答案哦，别乱发）"
        if outcome == "win":
            return f"回答正确！答案是 {extra[0]}，{extra[1]} 金币已到账。"
        if outcome == "hint":
            return f"猜错了，答案更{extra[0]}（已猜错 {extra[1]} 次）。"
        if outcome == "miss":
            return f"没猜对（已错 {extra[1]} 次），可以再想想。"
        if outcome == "rps":
            c = {"rock": "石头", "scissors": "剪刀", "paper": "布"}
            if extra[2] == "win":
                return f"TA 出{c[extra[0]]}，你出{c[extra[1]]}，TA 赢了，奖励 {extra[3]} 金币。"
            if extra[2] == "draw":
                return f"TA 出{c[extra[0]]}，你出{c[extra[1]]}，平手。"
            return f"TA 出{c[extra[0]]}，你出{c[extra[1]]}，TA 输了。"
        return "（游戏状态异常）"

    async def _game_end(self, ctx, a):
        if ctx.group_id:
            games.clear(self.store, ctx.group_id)
        return "游戏已结束，向大家宣布结果吧"

    async def _game_state(self, ctx, a):
        if not ctx.group_id:
            return "（当前没有进行中的游戏）"
        s = games.get(self.store, ctx.group_id)
        if not s:
            return "（当前没有进行中的游戏）"
        return (
            f"当前游戏：{s.get('kind')}；题目/开场：{s.get('hint') or '（无）'}；"
            f"已猜错 {s.get('hits', 0)} 次；奖励 {s.get('reward')} 金币"
        )

    # ---- 表情 / 发图 ----
    async def _send_face(self, ctx, a):
        name = str(a.get("name") or "").strip()
        fid = FACE_MAP.get(name)
        if fid is None:
            return f"（没有这个表情：{name}，可选：" + "、".join(list(FACE_MAP.keys())[:12]) + " 等）"
        seg = [{"type": "face", "data": {"id": fid}}]
        if ctx.group_id:
            await self.ob.action("send_group_msg", {"group_id": int(ctx.group_id), "message": seg})
        else:
            await self.ob.action("send_private_msg", {"user_id": int(ctx.sender_qq), "message": seg})
        self.store.add_message(ctx.session_key, "assistant", self.cfg.bot_qq, ctx.group_id, f"[表情：{name}]")
        return f"已发出表情：{name}"

    async def _generate_image(self, ctx, a):
        prompt = str(a.get("prompt") or "").strip()
        if not prompt:
            return "（画图需要描述，告诉我画什么）"
        if not self.cfg.sf_api_key:
            return "（图片生成未配置）"
        payload = {
            "model": self.cfg.image_model,
            "prompt": prompt,
            "image_size": "1024x1024",
            "batch_size": 1,
            "num_inference_steps": 25,
            "seed": random.randint(1, 999999),
        }
        headers = {"Authorization": f"Bearer {self.cfg.sf_api_key}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=150) as client:
                r = await client.post(
                    "https://api.siliconflow.cn/v1/images/generations", headers=headers, json=payload
                )
                r.raise_for_status()
                url = r.json()["data"][0]["url"]
                img = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                img.raise_for_status()
                data = img.content
        except Exception as e:  # noqa: BLE001
            return f"（生成图片失败：{e}）"
        gen_dir = os.path.join(self.cfg.data_dir, "generated")
        os.makedirs(gen_dir, exist_ok=True)
        path = os.path.join(gen_dir, f"gen_{int(time.time())}.png")
        with open(path, "wb") as f:
            f.write(data)
        seg = [{"type": "image", "data": {"file": path}}]
        if ctx.group_id:
            await self.ob.action("send_group_msg", {"group_id": int(ctx.group_id), "message": seg})
        else:
            await self.ob.action("send_private_msg", {"user_id": int(ctx.sender_qq), "message": seg})
        self.store.add_message(ctx.session_key, "assistant", self.cfg.bot_qq, ctx.group_id, "[发了张图]")
        return "图片已生成并发到会话里了"

    # ---- 看图（SiliconFlow Omni-Instruct → 文字描述，给 DeepSeek 当眼睛）----
    @staticmethod
    def _sniff_mime(b):
        if b[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return "image/png"
        if b[:6] in (b"GIF87a", b"GIF89a"):
            return "image/gif"
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            return "image/webp"
        if b[:2] == b"BM":
            return "image/bmp"
        return None    # 认不出的内容一律拒绝（原先回退 image/jpeg = 任意文件都能外泄）

    # ⚠️ 安全边界：本地图片只允许从白名单目录读；网络图片不跟随跳转、逐跳校验、边下边限长
    _IMAGE_HARD_LIMIT = 32 * 1024 * 1024
    _image_miss_warned = False

    def _image_allow_dirs(self):
        dirs = ["~/.config/QQ/NapCat/temp", "~/NapCat/temp"]
        extra = getattr(self.cfg, "vision_allow_dirs", None)
        if isinstance(extra, (list, tuple)):
            dirs.extend(str(d) for d in extra if str(d).strip())
        dirs.extend(p for p in os.environ.get("QBM_VISION_ALLOW_DIRS", "").split(os.pathsep) if p.strip())
        return tuple(os.path.expanduser(d) for d in dirs)

    def _local_image_allowed(self, path):
        try:
            real = os.path.realpath(path)          # 解析符号链接，防绕过
        except OSError:
            return False
        for base in self._image_allow_dirs():
            base_real = os.path.realpath(base)
            if real == base_real or real.startswith(base_real.rstrip(os.sep) + os.sep):
                return True
        return False

    @staticmethod
    def _url_host_blocked(host):
        """只放行真正的外网地址：拦回环 / 内网 / 链路本地（含云元数据 169.254.169.254）"""
        import ipaddress
        import socket
        h = (host or "").strip().strip("[]").lower()
        if not h or h == "localhost" or h.endswith((".localhost", ".local", ".internal", ".lan")):
            return True
        try:
            infos = socket.getaddrinfo(h, None, proto=socket.IPPROTO_TCP)
        except OSError:
            return True                            # 解析不了就当不可信
        if not infos:
            return True
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                return True
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                return True
            if ip.version == 4 and ip in ipaddress.ip_network("100.64.0.0/10"):   # 运营商级 NAT
                return True
        return False

    @staticmethod
    def _too_big(limit):
        if limit >= 1024 * 1024:
            return "图片太大（超过 %dMB）" % max(1, limit // (1024 * 1024))
        return "图片太大（超过 %dKB）" % max(1, limit // 1024)

    async def _fetch_image_url(self, url, headers, limit):
        """下载网络图片：不跟随跳转 + 每跳都校验主机 + 边下边限长（原实现 follow_redirects=True 且先收完再判大小）"""
        cur = str(url)
        async with httpx.AsyncClient(timeout=self.cfg.vision_timeout, follow_redirects=False) as client:
            for _ in range(4):                     # 最多跟 3 跳
                u = httpx.URL(cur)
                if u.scheme not in ("http", "https") or u.userinfo:
                    return None, "图片地址不受支持"
                if self._url_host_blocked(u.host):
                    return None, "图片地址指向内网，已拒绝"
                async with client.stream("GET", cur, headers=headers) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("location") or ""
                        if not loc:
                            return None, "图片地址跳转异常"
                        cur = str(u.join(loc))
                        continue
                    r.raise_for_status()
                    buf = bytearray()
                    async for chunk in r.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > limit:
                            return None, self._too_big(limit)
                    return bytes(buf), ""
        return None, "图片地址跳转次数过多"

    async def _load_image(self, src):
        """尝试本地路径 / file:// / http(s) 下载，返回 (bytes, mime)；失败返回 (None, 错误信息)"""
        try:
            limit = int(self.cfg.vision_max_bytes or 0)
        except (TypeError, ValueError):
            limit = 0
        limit = max(1, min(limit, self._IMAGE_HARD_LIMIT))   # 硬上限，配置被改大也没用
        path = (src or "").strip()
        if path.startswith("file://"):
            path = path[len("file://"):]
            if path.startswith("//"):
                path = path[1:]
            if len(path) > 2 and path[0] == "/" and path[2] == ":":   # file:///C:/x
                path = path[1:]
        try:
            if path.startswith(("http://", "https://")):
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://im.qq.com/",
                }
                data, err = await self._fetch_image_url(path, headers, limit)
                if data is None:
                    return None, err
            elif os.path.isfile(path):
                if not self._local_image_allowed(path):
                    logging.warning("拒绝读取白名单外的图片路径：%s", path)
                    return None, "不允许读取该路径的图片"
                with open(path, "rb") as f:
                    data = f.read(limit + 1)       # 先限长，再判断
                if len(data) > limit:
                    return None, self._too_big(limit)
            else:
                # 裸文件名（如 xxx.image）：只去白名单目录里找
                cand = ""
                for base in self._image_allow_dirs():
                    p = os.path.join(base, os.path.basename(path))
                    if os.path.isfile(p):
                        cand = p
                        break
                if not cand:
                    # 只在进程内告警一次：方便运维发现"图片本地路径换了地方"，同时不刷日志
                    if not self.__class__._image_miss_warned:
                        self.__class__._image_miss_warned = True
                        logging.warning("图片本地文件不在白名单目录：%s（已尝试 %s；可用环境变量 QBM_VISION_ALLOW_DIRS 追加）",
                                        src, list(self._image_allow_dirs()))
                    return None, f"找不到图片文件：{src}"
                with open(cand, "rb") as f:
                    data = f.read(limit + 1)
                if len(data) > limit:
                    return None, self._too_big(limit)
        except Exception as e:  # noqa: BLE001
            logging.warning("读图失败 %s: %s", type(e).__name__, e)
            return None, f"图片获取失败（{type(e).__name__}）"
        if not data:
            return None, "图片内容为空"
        mime = self._sniff_mime(data)
        if mime is None:
            return None, "不是可识别的图片格式"
        return data, mime

    async def _describe_image(self, ctx, a):
        if not self.cfg.sf_api_key:
            return "（视觉模型未配置，看不了图）"
        focus = (a.get("focus") or "整体内容").strip()[:80]
        # 候选源：显式传的 file > 当前会话最近一张图的 file/url
        sources = self.last_images.get(ctx.session_key) or []
        src = (a.get("file") or "").strip() or (sources[0].get("file") if sources else "") or ""
        if not src:
            return "（当前会话没有可看的图片）"
        data, mime = await self._load_image(src)
        if data is None:
            # file 不行就退回 URL
            url = ""
            if sources:
                url = sources[0].get("url") or ""
            if url and url != src:
                data, mime = await self._load_image(url)
                if data is None:
                    return f"（图片获取失败：{mime}；本地路径也打不开：{src}）"
            else:
                return f"（图片获取失败：{mime}）"
        cache_key = hashlib.sha256(data).hexdigest() + "|" + focus
        now = time.time()
        hit = self._vision_cache.get(cache_key)
        if hit and now - hit[0] < 3600:
            return hit[1]
        b64 = base64.b64encode(data).decode("ascii")
        prompt = (
            "请用中文客观描述这张图片：画面主体、人物/物体、动作表情、场景氛围，"
            f"以及图中出现的文字（如果有）。重点看：{focus}。只输出描述本身，不要评价、不要联想、不要寒暄。"
        )
        payload = {
            "model": self.cfg.vision_model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": prompt},
            ]}],
            "max_tokens": 600,
            "temperature": 0.3,
        }
        headers = {"Authorization": f"Bearer {self.cfg.sf_api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.cfg.vision_timeout) as client:
            r = await client.post(f"{self.cfg.vision_api_url}/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            desc = (r.json()["choices"][0]["message"]["content"] or "").strip()
        if not desc:
            return "（图片描述为空）"
        self._vision_cache[cache_key] = (now, desc)
        logging.info("看图成功 len=%s focus=%s", len(desc), focus)
        return desc
