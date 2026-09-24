"""定时器：到点自动发提醒。

语言表述层由 agent 负责：优先用 compose 回调让大脑按当前人设生成提醒话术；
没有回调时（测试/降级）才用「（人设名提醒）内容」模板兜底。
"""
import asyncio
import logging
import time


async def reminder_loop(cfg, store, ob, compose=None):
    while True:
        try:
            for r in store.due_reminders():
                if r["kind"] == "unban":
                    # 全员禁言到点解除
                    await ob.action("set_group_whole_ban", {"group_id": r["target_id"], "enable": False})
                    store.mark_reminder_fired(r["id"])
                    logging.info("全员禁言已解除 group=%s", r["target_id"])
                    continue
                text = ""
                if compose is not None:
                    try:
                        text = await compose(r)
                    except Exception:  # noqa: BLE001 —— 生成失败退回模板，不阻塞调度
                        text = ""
                if not str(text or "").strip():
                    name = getattr(cfg, "persona_name", "") or "李清菡"
                    text = f"（{name}提醒）{r['text']}"
                if r["kind"] == "group":
                    await ob.action("send_group_msg", {"group_id": r["target_id"], "message": text})
                else:
                    await ob.action("send_private_msg", {"user_id": r["target_id"], "message": text})
                store.mark_reminder_fired(r["id"])
                logging.info("提醒已发送 target=%s text=%s", r["target_id"], r["text"])
        except Exception:  # noqa: BLE001
            logging.exception("reminder_loop 出错")
        await asyncio.sleep(20)
