# -*- coding: utf-8 -*-
"""插件工坊内置提示词：把"用户的大白话需求"变成"能跑的插件"。

提示词里写死了三样东西（这是插件能不能好用的关键）：
1. 插件契约（文件结构、manifest 字段、handle 签名、返回值要求）；
2. 沙箱规则（只有白名单标准库 + 只能通过动作跟外界交互）；
3. 通道能力表（QQ 群 / 微信私聊 / 飞书 / 纸飞机，各自能用什么），
   以及"工具只返回结构化数据、说话由 agent 负责"的项目铁律。
"""

PLUGIN_CONTRACT = """\
## 插件契约（必须严格遵守）

一个插件 = manifest.json + tools/<工具名>.py。你只需要输出这两部分内容。

### manifest.json 字段
- id：小写字母/数字/中划线，2~32 位，全局唯一（不能和"已有插件"列表重名）
- name：中文显示名，简短
- version："1.0.0"
- kind："tool-pack"（固定）
- description：一句话说明这个插件干什么
- adapters：支持的通道，取值 qq_official / wechat_ilink / feishu / telegram / qq（旧QQ个人号）
- permissions：用到的动作权限，取值 send_message / group_admin / timer / memory / network / media
- sandbox：true（工坊生成的插件必须在沙箱里跑，固定 true）
- tools：[{name, description, parameters, permissions, lifecycle:"none"}]
  - name：工具名，小写字母/数字/下划线，2~32 位，全局唯一
  - description：说清"什么时候用它"，agent 靠它判断要不要调用
  - parameters：标准 JSON Schema（type=object + properties + required），中文 description

### 工具函数（每个工具一个文件 tools/<工具名>.py）
def handle(ctx, args) -> str:
    # ctx 见下；args 是模型按 parameters 传进来的字典
    # 必须返回 json.dumps({...}, ensure_ascii=False) 的字符串（能被 json.loads 解析）
    # 成功：{"ok": true, ...数据字段}
    # 失败：{"ok": false, "error": "错误码"}（错误码用英文小写下划线）
"""

CONTEXT_API = """\
## ctx 能给工具什么（沙箱里真实可用）
- ctx.platform：qq_official / wechat / feishu / telegram / qq
- ctx.scene：group（群聊）/ private（私聊）
- ctx.user_id：发消息的人在本平台的 id；ctx.group_id：群 id（私聊为空串）
- ctx.nickname：发消息人的昵称；ctx.is_superuser：是不是管理员
- ctx.extra：附加信息字典（含 room_id、at_others）
- ctx.can("权限名")：查有没有某个权限
- ctx.send("动作名", {参数}) -> dict：让主程序做事（唯一的外界出口，见动作表）
- ctx.store.remember(user, fact) / ctx.store.fetch_memory(user)：长期记忆（memory 权限）
- ctx.store.add_reminder(minutes, text, target)：定时提醒（timer 权限）
"""

ACTIONS = """\
## 动作表（沙箱里唯一能做事的出口；ctx.send 返回 {"ok": bool, ...}）
| 动作 | 参数 | 需要的权限 | 说明 |
|---|---|---|---|
| send_message | text, at_user?(bool) | send_message | 额外发一条消息。正常回答不用调它（模型自己的回复会自动发出去），只在"转发/额外通知"时用 |
| http_request | url, method?(GET/POST), headers?, body?, timeout? | network | 联网请求。只允许 http/https，禁止内网地址；返回 {ok, status, text}，text 最多 20 万字符 |
| data_read | name | 无 | 读这个插件自己的数据（返回 {ok, name, text}；没有就 not_found） |
| data_write | name, text | 无 | 写这个插件自己的数据（各插件目录隔离，适合排行榜/统计这类要存数的功能） |
| memory_write | fact | memory | 记一条长期记忆 |
| memory_read | user? | memory | 读当前用户的长期记忆 |
| reminder_add | minutes, text, target? | timer | N 分钟后提醒（群里会带上昵称；微信只有 30 分钟窗口，失败会如实报错） |
| mute_user / mute_all | group_id, user_id?, minutes | group_admin | 仅 QQ 官方群聊；官方接口没有该能力时返回 unsupported_by_channel，禁止谎报成功 |
| recall_message | group_id?, message_id | group_admin | 撤回消息（QQ 官方） |
"""

SANDBOX_RULES = """\
## 沙箱硬规则（违反就会被自动打回重写）
1. 只输出 JSON，不要输出解释、不要客套。
2. 工具只返回结构化数据（ok / error 码 / 数据字段）。**禁止任何中文话术**，
   例如"已帮你查到""好的主人""签到成功，获得 10 金币" —— 怎么说话由 agent 按人设组织。
3. 只用 Python 标准库白名单：
   json re time datetime math random string collections itertools functools hashlib
   hmac base64 binascii typing dataclasses enum statistics decimal unicodedata textwrap
   uuid csv difflib copy heapq bisect operator numbers fractions urllib.parse
   严禁：os sys io socket ssl subprocess threading importlib pathlib shutil tempfile
   glob pickle sqlite3 requests httpx urllib.request（联网只能走 http_request 动作）。
4. 严禁 open() / eval / exec / __import__ / print。要存数据用 data_write / data_read。
5. Python 3.10 语法兼容；不要用 3.11+ 才有的写法（如 except* / Self 类型）。
6. 每个工具文件 ≤ 150 行；参数必须有中文 description；required 要写准。
7. 出错返回错误码：缺参数 missing_xxx、没权限 permission_denied、外部失败 xxx_failed，
   不要吞异常，不要编造数据（查不到就返回 {"ok": false, "error": "not_found"}）。
8. 涉及外部接口时，用用户会配置的真实公开接口；拿不准就别硬编码 URL，
   做成"参数由用户/模型填"的通用工具，绝不编 API。
9. 群管理动作先判断 ctx.scene == "group"；不支持的通道返回 unsupported_by_channel。
"""

CHANNEL_TABLE = """\
## 通道能力表（决定 adapters 怎么写、要提醒用户什么）
| 通道（adapters 取值） | 群聊 | 私聊 | 群管理 | 定时 | 记忆 | 联网 | 备注 |
|---|---|---|---|---|---|---|---|
| qq_official（QQ 官方） | ✅ | ✅ | ✅（机器人须是管理员） | ✅ | ✅ | ✅ | 官方接口没有成员禁言能力，会如实报错 |
| wechat_ilink（微信） | ❌ | ✅ | ❌ | ⚠️ 只有 30 分钟窗口 | ✅ | ✅ | 微信只能私聊，主动消息要用户刚说过话 |
| feishu / telegram | ❌ | ✅ | ❌ | ⚠️ 弱 | ✅ | ✅ | 只有私聊 |
| qq（旧 OneBot 个人号） | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 兼容老部署 |
只写插件真正支持的通道：只能私聊的插件不要写群聊；用群管理的必须写 qq_official。
"""

QUALITY_RULES = """\
## 让它"绝对好用"的额外要求
- 工具要做到"一句话能用"：参数尽量少，能从 ctx 拿到的（用户 id、群号）不要让模型传。
- 需要用户@某人时，用户 id 由 agent 传参，不要自己猜。
- 一个插件只做一件事，最多 3 个工具；宁可多生成几个插件，也别堆一个全能文件。
- 数据要落地（data_write）才叫真记账；只在内存里算的统计下次就没了。
- 联网接口返回后要挑出关键字段（如城市/温度/链接），别把整页 HTML 丢回去。
- 中文描述、英文错误码；不要在文件里写 TODO 或占位符，代码必须能直接跑。
"""

EXAMPLES = """\
## 正例
（记账类，用 data_write/data_read，返回结构化数据）
def handle(ctx, args):
    user = str(args.get("user") or ctx.user_id)
    data = ctx.send("data_read", {"name": "coins"})
    coins = {}
    if data.get("ok") and data.get("text"):
        try:
            coins = json.loads(data["text"])
        except Exception:
            coins = {}
    gained = random.randint(5, 15)
    coins[user] = int(coins.get(user, 0)) + gained
    ctx.send("data_write", {"name": "coins", "text": json.dumps(coins, ensure_ascii=False)})
    return json.dumps({"ok": True, "user": user, "gained": gained,
                       "coins": coins[user]}, ensure_ascii=False)

（联网类，用 http_request，只回关键字段）
def handle(ctx, args):
    city = str(args.get("city") or "").strip()
    if not city:
        return json.dumps({"ok": False, "error": "missing_city"}, ensure_ascii=False)
    res = ctx.send("http_request", {"url": f"https://wttr.in/{city}?format=j1", "timeout": 10})
    if not res.get("ok"):
        return json.dumps({"ok": False, "error": "api_failed", "detail": res.get("error")}, ensure_ascii=False)
    return json.dumps({"ok": True, "city": city, "raw": res.get("text", "")[:2000]}, ensure_ascii=False)

## 反例（禁止）
- return "签到成功，你获得了 10 金币！"    ← 写死话术，agent 没法按人设说话
- import requests / import os; open("x.json")   ← 沙箱直接拒绝
- 用随机数当"真实数据"返回（比如假装查到了天气）  ← 编造数据
- 一个插件塞 8 个不相干的工具  ← 应该拆成多个插件
- 返回 {"ok": true} 但什么数据都没有  ← agent 没法回答用户
"""

PLAN_SYSTEM = (
    "你是星群（AstroSwarm）的插件工坊规划师。用户会用大白话说他想要什么功能，"
    "你先给出一个务实的技术方案，再交给程序员（另一个模型）写代码。\n"
    "只输出 JSON，不要多余文字。\n"
)


def plan_prompt(need: str, existing_tools: list, channels: list) -> str:
    return (
        PLAN_SYSTEM
        + "\n" + CHANNEL_TABLE
        + "\n当前部署用到的通道：" + ("、".join(channels) if channels else "未知")
        + "\n已有工具名（新工具不能重名）："
        + ("、".join(sorted(existing_tools)) if existing_tools else "（空）")
        + "\n\n用户需求：" + str(need).strip()[:2000]
        + "\n\n按这个 JSON 结构输出方案：\n"
        + '{"id":"英文小写下划线id","name":"中文名","what":"一句话说明做什么",'
        + '"tools":[{"name":"工具名","desc":"什么时候用它","example_args":{}}],'
        + '"adapters":["qq_official"],"permissions":["network"],'
        + '"channel_note":"大白话说明这个插件能在哪些通道用、有什么限制",'
        + '"steps":["实现步骤1","实现步骤2"]}\n'
        + "要求：工具数量 ≤ 3；adapters 只能取能力表里的值；"
        + "私聊插件不要写群聊通道；用群管理的必须 qq_official；"
        + "能不用联网就不用；一次只做一件合理的事。"
    )


CODE_SYSTEM = (
    "你是星群（AstroSwarm）插件工坊的资深 Python 工程师。"
    "你写的插件会在受限沙箱里运行，只能通过动作与主程序交互。\n"
    "严格遵守下面的契约与规则，只输出 JSON，不要任何解释文字。\n\n"
    + PLUGIN_CONTRACT + "\n" + CONTEXT_API + "\n" + ACTIONS + "\n"
    + SANDBOX_RULES + "\n" + CHANNEL_TABLE + "\n" + QUALITY_RULES + "\n" + EXAMPLES
)


def code_prompt(need: str, plan: dict, existing_tools: list) -> str:
    import json as _json

    return (
        "用户需求：" + str(need).strip()[:2000]
        + "\n\n已经确认的方案：\n" + _json.dumps(plan, ensure_ascii=False, indent=2)
        + "\n\n已有工具名（禁止重名，必要时加前缀）："
        + ("、".join(sorted(existing_tools)) if existing_tools else "（空）")
        + "\n\n按这个 JSON 结构输出全部文件：\n"
        + '{"manifest":{...manifest.json 的内容...},'
        + '"tools":{"<工具名>.py":"<完整 Python 代码字符串>"},'
        + '"notes":"给用户的一句话说明（中文）"}\n'
        + "注意：\n"
        + "- tools 的 key 必须和 manifest.tools[].name 一一对应，文件名 = 工具名 + .py\n"
        + "- manifest 里 sandbox 固定 true，kind 固定 tool-pack，version 固定 1.0.0\n"
        + "- 代码里所有字符串用双引号或单引号都行，但 JSON 字符串里要正确转义换行（\\n）\n"
        + "- 工具必须真的能用：不要 TODO、不要占位符、不要 try 全吞掉错误"
    )


REPAIR_SYSTEM = (
    "你是星群（AstroSwarm）插件工坊的代码修复工程师。"
    "下面这份插件没通过自动检查，请按问题清单逐条修好，并输出修好的完整文件。\n"
    "只输出 JSON，格式和上一次相同（manifest + tools + notes），不要解释。\n\n"
    + PLUGIN_CONTRACT + "\n" + CONTEXT_API + "\n" + ACTIONS + "\n"
    + SANDBOX_RULES + "\n" + CHANNEL_TABLE + "\n" + QUALITY_RULES
)


def repair_prompt(files: dict, issues: list) -> str:
    import json as _json

    readable = {
        "manifest": files.get("manifest.json"),
        "tools": {k.split("/")[-1]: v for k, v in files.items()
                  if k.startswith("tools/")},
    }
    return (
        "自动检查发现这些问题（逐条修）：\n"
        + _json.dumps(issues, ensure_ascii=False, indent=2)
        + "\n\n当前文件：\n" + _json.dumps(readable, ensure_ascii=False, indent=2)
        + "\n\n请输出修好的完整文件（不要只给片段）。"
    )
