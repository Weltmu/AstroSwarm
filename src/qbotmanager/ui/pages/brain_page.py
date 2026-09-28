# -*- coding: utf-8 -*-
"""AI 大脑页：接口配置 + 平台开关 + 模型/MCP/记忆/身份绑定摘要。"""
import json
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ...core import agent_profile, ai_config
from ...core import message_store
from ..theme import TEXT_3
from ..widgets import EmptyState, GlassPanel
from .common import PageContext, Worker, make_row


def _split_csv(text: str) -> list:
    return [x.strip() for x in (text or "").replace("，", ",").split(",") if x.strip()]


_AGENT_RESTART_KEYS = (
    "agent_profile_enabled", "agent_profile_id", "agent_wake_words",
    "agent_owner_openid", "vision_api_url", "vision_api_key", "vision_model",
    "llm_api_url", "llm_api_key", "llm_model",
)


def _agent_cfg_snapshot(s):
    """记录影响机器人启动加载的智能体/模型配置快照（用于自动重启判断）。"""
    llm = ai_config.current_config(s)
    return {
        "agent_profile_enabled": bool(getattr(s, "agent_profile_enabled", False)),
        "agent_profile_id": str(getattr(s, "agent_profile_id", "") or ""),
        "agent_wake_words": list(getattr(s, "agent_wake_words", []) or []),
        "agent_owner_openid": str(getattr(s, "agent_owner_openid", "") or ""),
        "vision_api_url": str(getattr(s, "vision_api_url", "") or ""),
        "vision_api_key": str(getattr(s, "vision_api_key", "") or ""),
        "vision_model": str(getattr(s, "vision_model", "") or ""),
        "llm_api_url": str(llm.get("api_url") or ""),
        "llm_api_key": str(llm.get("api_key") or ""),
        "llm_model": str(llm.get("model") or ""),
    }


def _agent_restart_required(before, after) -> bool:
    """档案/模型相关配置变化时需要重启机器人才会真正载入。"""
    return any(before.get(k) != after.get(k) for k in _AGENT_RESTART_KEYS)


class BrainPage(QWidget):
    """AI 大脑页。

    refresh_status 只更新状态摘要，绝不重置接口配置/平台开关控件，
    否则主窗口的定时刷新会把用户正在编辑的内容“复原”。
    """

    def __init__(self, ctx: PageContext):
        super().__init__()
        self.ctx = ctx
        self._loaded_persona = ""
        self._loaded_agent_cfg = {}
        self._build_ui()
        self.load_config()
        self.refresh_status()

    def _build_ui(self):
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        outer = QVBoxLayout(content)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        title = QLabel("AI 大脑")
        title.setObjectName("pageTitle")
        sub = QLabel("内置 AI 大脑：QQ / 微信 / 飞书 / 纸飞机共享模型、记忆与工具；"
                     "接口配置与平台开关在本页完成")
        sub.setObjectName("pageSub")
        outer.addWidget(title)
        outer.addWidget(sub)

        # ---- 接口配置 + 平台开关 ----
        config_panel = GlassPanel(strong=True)
        cv = QVBoxLayout(config_panel)
        cv.setContentsMargins(18, 14, 18, 16)
        cv.setSpacing(10)
        cfg_lbl = QLabel("接口配置")
        cfg_lbl.setObjectName("sectionTitle")
        cv.addWidget(cfg_lbl)
        cfg_tip = QLabel("选择服务商自动填接口地址与默认模型（预设已按官方文档核对）；"
                         "平台开关决定 AI 在哪些平台生效，保存后重启机器人生效。")
        cfg_tip.setWordWrap(True)
        cfg_tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        cv.addWidget(cfg_tip)

        platform_row = QHBoxLayout()
        platform_lbl = QLabel("平台启用")
        platform_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.chk_qq = QCheckBox("QQ")
        self.chk_wechat = QCheckBox("微信")
        self.chk_feishu = QCheckBox("飞书")
        self.chk_telegram = QCheckBox("纸飞机")
        for chk in (self.chk_qq, self.chk_wechat, self.chk_feishu, self.chk_telegram):
            chk.setToolTip("关闭后 AI 大脑不再处理该平台的消息，但平台通道本身仍正常运行")
        platform_row.addWidget(platform_lbl)
        platform_row.addSpacing(6)
        platform_row.addWidget(self.chk_qq)
        platform_row.addWidget(self.chk_wechat)
        platform_row.addWidget(self.chk_feishu)
        platform_row.addWidget(self.chk_telegram)
        platform_row.addStretch(1)
        cv.addLayout(platform_row)

        provider_row = QHBoxLayout()
        provider_lbl = QLabel("服务商")
        provider_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.ai_provider_combo = QComboBox()
        for p in ai_config.AI_PROVIDERS:
            self.ai_provider_combo.addItem(p["name"], p["key"])
        self.ai_provider_combo.setToolTip(
            "DeepSeek / 通义 / 智谱 / Kimi / OpenAI 等大厂接口自动填地址与默认模型，"
            "也可选「自定义接口」手动填写")
        provider_row.addWidget(provider_lbl)
        provider_row.addWidget(self.ai_provider_combo, 1)
        cv.addLayout(provider_row)

        url_row = QHBoxLayout()
        url_lbl = QLabel("接口地址")
        url_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.ai_url_edit = QLineEdit()
        self.ai_url_edit.setPlaceholderText("https://api.deepseek.com")
        url_row.addWidget(url_lbl)
        url_row.addWidget(self.ai_url_edit, 1)
        cv.addLayout(url_row)

        model_row = QHBoxLayout()
        model_lbl = QLabel("模型")
        model_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.ai_model_edit = QLineEdit()
        self.ai_model_edit.setPlaceholderText("deepseek-v4-flash")
        model_row.addWidget(model_lbl)
        model_row.addWidget(self.ai_model_edit, 1)
        cv.addLayout(model_row)

        key_row = QHBoxLayout()
        key_lbl = QLabel("API 密钥")
        key_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.ai_key_edit = QLineEdit()
        self.ai_key_edit.setEchoMode(QLineEdit.Password)
        self.ai_key_edit.setPlaceholderText("sk-...")
        key_row.addWidget(key_lbl)
        key_row.addWidget(self.ai_key_edit, 1)
        cv.addLayout(key_row)

        save_row = QHBoxLayout()
        self.btn_save = QPushButton("保存 AI 配置")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self._save_config)
        save_row.addWidget(self.btn_save)
        save_row.addStretch(1)
        cv.addLayout(save_row)
        outer.addWidget(config_panel)

        # ---- 智能体档案（李清菡等可选预设） ----
        agent_panel = GlassPanel(strong=True)
        self._agent_panel = agent_panel
        av = QVBoxLayout(agent_panel)
        av.setContentsMargins(18, 14, 18, 16)
        av.setSpacing(10)
        a_lbl = QLabel("智能体档案")
        a_lbl.setObjectName("sectionTitle")
        av.addWidget(a_lbl)
        a_tip = QLabel("可选李清菡等智能体预设：人格仍跟随上方人格设定，功能层按档案启用；"
                       "唤醒词用于群聊无 @ 唤醒，私聊无需唤醒词；"
                       "QQ 群不 @ 也回复需要群主开启「获取群内全部消息」后才会推送。"
                       "保存后重启机器人生效。")
        a_tip.setWordWrap(True)
        a_tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        av.addWidget(a_tip)

        self.chk_agent_profile = QCheckBox("启用智能体档案（默认关闭）")
        self.chk_agent_profile.setToolTip(
            "开启后机器人按所选档案的功能层运行（李清菡：群管/语音/图片/游戏/记忆等）")
        av.addWidget(self.chk_agent_profile)

        profile_row = QHBoxLayout()
        profile_lbl = QLabel("档案选择")
        profile_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.agent_profile_combo = QComboBox()
        for prof in agent_profile.list_profiles():
            self.agent_profile_combo.addItem(prof["name"], prof["id"])
        self.agent_profile_combo.setToolTip("星群助手 = 默认行为；李清菡 = 完整功能层预设")
        profile_row.addWidget(profile_lbl)
        profile_row.addWidget(self.agent_profile_combo, 1)
        av.addLayout(profile_row)

        wake_row = QHBoxLayout()
        wake_lbl = QLabel("唤醒词")
        wake_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.agent_wake_edit = QLineEdit()
        self.agent_wake_edit.setPlaceholderText(
            "逗号分隔，如：李清菡,学姐,菡姐,菡菡（留空 = 档案默认）")
        self.agent_wake_edit.textEdited.connect(self._on_wake_edited)
        wake_row.addWidget(wake_lbl)
        wake_row.addWidget(self.agent_wake_edit, 1)
        self.btn_wake_generate = QPushButton("按人格生成")
        self.btn_wake_generate.setObjectName("ghost")
        self.btn_wake_generate.setToolTip(
            "用上方语言模型按人格文本生成唤醒词；未配置模型时自动按名字句式提取")
        self.btn_wake_generate.clicked.connect(self._start_wake_generation)
        wake_row.addWidget(self.btn_wake_generate)
        av.addLayout(wake_row)

        self.chk_wake_auto = QCheckBox("人格变化时自动重新生成唤醒词（手动修改唤醒词后自动取消）")
        av.addWidget(self.chk_wake_auto)

        owner_row = QHBoxLayout()
        owner_lbl = QLabel("你同学 openid")
        owner_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.agent_owner_edit = QLineEdit()
        self.agent_owner_edit.setPlaceholderText(
            "你的官方 openid（先用你的账号与机器人对话，从消息中心会话标识复制；留空 = 群管专属命令降级）")
        owner_row.addWidget(owner_lbl)
        owner_row.addWidget(self.agent_owner_edit, 1)
        av.addLayout(owner_row)

        vision_tip = QLabel("视觉模型（图片描述/生成；密钥留空 = 不启用）")
        vision_tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        av.addWidget(vision_tip)
        v_url_row = QHBoxLayout()
        v_url_lbl = QLabel("视觉接口地址")
        v_url_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.vision_url_edit = QLineEdit()
        self.vision_url_edit.setPlaceholderText("https://api.siliconflow.cn/v1")
        v_url_row.addWidget(v_url_lbl)
        v_url_row.addWidget(self.vision_url_edit, 1)
        av.addLayout(v_url_row)
        v_model_row = QHBoxLayout()
        v_model_lbl = QLabel("视觉模型")
        v_model_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.vision_model_edit = QLineEdit()
        self.vision_model_edit.setPlaceholderText("Qwen/Qwen3-Omni-30B-A3B-Instruct")
        v_model_row.addWidget(v_model_lbl)
        v_model_row.addWidget(self.vision_model_edit, 1)
        av.addLayout(v_model_row)
        v_key_row = QHBoxLayout()
        v_key_lbl = QLabel("视觉 API 密钥")
        v_key_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.vision_key_edit = QLineEdit()
        self.vision_key_edit.setEchoMode(QLineEdit.Password)
        self.vision_key_edit.setPlaceholderText("sk-...")
        v_key_row.addWidget(v_key_lbl)
        v_key_row.addWidget(self.vision_key_edit, 1)
        av.addLayout(v_key_row)
        outer.addWidget(agent_panel)

        # ---- 人设工坊（本地）：用户自制人格卡 + 工具 ----
        workshop_panel = GlassPanel(strong=True)
        self._workshop_panel = workshop_panel
        wv = QVBoxLayout(workshop_panel)
        wv.setContentsMargins(18, 14, 18, 16)
        wv.setSpacing(10)
        w_lbl = QLabel("人设工坊（本地）")
        w_lbl.setObjectName("sectionTitle")
        wv.addWidget(w_lbl)
        w_tip = QLabel(
            "上传自己的「人格卡 + 工具」人设包（和内置李清菡 / EVA 同一种模式）："
            "先下载模板填写，再导入 JSON 或 zip；启用后写入人格并加载自带工具，"
            "保存重启机器人生效。启用本地人设会自动关闭上方智能体档案，避免双人格。")
        w_tip.setWordWrap(True)
        w_tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        wv.addWidget(w_tip)
        ws_btns = QHBoxLayout()
        ws_btns.setSpacing(6)
        self.btn_persona_template = QPushButton("下载模板")
        self.btn_persona_template.setObjectName("ghost")
        self.btn_persona_template.setMinimumHeight(30)
        self.btn_persona_template.clicked.connect(self._download_persona_template)
        self.btn_persona_import = QPushButton("导入人设")
        self.btn_persona_import.setObjectName("primary")
        self.btn_persona_import.setMinimumHeight(30)
        self.btn_persona_import.clicked.connect(self._import_persona)
        self.btn_persona_guide = QPushButton("模板说明")
        self.btn_persona_guide.setObjectName("ghost")
        self.btn_persona_guide.setMinimumHeight(30)
        self.btn_persona_guide.clicked.connect(self._show_persona_guide)
        self.btn_persona_refresh = QPushButton("刷新")
        self.btn_persona_refresh.setObjectName("ghost")
        self.btn_persona_refresh.setMinimumHeight(30)
        self.btn_persona_refresh.clicked.connect(self._refresh_persona_list)
        ws_btns.addWidget(self.btn_persona_template)
        ws_btns.addWidget(self.btn_persona_guide)
        ws_btns.addWidget(self.btn_persona_import)
        ws_btns.addWidget(self.btn_persona_refresh)
        ws_btns.addStretch(1)
        wv.addLayout(ws_btns)
        self.persona_list = QListWidget()
        self.persona_list.setMaximumHeight(110)
        wv.addWidget(self.persona_list)
        ws_act = QHBoxLayout()
        ws_act.setSpacing(6)
        self.btn_persona_activate = QPushButton("启用")
        self.btn_persona_activate.setObjectName("ghost")
        self.btn_persona_activate.setMinimumHeight(30)
        self.btn_persona_activate.clicked.connect(self._activate_persona)
        self.btn_persona_deactivate = QPushButton("停用本地人设")
        self.btn_persona_deactivate.setObjectName("ghost")
        self.btn_persona_deactivate.setMinimumHeight(30)
        self.btn_persona_deactivate.clicked.connect(self._deactivate_persona)
        self.btn_persona_uninstall = QPushButton("卸载")
        self.btn_persona_uninstall.setObjectName("ghost")
        self.btn_persona_uninstall.setMinimumHeight(30)
        self.btn_persona_uninstall.clicked.connect(self._uninstall_persona)
        ws_act.addWidget(self.btn_persona_activate)
        ws_act.addWidget(self.btn_persona_deactivate)
        ws_act.addWidget(self.btn_persona_uninstall)
        ws_act.addStretch(1)
        wv.addLayout(ws_act)
        outer.addWidget(workshop_panel)

        # ---- 人设与主动聊天（程序内设置，不再走聊天指令） ----
        persona_panel = GlassPanel(strong=True)
        pv = QVBoxLayout(persona_panel)
        pv.setContentsMargins(18, 14, 18, 16)
        pv.setSpacing(10)
        p_lbl = QLabel("人设与主动聊天")
        p_lbl.setObjectName("sectionTitle")
        pv.addWidget(p_lbl)
        p_tip = QLabel("原 ac 指令已移除，改在这里配置；保存后重启机器人生效。")
        p_tip.setWordWrap(True)
        p_tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        pv.addWidget(p_tip)

        persona_row = QHBoxLayout()
        persona_lbl = QLabel("人格设定")
        persona_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        persona_lbl.setAlignment(Qt.AlignTop)
        self.ai_personality_edit = QPlainTextEdit()
        self.ai_personality_edit.setPlaceholderText("机器人的人设/性格，例如：你是 AstroSwarm 星群内置 AI 助手，回答简洁直接…")
        self.ai_personality_edit.setFixedHeight(84)
        persona_row.addWidget(persona_lbl)
        persona_row.addWidget(self.ai_personality_edit, 1)
        pv.addLayout(persona_row)

        self.chk_proactive = QCheckBox("启用主动聊天（机器人会不定时主动找用户聊天）")
        pv.addWidget(self.chk_proactive)

        targets_row = QHBoxLayout()
        targets_lbl = QLabel("目标用户")
        targets_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.ai_proactive_targets = QLineEdit()
        self.ai_proactive_targets.setPlaceholderText("QQ 官方 openid，多个用逗号分隔（留空 = 无目标；先用目标账号与机器人对话获取 openid）")
        targets_row.addWidget(targets_lbl)
        targets_row.addWidget(self.ai_proactive_targets, 1)
        pv.addLayout(targets_row)

        groups_row = QHBoxLayout()
        groups_lbl = QLabel("搭话群聊")
        groups_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        self.ai_proactive_groups = QLineEdit()
        self.ai_proactive_groups.setPlaceholderText("QQ 群 openid，多个用逗号分隔（留空 = 不搭话；机器人需已在群内接收过消息）")
        groups_row.addWidget(groups_lbl)
        groups_row.addWidget(self.ai_proactive_groups, 1)
        pv.addLayout(groups_row)

        nums_grid = QGridLayout()
        nums_grid.setHorizontalSpacing(12)
        nums_grid.setVerticalSpacing(6)
        nums_grid.addWidget(self._spin("间隔最小(分)", "ai_interval_min", 1, 1440, 30), 0, 0)
        nums_grid.addWidget(self._spin("间隔最大(分)", "ai_interval_max", 1, 1440, 90), 0, 1)
        nums_grid.addWidget(self._spin("冷却(分)", "ai_cooldown", 1, 1440, 30), 0, 2)
        nums_grid.addWidget(self._spin("免打扰开始(时)", "ai_quiet_start", 0, 23, 0), 1, 0)
        nums_grid.addWidget(self._spin("免打扰结束(时)", "ai_quiet_end", 0, 23, 8), 1, 1)
        nums_grid.setColumnStretch(3, 1)
        pv.addLayout(nums_grid)
        outer.addWidget(persona_panel)

        # ---- 记忆与 MCP ----
        mem_panel = GlassPanel(strong=True)
        self._mem_panel = mem_panel
        mv = QVBoxLayout(mem_panel)
        mv.setContentsMargins(18, 14, 18, 16)
        mv.setSpacing(10)
        m_lbl = QLabel("记忆与 MCP")
        m_lbl.setObjectName("sectionTitle")
        mv.addWidget(m_lbl)
        self.chk_memory = QCheckBox("启用全局记忆（默认开启，AI 会记住长期事项）")
        mv.addWidget(self.chk_memory)
        self.chk_mcp = QCheckBox("启用 MCP 工具（供 AI 调用外部服务器）")
        mv.addWidget(self.chk_mcp)
        mcp_row = QHBoxLayout()
        mcp_lbl = QLabel("MCP 服务器")
        mcp_lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        mcp_lbl.setAlignment(Qt.AlignTop)
        self.mcp_json_edit = QPlainTextEdit()
        self.mcp_json_edit.setPlaceholderText(
            '{\n  "服务器名": {"type": "sse", "enabled": true, "url": "http://127.0.0.1:8000/sse", "headers": {}}\n}')
        self.mcp_json_edit.setFixedHeight(96)
        mcp_row.addWidget(mcp_lbl)
        mcp_row.addWidget(self.mcp_json_edit, 1)
        mv.addLayout(mcp_row)
        mcp_hint = QLabel("JSON 格式：sse 用 url/headers；stdio 用 command/args/env；保存后重启机器人生效。")
        mcp_hint.setWordWrap(True)
        mcp_hint.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        mv.addWidget(mcp_hint)

        mem_tip = QLabel(
            "记忆时间线：这里读的是李清菡智能体档案的记忆库"
            "（bot/data/liqinghan/agent.db），可导出 / 单条删除 / 清空。\n"
            "内置 AI 插件的全局记忆在另一个文件（bot/data/ai/aichat_memory.json），"
            "首页「记忆条数」与控制台时间线统计的是那一份；两份互不影响。")
        mem_tip.setWordWrap(True)
        mem_tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        mv.addWidget(mem_tip)
        self.memory_list = QListWidget()
        self.memory_list.setMaximumHeight(130)
        mv.addWidget(self.memory_list)
        mem_btns = QHBoxLayout()
        mem_btns.setSpacing(6)
        self.btn_memory_refresh = QPushButton("刷新")
        self.btn_memory_refresh.setObjectName("ghost")
        self.btn_memory_refresh.setMinimumHeight(30)
        self.btn_memory_refresh.clicked.connect(self._refresh_memory_list)
        self.btn_memory_export = QPushButton("导出记忆")
        self.btn_memory_export.setObjectName("ghost")
        self.btn_memory_export.setMinimumHeight(30)
        self.btn_memory_export.clicked.connect(self._export_memory)
        self.btn_memory_delete = QPushButton("删除选中")
        self.btn_memory_delete.setObjectName("ghost")
        self.btn_memory_delete.setMinimumHeight(30)
        self.btn_memory_delete.clicked.connect(self._delete_memory)
        self.btn_memory_clear = QPushButton("清空")
        self.btn_memory_clear.setObjectName("ghost")
        self.btn_memory_clear.setMinimumHeight(30)
        self.btn_memory_clear.clicked.connect(self._clear_memory)
        mem_btns.addWidget(self.btn_memory_refresh)
        mem_btns.addWidget(self.btn_memory_export)
        mem_btns.addWidget(self.btn_memory_delete)
        mem_btns.addWidget(self.btn_memory_clear)
        mem_btns.addStretch(1)
        mv.addLayout(mem_btns)

        # ---- 内置 AI 插件的全局记忆（另一个文件，与控制台同一份）----
        self.ai_mem_tip = QLabel("内置 AI 记忆（全局）：读取 bot/data/ai/aichat_memory.json，"
                                 "可导出 / 单条删除 / 清空全局。")
        self.ai_mem_tip.setWordWrap(True)
        self.ai_mem_tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        mv.addWidget(self.ai_mem_tip)
        self.ai_mem_list = QListWidget()
        self.ai_mem_list.setMaximumHeight(130)
        mv.addWidget(self.ai_mem_list)
        ai_mem_btns = QHBoxLayout()
        ai_mem_btns.setSpacing(8)
        self.btn_ai_mem_refresh = QPushButton("刷新")
        self.btn_ai_mem_refresh.setObjectName("ghost")
        self.btn_ai_mem_refresh.setMinimumHeight(30)
        self.btn_ai_mem_refresh.clicked.connect(self._refresh_ai_memory)
        self.btn_ai_mem_export = QPushButton("导出")
        self.btn_ai_mem_export.setObjectName("ghost")
        self.btn_ai_mem_export.setMinimumHeight(30)
        self.btn_ai_mem_export.clicked.connect(self._export_ai_memory)
        self.btn_ai_mem_delete = QPushButton("删除选中")
        self.btn_ai_mem_delete.setObjectName("ghost")
        self.btn_ai_mem_delete.setMinimumHeight(30)
        self.btn_ai_mem_delete.clicked.connect(self._delete_ai_memory)
        self.btn_ai_mem_clear = QPushButton("清空全局")
        self.btn_ai_mem_clear.setObjectName("ghost")
        self.btn_ai_mem_clear.setMinimumHeight(30)
        self.btn_ai_mem_clear.clicked.connect(self._clear_ai_memory)
        ai_mem_btns.addWidget(self.btn_ai_mem_refresh)
        ai_mem_btns.addWidget(self.btn_ai_mem_export)
        ai_mem_btns.addWidget(self.btn_ai_mem_delete)
        ai_mem_btns.addWidget(self.btn_ai_mem_clear)
        ai_mem_btns.addStretch(1)
        mv.addLayout(ai_mem_btns)

        kb_tip = QLabel(
            "本地知识库：上传 txt / md 文档，AI 可调用 knowledge_search 检索回答（数据不出本机）。")
        kb_tip.setWordWrap(True)
        kb_tip.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        mv.addWidget(kb_tip)
        self.kb_list = QListWidget()
        self.kb_list.setMaximumHeight(90)
        mv.addWidget(self.kb_list)
        kb_btns = QHBoxLayout()
        kb_btns.setSpacing(6)
        self.btn_kb_add = QPushButton("添加文档")
        self.btn_kb_add.setObjectName("primary")
        self.btn_kb_add.setMinimumHeight(30)
        self.btn_kb_add.clicked.connect(self._kb_add)
        self.btn_kb_refresh = QPushButton("刷新")
        self.btn_kb_refresh.setObjectName("ghost")
        self.btn_kb_refresh.setMinimumHeight(30)
        self.btn_kb_refresh.clicked.connect(self._refresh_kb_list)
        self.btn_kb_delete = QPushButton("删除选中")
        self.btn_kb_delete.setObjectName("ghost")
        self.btn_kb_delete.setMinimumHeight(30)
        self.btn_kb_delete.clicked.connect(self._kb_delete)
        kb_btns.addWidget(self.btn_kb_add)
        kb_btns.addWidget(self.btn_kb_refresh)
        kb_btns.addWidget(self.btn_kb_delete)
        kb_btns.addStretch(1)
        mv.addLayout(kb_btns)
        outer.addWidget(mem_panel)

        # ---- 状态摘要（只读） ----
        self.summary_panel = GlassPanel()
        sv = QVBoxLayout(self.summary_panel)
        sv.setContentsMargins(18, 14, 18, 16)
        self.summary_labels = {}
        keys = [
            ("model", "当前模型"),
            ("mcp", "MCP"),
            ("memory_global", "全局记忆"),
            ("memory_users", "用户记忆"),
            ("identity", "身份绑定"),
        ]
        for key, label in keys:
            val = QLabel("—")
            val.setWordWrap(True)
            val.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
            self.summary_labels[key] = val
            sv.addLayout(make_row(label, val))
        btns = QHBoxLayout()
        btn_env = QPushButton("打开 .env")
        btn_env.clicked.connect(lambda: os.startfile(str(self.ctx.settings.bot_env_file)))
        btn_plugins = QPushButton("打开插件目录")
        btn_plugins.clicked.connect(lambda: os.startfile(str(self.ctx.settings.plugins_dir)))
        btns.addWidget(btn_env)
        btns.addWidget(btn_plugins)
        btns.addStretch(1)
        sv.addLayout(btns)
        outer.addWidget(self.summary_panel)

        self.empty = EmptyState("加载中", "")
        outer.addWidget(self.empty, 1)

        self.ai_provider_combo.currentIndexChanged.connect(self._on_ai_provider_changed)
        self.scroll.setWidget(content)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.scroll)
        self.set_beginner(bool(self.ctx.settings.beginner_mode))

    def set_beginner(self, on: bool):
        """小白模式：AI 大脑只保留接口配置、人设与状态摘要，隐藏档案/MCP/未接入平台。"""
        on = bool(on)
        for w in (getattr(self, "_agent_panel", None),
                  getattr(self, "_workshop_panel", None),
                  getattr(self, "_mem_panel", None)):
            if w is not None:
                w.setVisible(not on)
        self.chk_feishu.setVisible(not on)
        self.chk_telegram.setVisible(not on)

    def _spin(self, label: str, attr: str, lo: int, hi: int, default: int) -> QWidget:
        """创建一个“标签在上、数字在下”的整数输入框，固定宽度不会被挤压。"""
        w = QWidget()
        w.setFixedWidth(118)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {TEXT_3}; font-size: 12px;")
        lbl.setAlignment(Qt.AlignHCenter)
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(default)
        spin.setFixedWidth(96)
        spin.setAlignment(Qt.AlignCenter)
        setattr(self, attr, spin)
        lay.addWidget(lbl)
        lay.addWidget(spin, 0, Qt.AlignHCenter)
        return w

    # ------------------------------------------------------------ 配置
    def load_config(self):
        """把已保存的 AI 配置与平台开关填入控件（仅页面初始化时调用）。"""
        s = self.ctx.settings
        platforms = getattr(s, "ai_platforms", None)
        if not isinstance(platforms, dict):
            platforms = {}
        self.chk_qq.setChecked(platforms.get("qq", True))
        self.chk_wechat.setChecked(platforms.get("wechat", True))
        self.chk_feishu.setChecked(platforms.get("feishu", True))
        self.chk_telegram.setChecked(platforms.get("telegram", True))

        cfg = ai_config.current_config(s)
        self.ai_url_edit.setText(str(cfg.get("api_url") or ""))
        self.ai_model_edit.setText(str(cfg.get("model") or ""))
        self.ai_key_edit.setText(str(cfg.get("api_key") or ""))
        key = ai_config.provider_key_for_url(str(cfg.get("api_url") or ""))
        idx = self.ai_provider_combo.findData(key)
        self.ai_provider_combo.setCurrentIndex(idx if idx >= 0 else 0)

        # 人设与主动聊天（程序内设置）
        self.ai_personality_edit.setPlainText(ai_config.read_personality(s))
        pro = ai_config.read_proactive(s)
        self.chk_proactive.setChecked(pro["enabled"])
        self.ai_proactive_targets.setText(", ".join(pro["targets"]))
        self.ai_proactive_groups.setText(", ".join(pro["groups"]))
        self.ai_interval_min.setValue(pro["interval_min"])
        self.ai_interval_max.setValue(pro["interval_max"])
        self.ai_cooldown.setValue(pro["cooldown"])
        self.ai_quiet_start.setValue(pro["quiet_start"])
        self.ai_quiet_end.setValue(pro["quiet_end"])

        # 记忆与 MCP（程序内设置）
        self.chk_memory.setChecked(ai_config.read_memory_enabled(s))
        mcp = ai_config.read_mcp(s)
        self.chk_mcp.setChecked(mcp["enabled"])
        self.mcp_json_edit.setPlainText(
            json.dumps(mcp["servers"], ensure_ascii=False, indent=2)
            if mcp["servers"] else "")
        # 智能体档案
        self.chk_agent_profile.setChecked(s.agent_profile_enabled)
        idx = self.agent_profile_combo.findData(s.agent_profile_id)
        self.agent_profile_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.agent_wake_edit.setText(", ".join(s.agent_wake_words))
        self.chk_wake_auto.setChecked(s.agent_wake_auto)
        self.agent_owner_edit.setText(s.agent_owner_openid)
        self.vision_url_edit.setText(s.vision_api_url)
        self.vision_model_edit.setText(s.vision_model)
        self.vision_key_edit.setText(s.vision_api_key)
        self._loaded_persona = ai_config.read_personality(s)
        self._loaded_agent_cfg = _agent_cfg_snapshot(s)

    def _on_ai_provider_changed(self):
        key = self.ai_provider_combo.currentData() or "custom"
        for p in ai_config.AI_PROVIDERS:
            if p["key"] == key:
                if p["url"]:
                    self.ai_url_edit.setText(p["url"])
                if p["model"]:
                    self.ai_model_edit.setText(p["model"])
                break

    def _save_config(self):
        s = self.ctx.settings
        s.ai_platforms = {
            "qq": self.chk_qq.isChecked(),
            "wechat": self.chk_wechat.isChecked(),
            "feishu": self.chk_feishu.isChecked(),
            "telegram": self.chk_telegram.isChecked(),
        }
        s.agent_profile_enabled = self.chk_agent_profile.isChecked()
        s.agent_profile_id = str(self.agent_profile_combo.currentData()
                                 or agent_profile.DEFAULT_PROFILE_ID)
        s.agent_wake_words = _split_csv(self.agent_wake_edit.text())
        s.agent_wake_auto = self.chk_wake_auto.isChecked()
        s.agent_owner_openid = self.agent_owner_edit.text().strip()
        s.vision_api_url = self.vision_url_edit.text().strip()
        s.vision_api_key = self.vision_key_edit.text().strip()
        s.vision_model = self.vision_model_edit.text().strip()
        ai_ok = ai_config.save_config(
            s,
            api_key=self.ai_key_edit.text().strip(),
            api_url=self.ai_url_edit.text().strip(),
            model=self.ai_model_edit.text().strip(),
        )

        persona_ok = ai_config.save_personality(
            s, self.ai_personality_edit.toPlainText())
        pro_ok = ai_config.save_proactive(
            s,
            enabled=self.chk_proactive.isChecked(),
            targets=_split_csv(self.ai_proactive_targets.text()),
            groups=_split_csv(self.ai_proactive_groups.text()),
            interval_min=self.ai_interval_min.value(),
            interval_max=self.ai_interval_max.value(),
            cooldown=self.ai_cooldown.value(),
            quiet_start=self.ai_quiet_start.value(),
            quiet_end=self.ai_quiet_end.value(),
        )
        memory_ok = ai_config.save_memory_enabled(
            s, self.chk_memory.isChecked())
        try:
            servers = json.loads(self.mcp_json_edit.toPlainText().strip() or "{}")
        except ValueError as e:
            self.ctx.show_toast("MCP 配置不是合法 JSON：" + str(e))
            return
        try:
            servers = ai_config.normalize_mcp_servers(servers)
        except ValueError as e:
            # 逐项校验（与无头端 console_ext.mcp_save 同一套规则）：以前只查「是不是对象」，
            # type 写错 / stdio 没填 command 都照样存盘，机器人重启后 MCP 起不来只能自己猜
            self.ctx.show_toast("MCP 配置有问题：" + str(e))
            return
        mcp_ok = ai_config.save_mcp(
            s, self.chk_mcp.isChecked(), servers)
        try:
            s.save()
        except OSError as e:
            self.ctx.show_toast("保存 AI 配置失败: " + str(e))
            return
        self.refresh_status()
        fails = []
        if not ai_ok:
            fails.append("接口")
        if not persona_ok:
            fails.append("人设")
        if not pro_ok:
            fails.append("主动聊天")
        if not memory_ok:
            fails.append("记忆")
        if not mcp_ok:
            fails.append("MCP")
        self.ctx.show_toast(
            ("AI 配置已保存，重启机器人生效"
             + ("" if not fails else f"（{'、'.join(fails)}写入失败，请检查目录权限）")))
        before = dict(self._loaded_agent_cfg)
        after = _agent_cfg_snapshot(s)
        self._loaded_agent_cfg = after
        if _agent_restart_required(before, after):
            self._auto_restart_agent()
        self._maybe_auto_wake_generation(s)

    # ------------------------------------------------------------ 智能体档案
    def _auto_restart_agent(self):
        """档案/模型相关配置变化后自动重启 NoneBot，让新档案真正载入。"""
        if self.ctx.tasks is None:
            self.ctx.show_toast("AI 配置已保存，请手动重启 NoneBot 载入新档案")
            return
        from ...tasks.workers import RestartBotTask
        self.ctx.show_toast("AI 配置已保存，正在自动重启 NoneBot 载入新档案...")
        self.ctx.tasks.submit(
            "重启 NoneBot（载入智能体档案）", "service", RestartBotTask,
            retryable=True, manager=self.ctx.manager,
        )

    def _on_wake_edited(self, _text):
        """手动改唤醒词 = 关闭自动覆盖，防止下次保存冲掉人工维护的词。"""
        self.chk_wake_auto.setChecked(False)

    # ------------------------------------------------------------ 人设工坊（本地）
    def _download_persona_template(self):
        from ...core import persona_workshop
        path, _ = QFileDialog.getSaveFileName(
            self, "保存人设模板",
            str(os.path.join(os.path.expanduser("~"), "persona-card-template.json")),
            "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(persona_workshop.template_text())
        except OSError as e:
            self.ctx.show_toast("保存模板失败：" + str(e))
            return
        self.ctx.show_toast("模板已保存，填好后点「导入人设」")

    def _show_persona_guide(self):
        """打开模板说明文档（图文教程）。"""
        from ...core import persona_workshop
        dlg = QDialog(self)
        dlg.setWindowTitle("人格卡模板说明")
        dlg.resize(680, 720)
        lay = QVBoxLayout(dlg)
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(persona_workshop.guide_text())
        lay.addWidget(edit)
        dlg.show()

    def _import_persona(self):
        from ...core import persona_workshop
        path, _ = QFileDialog.getOpenFileName(
            self, "导入人设", "",
            "人设包 (*.json *.zip);;JSON 人格卡 (*.json);;ZIP 人设包 (*.zip)")
        if not path:
            return
        worker = Worker(self)
        worker.finished.connect(self._on_persona_imported)
        threading.Thread(
            target=lambda: worker.run(
                lambda: persona_workshop.install_persona(self.ctx.settings, path)),
            daemon=True,
        ).start()

    def _on_persona_imported(self, res):
        if isinstance(res, dict) and res.get("ok"):
            self.ctx.show_toast(f"人设已导入：{res.get('name')}，选中后点「启用」")
        else:
            detail = (res.get("error") if isinstance(res, dict) else "") or "导入失败"
            self.ctx.show_toast("导入失败：" + str(detail))
        self._refresh_persona_list()

    def _refresh_persona_list(self):
        from ...core import persona_workshop
        self.persona_list.clear()
        for p in persona_workshop.list_personas(self.ctx.settings):
            mark = "（启用中）" if p["active"] else ""
            tools = "、".join(p["tools"]) if p["tools"] else "无工具"
            item = QListWidgetItem(
                f"{p['name']} v{p['version']}{mark}  [工具：{tools}]")
            item.setData(Qt.UserRole, p["id"])
            item.setToolTip(p["summary"])
            self.persona_list.addItem(item)

    def _activate_persona(self):
        from ...core import persona_workshop
        item = self.persona_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个人设")
            return
        pid = str(item.data(Qt.UserRole) or "")
        try:
            res = persona_workshop.activate_persona(self.ctx.settings, pid)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "启用失败", str(e))
            return
        self._loaded_persona = ai_config.read_personality(self.ctx.settings)
        self.ai_personality_edit.setPlainText(self._loaded_persona)
        self.chk_agent_profile.setChecked(False)
        self._refresh_persona_list()
        self.ctx.show_toast(f"已启用人设：{res.get('name')}，重启机器人后生效")

    def _deactivate_persona(self):
        from ...core import persona_workshop
        try:
            persona_workshop.deactivate_persona(self.ctx.settings)
        except OSError as e:
            self.ctx.show_toast("停用失败：" + str(e))
            return
        self._refresh_persona_list()
        self.ctx.show_toast("已停用本地人设")

    def _uninstall_persona(self):
        from ...core import persona_workshop
        item = self.persona_list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先选择一个人设")
            return
        pid = str(item.data(Qt.UserRole) or "")
        ret = QMessageBox.question(
            self, "卸载人设", f"确定卸载「{item.text()}」吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        try:
            persona_workshop.uninstall_persona(self.ctx.settings, pid)
        except OSError as e:
            self.ctx.show_toast("卸载失败：" + str(e))
            return
        self._refresh_persona_list()
        self.ctx.show_toast("人设已卸载")

    # ------------------------------------------------------------ 记忆时间线
    def _memory_db(self):
        p = self.ctx.settings.root / "bot" / "data" / "liqinghan" / "agent.db"
        return p if p.exists() else None

    def _backup_memory_db(self) -> str:
        """删除/清空前把记忆库整份复制一份（与内置 AI 全局记忆同一套做法）。

        sqlite 里删掉就是真删掉了，事后没法从日志里还原 —— 先留 .bak 才敢让用户点删除。
        """
        import shutil

        dbp = self._memory_db()
        if dbp is None:
            return ""
        bak = dbp.with_name(f"{dbp.name}.bak.{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            shutil.copy2(dbp, bak)
            return str(bak)
        except OSError:
            return ""

    def _refresh_memory_list(self):
        import sqlite3
        self.memory_list.clear()
        dbp = self._memory_db()
        if dbp is None:
            self.memory_list.addItem(
                "（暂无记忆库：启用李清菡 / 本地人设并聊过天后会生成）")
            return
        try:
            conn = sqlite3.connect(str(dbp))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT m.id, m.qq, m.fact, m.ts, u.nickname FROM memories m "
                "LEFT JOIN users u ON u.qq=m.qq ORDER BY m.ts DESC LIMIT 200"
            ).fetchall()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.memory_list.addItem("（读取记忆失败：" + str(e) + "）")
            return
        for r in rows:
            ts = (time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ts"]))
                  if r["ts"] else "?")
            nick = r["nickname"] or r["qq"] or "?"
            item = QListWidgetItem(f"[{ts}] {nick}：{str(r['fact'])[:80]}")
            item.setData(Qt.UserRole, r["id"])
            item.setToolTip(str(r["fact"]))
            self.memory_list.addItem(item)

    def _export_memory(self):
        import json as _json
        import sqlite3
        dbp = self._memory_db()
        if dbp is None:
            self.ctx.show_toast("暂无记忆库")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出记忆",
            str(os.path.join(os.path.expanduser("~"), "星群记忆导出.json")),
            "JSON 文件 (*.json)")
        if not path:
            return
        try:
            conn = sqlite3.connect(str(dbp))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT m.qq, m.fact, m.ts, u.nickname FROM memories m "
                "LEFT JOIN users u ON u.qq=m.qq ORDER BY m.ts DESC").fetchall()
            conn.close()
            data = {
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "count": len(rows),
                "items": [dict(r) for r in rows],
            }
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            self.ctx.show_toast("导出失败：" + str(e))
            return
        self.ctx.show_toast(f"已导出 {len(rows)} 条记忆")

    def _delete_memory(self):
        import sqlite3
        item = self.memory_list.currentItem()
        if not item or item.data(Qt.UserRole) is None:
            QMessageBox.information(self, "提示", "请先选择一条记忆")
            return
        dbp = self._memory_db()
        if dbp is None:
            return
        backup = self._backup_memory_db()
        try:
            conn = sqlite3.connect(str(dbp))
            conn.execute("DELETE FROM memories WHERE id=?",
                         (item.data(Qt.UserRole),))
            conn.commit()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.ctx.show_toast("删除失败：" + str(e))
            return
        self._refresh_memory_list()
        self.ctx.show_toast(
            f"已删除该条记忆（原库已备份为 {os.path.basename(backup)}）" if backup
            else "已删除该条记忆")

    def _clear_memory(self):
        import sqlite3
        dbp = self._memory_db()
        if dbp is None:
            return
        ret = QMessageBox.question(
            self, "清空记忆",
            "确定清空全部记忆吗？\n清空前会自动把记忆库整份备份一份（agent.db.bak.<时间>）。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        backup = self._backup_memory_db()
        try:
            conn = sqlite3.connect(str(dbp))
            conn.execute("DELETE FROM memories")
            conn.commit()
            conn.close()
        except Exception as e:  # noqa: BLE001
            self.ctx.show_toast("清空失败：" + str(e))
            return
        self._refresh_memory_list()
        self.ctx.show_toast(
            f"记忆已清空（原库已备份为 {os.path.basename(backup)}）" if backup
            else "记忆已清空（未能备份，请检查目录权限）")

    # ------------------------------------------------------ 内置 AI 全局记忆
    def _refresh_ai_memory(self):
        """读内置 AI 插件的全局记忆（另一个文件，与控制台同一份）。"""
        from ...core import ai_memory

        self.ai_mem_list.clear()
        try:
            info = ai_memory.summary(self.ctx.settings)
        except ValueError as exc:
            # 文件坏了必须说出来，不能显示成「没有记忆」（否则保存会覆盖掉）
            self.ai_mem_tip.setText("内置 AI 记忆读取失败：" + str(exc))
            self.ctx.show_toast("内置 AI 记忆读取失败，见说明文字")
            return
        self.ai_mem_tip.setText(
            f"内置 AI 记忆（全局）：共 {info['total']} 条"
            f"（全局 {info['global_count']} 条、{len(info['users'])} 个用户）"
            f" · {info['file']}")
        if not info["total"]:
            self.ai_mem_list.addItem("（还没有记忆；AI 聊到值得长期记住的事才会写进来）")
            return
        for idx, entry in enumerate(info["global"]):
            item = QListWidgetItem("· " + ai_memory.item_text(entry))
            item.setData(Qt.UserRole, ("global", "", idx))
            self.ai_mem_list.addItem(item)
        for group in info["users"]:
            head = QListWidgetItem(f"— 用户 {group['user']}（{group['count']} 条）")
            head.setData(Qt.UserRole, None)
            self.ai_mem_list.addItem(head)
            base = group["count"] - len(group["items"])
            for idx, entry in enumerate(group["items"]):
                item = QListWidgetItem("   · " + ai_memory.item_text(entry))
                item.setData(Qt.UserRole, ("user", group["user"], base + idx))
                self.ai_mem_list.addItem(item)

    def _export_ai_memory(self):
        from ...core import ai_memory

        try:
            _name, body = ai_memory.export_text(self.ctx.settings, "md")
        except ValueError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出内置 AI 记忆",
            os.path.join(os.path.expanduser("~"), "星群AI记忆时间线.md"),
            "Markdown (*.md);;JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(body)
        except OSError as exc:
            self.ctx.show_toast("导出失败：" + str(exc))
            return
        self.ctx.show_toast("已导出到 " + path)

    def _delete_ai_memory(self):
        from ...core import ai_memory

        item = self.ai_mem_list.currentItem()
        if not item or item.data(Qt.UserRole) is None:
            QMessageBox.information(self, "提示", "请先选择一条记忆（标题行和设备行不能删）")
            return
        scope, user, index = item.data(Qt.UserRole)
        if not self._confirm_ai_memory("删除这条记忆", f"确定删除这条记忆吗？\n\n{item.text().strip()}"):
            return
        try:
            res = ai_memory.delete(self.ctx.settings, scope, user, index)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        self._refresh_ai_memory()
        self.ctx.show_toast(f"已删除（原文件已备份到 {os.path.basename(res['backup'] or '（未备份）')}）")

    def _clear_ai_memory(self):
        from ...core import ai_memory

        if not self._confirm_ai_memory(
                "清空内置 AI 全局记忆",
                "将清空内置 AI 插件的「全局记忆」（用户记忆不动），改动前会自动备份。\n\n确定继续吗？"):
            return
        try:
            res = ai_memory.clear(self.ctx.settings, "global")
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "清空失败", str(exc))
            return
        self._refresh_ai_memory()
        self.ctx.show_toast(f"已清空 {res['removed']} 条全局记忆")

    def _confirm_ai_memory(self, title: str, text: str) -> bool:
        ret = QMessageBox.question(self, title, text,
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return ret == QMessageBox.Yes

    # ------------------------------------------------------------ 本地知识库
    def _refresh_kb_list(self):
        from ...core import knowledge_base
        self.kb_list.clear()
        docs = knowledge_base.list_documents(self.ctx.settings)
        if not docs:
            self.kb_list.addItem("（暂无文档，点「添加文档」上传 txt / md）")
            return
        for doc in docs:
            item = QListWidgetItem(f"{doc['title']}（{doc['chunks']} 段）")
            item.setData(Qt.UserRole, doc["id"])
            self.kb_list.addItem(item)

    def _kb_add(self):
        from ...core import knowledge_base
        path, _ = QFileDialog.getOpenFileName(
            self, "添加知识库文档", "",
            "文本 / Markdown (*.txt *.md);;所有文件 (*.*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            knowledge_base.add_document(
                self.ctx.settings, os.path.basename(path), text)
        except Exception as e:  # noqa: BLE001
            self.ctx.show_toast("添加失败：" + str(e))
            return
        self._refresh_kb_list()
        self.ctx.show_toast("文档已加入本地知识库，重启机器人后 AI 可检索")

    def _kb_delete(self):
        from ...core import knowledge_base
        item = self.kb_list.currentItem()
        if not item or item.data(Qt.UserRole) is None:
            QMessageBox.information(self, "提示", "请先选择一篇文档")
            return
        try:
            knowledge_base.delete_document(
                self.ctx.settings, str(item.data(Qt.UserRole)))
        except OSError as e:
            self.ctx.show_toast("删除失败：" + str(e))
            return
        self._refresh_kb_list()
        self.ctx.show_toast("文档已删除")

    def _maybe_auto_wake_generation(self, s):
        """人格变化且开了自动生成时，保存后后台重新生成唤醒词。"""
        persona = self.ai_personality_edit.toPlainText().strip()
        if (not s.agent_profile_enabled or not s.agent_wake_auto
                or not persona
                or persona == str(getattr(self, "_loaded_persona", "")).strip()):
            return
        self._start_wake_generation()

    def _start_wake_generation(self):
        """按人格生成唤醒词：语言模型一次调用，失败自动走正则/默认词兜底。"""
        s = self.ctx.settings
        cfg = ai_config.current_config(s)
        api_url = self.ai_url_edit.text().strip() or str(cfg.get("api_url") or "")
        api_key = self.ai_key_edit.text().strip() or str(cfg.get("api_key") or "")
        model = self.ai_model_edit.text().strip() or str(cfg.get("model") or "")
        persona = self.ai_personality_edit.toPlainText().strip()
        if not persona:
            self.ctx.show_toast("请先填写人格设定")
            return
        profile_id = str(self.agent_profile_combo.currentData()
                         or agent_profile.DEFAULT_PROFILE_ID)
        prof = agent_profile.load_profile(profile_id)
        default = list(prof["default_wake_words"]) if prof else []
        worker = Worker(self)
        worker.finished.connect(lambda res: self._on_wake_generated(res, default))
        threading.Thread(
            target=lambda: worker.run(lambda: {
                "words": agent_profile.generate_wake_words(
                    persona,
                    lambda prompt: agent_profile.openai_chat(
                        prompt, api_url, api_key, model),
                    default=default),
            }),
            daemon=True,
        ).start()
        self.btn_wake_generate.setEnabled(False)
        self.ctx.show_toast("正在按人格生成唤醒词...")

    def _on_wake_generated(self, res, default):
        self.btn_wake_generate.setEnabled(True)
        words = res.get("words") if isinstance(res, dict) else None
        if words:
            self.agent_wake_edit.setText(", ".join(words))
            self.chk_wake_auto.setChecked(True)
            self.ctx.show_toast("唤醒词已生成，可手动修改（保存后重启机器人生效）")
            return
        msg = str(res.get("error") or "无结果") if isinstance(res, dict) else "无结果"
        self.ctx.show_toast("唤醒词生成失败：" + msg + "，已保留原唤醒词")

    # ------------------------------------------------------------ 状态
    def refresh_status(self):
        s = self.ctx.settings
        summary = message_store.brain_summary(s)
        installed = (s.plugins_dir / "ai").is_dir()
        cfg = ai_config.current_config(s)
        configured = bool(cfg.get("api_key") and cfg.get("api_url") and cfg.get("model"))
        self.summary_panel.setVisible(installed)
        self.empty.setVisible(not installed)
        if not installed:
            self.empty.set_content(
                "未检测到内置 AI 插件",
                "重启一次机器人后，AstroSwarm 会自动把内置 ai 插件安装到插件目录，"
                "并在这里展示模型、MCP、记忆与身份绑定状态。")
            return
        if not getattr(s, "ai_enabled", True):
            self.summary_panel.setVisible(False)
            self.empty.setVisible(True)
            self.empty.set_content(
                "AI 插件已停用",
                "当前在「设置」页关闭了 AI 插件总开关，机器人启动时不会加载 AI 功能；"
                "接口配置与平台开关仍可在上方提前填好。")
            return
        if not configured:
            self.summary_panel.setVisible(False)
            self.empty.setVisible(True)
            self.empty.set_content(
                "尚未配置 AI 接口",
                "在上方选择服务商（DeepSeek/通义/智谱/Kimi/OpenAI 等），"
                "填入 API 密钥并保存，重启机器人生效。")
            return
        self.summary_labels["model"].setText(summary["model"] or "未配置")
        mcp = ("已开启" if summary["mcp_enabled"] else "未开启") + \
              f" · {summary['mcp_servers']} 个服务器"
        self.summary_labels["mcp"].setText(mcp)
        self.summary_labels["memory_global"].setText(f"{summary['memory_global']} 条")
        self.summary_labels["memory_users"].setText(f"{summary['memory_users']} 个用户")
        self.summary_labels["identity"].setText(f"{summary['identity_binds']} 组绑定")
        # 首页那两行统计的就是这份内置 AI 记忆，顺手把列表也刷新，别让两处对不上
        try:
            self._refresh_ai_memory()
        except Exception:  # noqa: BLE001 —— 刷新失败不该让整页报错
            pass
