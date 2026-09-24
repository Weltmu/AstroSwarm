"""产品知识库工具：返回结构化 FAQ 数据，怎么组织语言由 agent 按人设负责。"""
import json

_FAQ = {
    "价格": "客户端和插件都开源免费：插件市场里的能力包全部免费，直接装就行；源码在 GitHub（Weltmu/AstroSwarm）。只有微信 iLink 通道属于会员档功能。",
    "购买": "插件不用购买，控制台「插件管理」或官网插件市场直接装即可；整套源码在 GitHub Weltmu/AstroSwarm，也可以自己编译。",
    "安装": "Windows 解压运行 AstroSwarm.exe；Linux 运行 install.sh 后浏览器打开控制台。",
    "微信": "微信通道为付费功能（会员档解锁），走腾讯官方 iLink 通道。",
    "激活": "邮箱登录即授权，不需要激活码。",
}


def handle(ctx, args):
    question = str(args.get("question") or "").strip()
    for key, answer in _FAQ.items():
        if key in question:
            return json.dumps({"ok": True, "matched": key, "answer": answer},
                              ensure_ascii=False)
    return json.dumps({"ok": False, "error": "no_answer"}, ensure_ascii=False)
