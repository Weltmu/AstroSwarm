"""AstroSwarm（星群）产品知识库：供李清菡做客服时查询"""


FAQ = [
    {
        "keywords": ["是什么", "介绍", "功能", "产品", "干嘛", "作用", "星群", "astroswarm"],
        "text": "AstroSwarm（星群）是我同学做的 Windows 桌面多平台机器人管理器（前身叫 QBotManager）。它整合 QQ 官方机器人和微信官方 iLink 通道，内置统一 AI 大脑，能管理机器人、AI 聊天、群管理、多平台消息等。",
    },
    {
        "keywords": ["平台", "qq", "微信", "wechat", "支持", "飞书", "纸飞机", "频道"],
        "text": "目前支持：QQ（官方机器人 API，q.qq.com 开放平台）和微信（官方 iLink / ClawBot）。飞书、纸飞机在规划中。QQ 是官方机器人通道，微信是官方 iLink 接口，都是合规的官方通道。",
    },
    {
        "keywords": ["价格", "收费", "多少钱", "免费", "付费", "版本", "买", "钱"],
        "text": "客户端本身和插件全部开源免费：能力包（记忆、群管理、主动聊天、天气、定时提醒等）在控制台「插件管理」或官网插件市场直接装，源码在 GitHub（Weltmu/AstroSwarm）。微信通道走腾讯官方 iLink，需要单独开通。",
    },
    {
        "keywords": ["安装", "下载", "怎么用", "启动", "部署", "装", "exe", "zip", "运行"],
        "text": "下载后解压，运行里面的 AstroSwarm.exe（旧版叫 QBotManager.exe），首次启动会走安装向导（自动装依赖、可选创建桌面快捷方式）。安装或登录遇到问题，把报错截图/日志发给客服就行。",
    },
    {
        "keywords": ["激活", "授权", "激活码", "密钥", "机器码", "注册", "license", "key", "登录", "付费"],
        "text": "采用邮箱账号授权：在官网注册/登录邮箱后，程序内登录同一账号即可绑定本机，不需要激活码。插件已全部免费（源码开源），微信通道需要单独开通。换电脑用同一邮箱重新登录即可。",
    },
    {
        "keywords": ["微信", "ilink", "clawbot", "主动", "推送", "群消息", "24小时"],
        "text": "微信走官方 iLink（ClawBot）通道，注意三点限制：① 不能主动推送消息（只能回复）；② 超过 24 小时没回的消息可能失效；③ 读不了群消息（只支持私聊场景）。想做主动营销推送的话官方通道做不了。",
    },
    {
        "keywords": ["模型", "ai", "claude", "deepseek", "通义", "kimi", "智谱", "openai", "大脑", "大模型"],
        "text": "AI 大脑支持多家模型服务商：DeepSeek、通义、Kimi、智谱、OpenAI 等，自己填 API key 就能用。关于 Claude：Claude 官方不对中国大陆提供服务，国内直连不稳定，需要海外服务器或合规通道；建议国内先用 DeepSeek、通义这类直连模型，效果也够好。",
    },
    {
        "keywords": ["掉线", "没反应", "收不到", "不回", "断连", "崩溃", "重启", "故障", "问题", "日志"],
        "text": "常见排查：① 先看程序状态（机器人是否在跑、是否已连接）；② 看日志（程序日志/nonebot日志/napcat日志）；③ 微信 iLink 是长轮询，没消息时可能看起来'没连接'，发条消息试试；④ QQ 官方通道受 IP 白名单影响，家庭宽带 IP 变化会导致连不上。把日志发给客服排查最快。",
    },
    {
        "keywords": ["封号", "风控", "稳定", "安全", "合规", "官方", "踢下线", "掉线"],
        "text": "我们只走官方通道（QQ 官方机器人 API + 微信官方 iLink），不做 hook、不注入、不碰第三方协议，合规上尽量稳。但任何机器人平台都可能调整或限制，我们不承诺'永不封号/永久通道'。",
    },
    {
        "keywords": ["官网", "网站", "下载地址", "astroswarm.cn", "联系", "客服", "支持", "售后"],
        "text": "官网：astroswarm.cn（ICP 备案中，备案前暂时用服务器入口访问）。有问题可以随时找李清菡转达，或把日志/截图发来，客服会跟进处理。",
    },
]


def search_faq(question):
    q = (question or "").lower()
    scored = []
    for entry in FAQ:
        score = sum(1 for k in entry["keywords"] if k in q)
        if score:
            scored.append((score, entry["text"]))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return "（知识库里没找到相关内容，可以这样回：这个我帮你问问同学确认一下）"
    return "\n\n".join(text for _, text in scored[:3])

