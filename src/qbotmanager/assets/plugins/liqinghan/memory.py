"""SQLite 存储：用户档案 / 消息历史 / 你同学规则 / 金币小游戏 / 提醒"""
import json
import random
import sqlite3
import time


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  qq TEXT PRIMARY KEY,
  nickname TEXT DEFAULT '',
  first_seen INTEGER,
  last_seen INTEGER,
  msg_count INTEGER DEFAULT 0,
  relationship INTEGER DEFAULT 0,
  notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session TEXT,
  role TEXT,
  qq TEXT,
  group_id TEXT,
  text TEXT,
  ts INTEGER
);
CREATE TABLE IF NOT EXISTS rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_qq TEXT,
  text TEXT,
  scope TEXT DEFAULT 'all',
  enabled INTEGER DEFAULT 1,
  created_ts INTEGER,
  hits INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS coins(
  qq TEXT PRIMARY KEY,
  balance INTEGER DEFAULT 0,
  last_checkin TEXT DEFAULT '',
  work_count INTEGER DEFAULT 0,
  last_work_ts INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reminders(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT,
  target_id TEXT,
  text TEXT,
  due_ts INTEGER,
  fired INTEGER DEFAULT 0,
  created_ts INTEGER
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS outreach(
  qq TEXT PRIMARY KEY,
  last_ts INTEGER DEFAULT 0,
  unanswered INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS join_requests(
  flag TEXT PRIMARY KEY,
  group_id TEXT,
  user_id TEXT,
  comment TEXT DEFAULT '',
  ts INTEGER,
  status TEXT DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS memories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  qq TEXT,
  fact TEXT,
  ts INTEGER
);
CREATE TABLE IF NOT EXISTS mood(
  qq TEXT PRIMARY KEY,
  anger INTEGER DEFAULT 0,
  updated_ts INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS diary(
  day TEXT PRIMARY KEY,
  content TEXT DEFAULT '',
  ts INTEGER
);
CREATE TABLE IF NOT EXISTS birthdays(
  qq TEXT PRIMARY KEY,
  month INTEGER,
  day INTEGER,
  note TEXT DEFAULT '',
  ts INTEGER
);
CREATE TABLE IF NOT EXISTS games(
  group_id TEXT PRIMARY KEY,
  state TEXT,
  started_ts INTEGER,
  last_ts INTEGER
);
"""


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---- 用户档案 ----
    def touch_user(self, qq, nickname=""):
        now = int(time.time())
        self.db.execute(
            "INSERT INTO users(qq, nickname, first_seen, last_seen, msg_count) "
            "VALUES(?,?,?,?,1) "
            "ON CONFLICT(qq) DO UPDATE SET last_seen=excluded.last_seen, "
            "msg_count=msg_count+1, "
            "nickname=CASE WHEN ?<>'' THEN ? ELSE nickname END",
            (qq, nickname, now, now, nickname, nickname),
        )
        self.db.commit()

    def get_user(self, qq):
        return self.db.execute("SELECT * FROM users WHERE qq=?", (qq,)).fetchone()

    def adjust_relationship(self, qq, delta):
        self.db.execute(
            "INSERT INTO users(qq, relationship) VALUES(?,?) "
            "ON CONFLICT(qq) DO UPDATE SET relationship=relationship+?",
            (qq, delta, delta),
        )
        self.db.commit()

    def set_relationship(self, qq, score):
        self.db.execute(
            "INSERT INTO users(qq, relationship) VALUES(?,?) "
            "ON CONFLICT(qq) DO UPDATE SET relationship=?",
            (qq, score, score),
        )
        self.db.commit()

    # ---- 消息历史 ----
    def add_message(self, session, role, qq, group_id, text):
        text = (text or "")[:1000]  # 防止超长消息撑爆上下文
        self.db.execute(
            "INSERT INTO messages(session, role, qq, group_id, text, ts) VALUES(?,?,?,?,?,?)",
            (session, role, qq, group_id, text, int(time.time())),
        )
        self.db.execute(
            "DELETE FROM messages WHERE session=? AND id NOT IN "
            "(SELECT id FROM messages WHERE session=? ORDER BY id DESC LIMIT 60)",
            (session, session),
        )
        self.db.commit()

    def recent_messages(self, session, limit=20):
        rows = self.db.execute(
            "SELECT role, qq, text FROM messages WHERE session=? ORDER BY id DESC LIMIT ?",
            (session, limit),
        ).fetchall()
        return list(reversed(rows))

    def recent_user_context(self, user_id, session, limit=20):
        """跨会话上下文：该用户所有消息（私聊+群聊）+ 当前会话里她的回复"""
        rows = self.db.execute(
            "SELECT role, qq, text FROM messages "
            "WHERE qq=? OR (role='assistant' AND session IN (?, ?)) "
            "ORDER BY id DESC LIMIT ?",
            (user_id, f"p:{user_id}", session, limit),
        ).fetchall()
        return list(reversed(rows))

    # ---- 你同学规则 ----
    def add_rule(self, owner_qq, text, scope="all"):
        text = (text or "")[:200]
        cur = self.db.execute(
            "INSERT INTO rules(owner_qq, text, scope, enabled, created_ts) VALUES(?,?,?,1,?)",
            (owner_qq, text, scope, int(time.time())),
        )
        self.db.commit()
        return cur.lastrowid

    def list_rules(self, enabled_only=True):
        if enabled_only:
            return self.db.execute("SELECT * FROM rules WHERE enabled=1 ORDER BY id").fetchall()
        return self.db.execute("SELECT * FROM rules ORDER BY id").fetchall()

    def remove_rule(self, rule_id):
        self.db.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        self.db.commit()
        return self.db.total_changes

    # ---- 金币小游戏 ----
    def checkin(self, qq, today):
        row = self.db.execute("SELECT * FROM coins WHERE qq=?", (qq,)).fetchone()
        if row and row["last_checkin"] == today:
            return False, row["balance"], "今天已经签过到啦"
        bonus = random.randint(10, 30)
        if row:
            self.db.execute(
                "UPDATE coins SET balance=balance+?, last_checkin=? WHERE qq=?",
                (bonus, today, qq),
            )
        else:
            self.db.execute(
                "INSERT INTO coins(qq, balance, last_checkin) VALUES(?,?,?)",
                (qq, bonus, today),
            )
        self.db.commit()
        bal = self.db.execute("SELECT balance FROM coins WHERE qq=?", (qq,)).fetchone()["balance"]
        return True, bal, f"签到成功 +{bonus} 金币，当前 {bal} 金币"

    def work(self, qq, cooldown_sec):
        now = int(time.time())
        row = self.db.execute("SELECT * FROM coins WHERE qq=?", (qq,)).fetchone()
        if row and now - row["last_work_ts"] < cooldown_sec:
            wait = cooldown_sec - (now - row["last_work_ts"])
            return False, 0, f"打工太频繁啦，{wait//60} 分钟后再来"
        pay = random.randint(5, 15)
        if row:
            self.db.execute(
                "UPDATE coins SET balance=balance+?, work_count=work_count+1, last_work_ts=? WHERE qq=?",
                (pay, now, qq),
            )
        else:
            self.db.execute(
                "INSERT INTO coins(qq, balance, work_count, last_work_ts) VALUES(?,?,1,?)",
                (qq, pay, now),
            )
        self.db.commit()
        bal = self.db.execute("SELECT balance FROM coins WHERE qq=?", (qq,)).fetchone()["balance"]
        return True, bal, f"打工完成 +{pay} 金币，当前 {bal} 金币"

    def balance(self, qq):
        row = self.db.execute("SELECT balance FROM coins WHERE qq=?", (qq,)).fetchone()
        return row["balance"] if row else 0

    def leaderboard(self, n=5):
        rows = self.db.execute("SELECT qq, balance FROM coins ORDER BY balance DESC LIMIT ?", (n,)).fetchall()
        return rows

    # ---- 提醒 ----
    def add_reminder(self, kind, target_id, text, minutes):
        due = int(time.time()) + max(1, int(minutes)) * 60
        cur = self.db.execute(
            "INSERT INTO reminders(kind, target_id, text, due_ts, created_ts) VALUES(?,?,?,?,?)",
            (kind, target_id, text, due, int(time.time())),
        )
        self.db.commit()
        return cur.lastrowid

    def due_reminders(self, now=None):
        now = now or int(time.time())
        return self.db.execute(
            "SELECT * FROM reminders WHERE fired=0 AND due_ts<=? ORDER BY due_ts", (now,)
        ).fetchall()

    def mark_reminder_fired(self, rid):
        self.db.execute("UPDATE reminders SET fired=1 WHERE id=?", (rid,))
        self.db.commit()

    def cancel_unban(self, group_id):
        self.db.execute(
            "DELETE FROM reminders WHERE kind='unban' AND target_id=? AND fired=0", (group_id,)
        )
        self.db.commit()

    # ---- 设置项（静默模式等）----
    def get_setting(self, key, default=""):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        self.db.execute(
            "INSERT INTO settings(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.db.commit()

    # ---- 私聊外联冻结 ----
    def get_outreach(self, qq):
        return self.db.execute("SELECT * FROM outreach WHERE qq=?", (qq,)).fetchone()

    def set_outreach(self, qq, last_ts, unanswered):
        self.db.execute(
            "INSERT INTO outreach(qq, last_ts, unanswered) VALUES(?,?,?) "
            "ON CONFLICT(qq) DO UPDATE SET last_ts=excluded.last_ts, unanswered=excluded.unanswered",
            (qq, last_ts, unanswered),
        )
        self.db.commit()

    def reset_outreach(self, qq):
        self.db.execute("UPDATE outreach SET last_ts=0, unanswered=0 WHERE qq=?", (qq,))
        self.db.commit()

    def outreach_candidates(self):
        return self.db.execute("SELECT qq FROM users WHERE msg_count>0").fetchall()

    def outreach_rows(self):
        return self.db.execute("SELECT * FROM outreach").fetchall()

    # ---- 入群审批 ----
    def add_join_request(self, flag, group_id, user_id, comment):
        self.db.execute(
            "INSERT OR IGNORE INTO join_requests(flag, group_id, user_id, comment, ts) VALUES(?,?,?,?,?)",
            (flag, group_id, user_id, comment, int(time.time())),
        )
        self.db.commit()

    def pending_join_requests(self, delay_h):
        cutoff = int(time.time()) - int(delay_h * 3600)
        return self.db.execute(
            "SELECT * FROM join_requests WHERE status='pending' AND ts<=? ORDER BY ts",
            (cutoff,),
        ).fetchall()

    def mark_join_done(self, flag):
        self.db.execute("UPDATE join_requests SET status='done' WHERE flag=?", (flag,))
        self.db.commit()

    # ---- 长期记忆 ----
    def remember(self, qq, fact):
        fact = (fact or "")[:200]
        self.db.execute("INSERT INTO memories(qq, fact, ts) VALUES(?,?,?)", (qq, fact, int(time.time())))
        self.db.commit()

    def remember_if_new(self, qq, fact):
        """去重后写入记忆：与已有记忆高度重复就跳过。返回是否写入"""
        fact = fact.strip().strip("。.!！~～")
        fact = fact[:200]
        if len(fact) < 4:
            return False
        rows = self.db.execute("SELECT fact FROM memories WHERE qq=?", (qq,)).fetchall()
        for r in rows:
            a, b = r["fact"], fact
            if a in b or b in a:
                return False
        self.remember(qq, fact)
        return True

    def memories_for(self, qq, limit=5):
        return self.db.execute(
            "SELECT fact FROM memories WHERE qq=? ORDER BY id DESC LIMIT ?", (qq, limit)
        ).fetchall()

    # ---- 日记（睡前自动写，醒来能想起）----
    def save_diary(self, day, content):
        self.db.execute(
            "INSERT INTO diary(day, content, ts) VALUES(?,?,?) "
            "ON CONFLICT(day) DO UPDATE SET content=excluded.content, ts=excluded.ts",
            (day, content, int(time.time())),
        )
        self.db.commit()

    def diary_recent(self, limit=2):
        return self.db.execute(
            "SELECT day, content FROM diary ORDER BY day DESC LIMIT ?", (limit,)
        ).fetchall()

    # ---- 生日 ----
    def set_birthday(self, qq, month, day, note=""):
        self.db.execute(
            "INSERT INTO birthdays(qq, month, day, note, ts) VALUES(?,?,?,?,?) "
            "ON CONFLICT(qq) DO UPDATE SET month=excluded.month, day=excluded.day, "
            "note=excluded.note, ts=excluded.ts",
            (qq, month, day, note, int(time.time())),
        )
        self.db.commit()

    def birthdays_due(self, month, day):
        return self.db.execute(
            "SELECT * FROM birthdays WHERE month=? AND day=?", (month, day)
        ).fetchall()

    # ---- 小游戏状态（每群一个）----
    def set_game(self, group_id, state):
        self.db.execute(
            "INSERT INTO games(group_id, state, started_ts, last_ts) VALUES(?,?,?,?) "
            "ON CONFLICT(group_id) DO UPDATE SET state=excluded.state, last_ts=excluded.last_ts",
            (group_id, state, int(time.time()), int(time.time())),
        )
        self.db.commit()

    def get_game(self, group_id):
        row = self.db.execute("SELECT state FROM games WHERE group_id=?", (group_id,)).fetchone()
        return row["state"] if row else None

    def clear_game(self, group_id):
        self.db.execute("DELETE FROM games WHERE group_id=?", (group_id,))
        self.db.commit()

    # ---- 金币（游戏奖励用）----
    def add_coins(self, qq, delta):
        self.db.execute(
            "INSERT INTO coins(qq, balance) VALUES(?,?) "
            "ON CONFLICT(qq) DO UPDATE SET balance=balance+?",
            (qq, delta, delta),
        )
        self.db.commit()
        return self.balance(qq)

    # ---- 记忆扫描 / 日记素材 ----
    def user_ids_since(self, ts):
        return [r[0] for r in self.db.execute(
            "SELECT DISTINCT qq FROM messages WHERE role='user' AND ts>=? AND qq<>''", (ts,)
        )]

    def messages_since(self, qq, ts, limit=50):
        return self.db.execute(
            "SELECT role, text, ts FROM messages WHERE qq=? AND role='user' AND ts>=? "
            "ORDER BY id ASC LIMIT ?",
            (qq, ts, limit),
        ).fetchall()

    def messages_today(self, since_ts, limit=40):
        return self.db.execute(
            "SELECT role, qq, text FROM messages WHERE ts>=? ORDER BY id DESC LIMIT ?",
            (since_ts, limit),
        ).fetchall()

    def user_stats(self, top=20):
        return self.db.execute(
            "SELECT u.qq, u.nickname, u.first_seen, u.last_seen, u.msg_count, u.relationship, "
            "(SELECT balance FROM coins c WHERE c.qq=u.qq) AS balance "
            "FROM users u ORDER BY u.last_seen DESC LIMIT ?",
            (top,),
        ).fetchall()

    # ---- 情绪（愤怒值 0~100）----
    def get_anger(self, qq):
        row = self.db.execute("SELECT * FROM mood WHERE qq=?", (qq,)).fetchone()
        if not row:
            return 0
        hours = (int(time.time()) - row["updated_ts"]) / 3600.0
        return max(0, min(100, row["anger"] - int(hours * 2)))  # 随时间消退

    def adjust_anger(self, qq, delta):
        current = self.get_anger(qq)
        new = max(0, min(100, current + delta))
        self.db.execute(
            "INSERT INTO mood(qq, anger, updated_ts) VALUES(?,?,?) "
            "ON CONFLICT(qq) DO UPDATE SET anger=excluded.anger, updated_ts=excluded.updated_ts",
            (qq, new, int(time.time())),
        )
        self.db.commit()
        return new
