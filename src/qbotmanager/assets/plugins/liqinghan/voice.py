"""语音条：MOSS-TTSD 合成 wav → pilk 转 silk → 发 QQ 语音"""
import logging
import os
import time

import httpx

try:
    import pilk
    HAS_PILK = True
except Exception:  # noqa: BLE001
    pilk = None
    HAS_PILK = False


async def synth(cfg, text, out_wav):
    """调 MOSS-TTSD 生成 wav（24kHz），返回路径"""
    payload = {
        "model": cfg.voice_model,
        "stream": False,
        "input": text[:180],
        "max_tokens": 1200,
        "response_format": "wav",
        "sample_rate": 24000,
        "speed": cfg.voice_speed,
        "gain": cfg.voice_gain,
    }
    if cfg.voice_preset:
        # CosyVoice2 等预置音色模式：voice 传音色名
        payload["voice"] = cfg.voice_preset
    else:
        # MOSS-TTSD 克隆模式：references 传参考音频
        payload["references"] = [{"audio": cfg.voice_ref_url, "text": cfg.voice_ref_text}]
    headers = {"Authorization": f"Bearer {cfg.sf_api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post("https://api.siliconflow.cn/v1/audio/speech", headers=headers, json=payload)
        r.raise_for_status()
        with open(out_wav, "wb") as f:
            f.write(r.content)
    return out_wav


def to_silk(wav_path, silk_path):
    if not HAS_PILK:
        raise RuntimeError("未安装 pilk，无法转 silk")
    pilk.encode(wav_path, silk_path, pcm_rate=24000, tencent=True)
    return silk_path


async def send_voice(cfg, ob, session, msg_type, group_id, user_id, text):
    """合成并发送一条语音。成功返回 True"""
    if not cfg.sf_api_key or not HAS_PILK:
        return False
    base = os.path.join(cfg.voice_dir, str(int(time.time() * 1000)))
    wav, silk = base + ".wav", base + ".silk"
    try:
        os.makedirs(cfg.voice_dir, exist_ok=True)
        await synth(cfg, text, wav)
        if not os.path.getsize(wav):
            return False
        to_silk(wav, silk)
        if not os.path.getsize(silk):
            return False
        seg = [{"type": "record", "data": {"file": "file://" + silk}}]
        if msg_type == "group":
            resp = await ob.action("send_group_msg", {"group_id": int(group_id), "message": seg})
        else:
            resp = await ob.action("send_private_msg", {"user_id": int(user_id), "message": seg})
        ok = bool(resp and resp.get("message_id"))
        # 发送成功后清理临时文件
        for p in (wav, silk):
            try:
                os.remove(p)
            except OSError:
                pass
        return ok
    except Exception as e:  # noqa: BLE001
        logging.warning("语音发送失败：%s", e)
        return False
