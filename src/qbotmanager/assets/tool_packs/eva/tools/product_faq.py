"""产品知识库工具：返回结构化 FAQ 数据，怎么组织语言由 agent 按人设负责。"""
import json

_FAQ = {
    "价格": "免费版仅支持 QQ；开通会员档解锁微信等付费通道。进阶能力包是买断制：付一次永久可用，不按月扣费，具体价格见控制台「插件管理」里的插件详情。",
    "购买": "通过爱发电（https://ifdian.net/a/astroswarm）购买，首次下单备注填写注册邮箱，系统自动开通。",
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
