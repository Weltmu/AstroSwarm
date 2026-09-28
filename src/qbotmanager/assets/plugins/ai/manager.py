import json
import os
from typing import List, Dict, Any
from nonebot import logger
try:
    from nonebot.adapters.onebot.v11 import MessageEvent
except Exception:  # noqa: BLE001  # 官方通道部署不装 OneBot 适配器，仅注解用
    MessageEvent = object
import nonebot_plugin_localstore as store
from .config import config

MANAGER_FILE = store.get_plugin_config_file("aichat_manager.json")
logger.info(f"[ai] 管理配置路径: {MANAGER_FILE}")

_DEFAULT_PERSONALITY = "你是星群（AstroSwarm）的 AI 助手，负责跨平台对话与记忆管理。回答保持简洁直接，情绪随心情波动，回答长短看情况，只给关键信息，不啰嗦。"


class ChatManager:
    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._load_manager_config()
    
    def _load_manager_config(self):
        """加载管理配置"""
        if os.path.exists(MANAGER_FILE):
            try:
                with open(MANAGER_FILE, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info("聊天管理器配置加载成功")
            except Exception as e:
                logger.error(f"加载聊天管理器配置失败: {e}")
                self._data = self._get_default_config()
        else:
            self._data = self._get_default_config()
            self._save_manager_config()
            logger.info("创建新的聊天管理器配置")
        self._merge_env_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "super_users": list(config.aichat_super_users),
            "enabled_groups": [],
            "chat_enabled": True,
            "group_chat_probability": 1,  # 群活跃度基础值
            "personality": _DEFAULT_PERSONALITY,
            "ai_configs": [],  # 改为数组形式，支持多个模型配置
            "current_ai_config": 0,  # 当前使用的配置索引
            "image_recognition_enabled": False,  # 图片识别功能开关
            "current_image_recognition_config": 0,  # 当前图片识别配置索引
            "enable_search": False,   # 是否启用搜索功能
            "mcp_enabled": False,     # MCP功能总开关
            "mcp_servers": {},
            # ===== 魔改新增：主动聊天配置 =====
            "proactive_enabled": False,  # 主动聊天总开关（默认关闭，需用命令开启）
            "proactive_targets": list(config.aichat_super_users),  # 主动聊天目标用户列表
            "proactive_groups": list(config.aichat_proactive_groups),  # 主动聊天群聊列表
            "proactive_interval_min": 30,  # 随机间隔最小值（分钟）
            "proactive_interval_max": 90,  # 随机间隔最大值（分钟）
            "proactive_cooldown": 30,      # 同一用户最短发送间隔（分钟）
            "proactive_quiet_start": 0,    # 免打扰时段开始小时（24小时制）
            "proactive_quiet_end": 8,      # 免打扰时段结束小时（24小时制）
            "memory_enabled": True,        # 全局记忆开关（默认开启，可在 AstroSwarm AI 大脑页关闭）
            # ===== 魔改新增：群聊搭话 =====
            "interject_enabled": False,    # 群聊搭话总开关
            "interject_probability": 0.3,  # 搭话概率
            "interject_interval_min": 30,  # 搭话随机间隔最小值（分钟）
            "interject_interval_max": 90,  # 搭话随机间隔最大值（分钟）
            "interject_history_count": 10, # 搭话时读取最近消息条数
            # ===== 魔改新增：群聊免@会话 =====
            "session_expire_seconds": 30,  # 免@会话有效期（秒）
            "session_unrelated_limit": 5,  # 连续无关消息条数上限
            "group_auto_participate": False,  # 旧版群聊随机参与（默认关闭）
            # "mcp_servers": {          # MCP服务器配置
            #     # "web_search": {
            #     #     "url": "https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/sse",
            #     #     "headers": {
            #     #         "Authorization": "Bearer you-key-here"
            #     #     },
            #     #     "enabled": True
            #     # }
            #     # 可以添加stdio类型的配置示例:
            #     # "local_tool": {
            #     #     "type": "stdio",
            #     #     "command": "python",
            #     #     "args": ["/path/to/mcp/server.py"],
            #     #     "env": {"KEY": "value"},
            #     #     "enabled": True
            #     # }
            # }
        }
    
    def _save_manager_config(self):
        """保存管理配置"""
        try:
            with open(MANAGER_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存聊天管理器配置失败: {e}")

    def _merge_env_config(self):
        """把 .env 中的新配置合并进管理器（.env 优先）"""
        # 超级用户并集
        su = list(self._data.get("super_users", []))
        for uid in config.aichat_super_users:
            if uid and uid not in su:
                su.append(uid)
        self._data["super_users"] = su

        # 主动聊天目标用户（.env 追加，不去重历史数据）
        targets = self._data.get("proactive_targets", [])
        for uid in config.aichat_proactive_users:
            if uid and uid not in targets:
                targets.append(uid)
        self._data["proactive_targets"] = targets

        # 主动聊天群聊（.env 追加）
        groups = self._data.get("proactive_groups", [])
        for gid in config.aichat_proactive_groups:
            if gid and gid not in groups:
                groups.append(gid)
        self._data["proactive_groups"] = groups

        # 各参数：.env 显式配置时覆盖管理器默认值
        if config.aichat_proactive_interval_min > 0:
            self._data["proactive_interval_min"] = config.aichat_proactive_interval_min
        if config.aichat_proactive_interval_max > 0:
            self._data["proactive_interval_max"] = config.aichat_proactive_interval_max
        if config.aichat_proactive_cooldown > 0:
            self._data["proactive_cooldown"] = config.aichat_proactive_cooldown
        if 0 <= config.aichat_proactive_quiet_start <= 23:
            self._data["proactive_quiet_start"] = config.aichat_proactive_quiet_start
        if 0 <= config.aichat_proactive_quiet_end <= 23:
            self._data["proactive_quiet_end"] = config.aichat_proactive_quiet_end

        self._data["interject_enabled"] = bool(config.aichat_interject_enabled)
        self._data["interject_probability"] = max(0.0, min(1.0, config.aichat_interject_probability))
        if config.aichat_interject_interval_min > 0:
            self._data["interject_interval_min"] = config.aichat_interject_interval_min
        if config.aichat_interject_interval_max > 0:
            self._data["interject_interval_max"] = config.aichat_interject_interval_max
        if config.aichat_interject_history_count > 0:
            self._data["interject_history_count"] = config.aichat_interject_history_count

        # 旧版分钟配置迁移到秒（仅当旧数据存在且新值未配置时）
        if "session_expire_minutes" in self._data and "session_expire_seconds" not in self._data:
            self._data["session_expire_seconds"] = int(self._data["session_expire_minutes"]) * 60
            self._data.pop("session_expire_minutes", None)
        if config.aichat_session_expire_seconds > 0:
            self._data["session_expire_seconds"] = config.aichat_session_expire_seconds
        if config.aichat_session_unrelated_limit > 0:
            self._data["session_unrelated_limit"] = config.aichat_session_unrelated_limit
        self._data["group_auto_participate"] = bool(config.aichat_group_auto_participate)
        self._save_manager_config()
    
    # MCP功能管理
    def is_mcp_enabled(self) -> bool:
        """检查MCP功能是否启用"""
        return self._data.get("mcp_enabled", False)
    
    def set_mcp_enabled(self, enabled: bool) -> bool:
        """设置MCP功能开关"""
        if self._data.get("mcp_enabled", False) != enabled:
            self._data["mcp_enabled"] = enabled
            self._save_manager_config()
            return True
        return False
    
    def get_mcp_servers(self) -> Dict[str, Any]:
        """获取所有MCP服务器配置"""
        return self._data.get("mcp_servers", {})
    
    def get_enabled_mcp_servers(self) -> Dict[str, Any]:
        """获取启用的MCP服务器配置"""
        all_servers = self.get_mcp_servers()
        return {name: config for name, config in all_servers.items() 
                if config.get("enabled", True)}
    
    def set_mcp_server_enabled(self, server_name: str, enabled: bool) -> bool:
        """设置单个MCP服务器的启用状态"""
        servers = self.get_mcp_servers()
        if server_name in servers:
            if servers[server_name].get("enabled", True) != enabled:
                servers[server_name]["enabled"] = enabled
                self._data["mcp_servers"] = servers
                self._save_manager_config()
                return True
        return False
    
    def add_mcp_server(self, server_name: str, server_type: str, **kwargs) -> bool:
        """添加MCP服务器配置
        
        Args:
            server_name: 服务器名称
            server_type: 服务器类型 "sse" 或 "stdio"
            **kwargs: 配置参数
                - 对于sse类型: url, headers
                - 对于stdio类型: command, args, env
        """
        servers = self.get_mcp_servers()
        if server_name in servers:
            return False
        
        base_config = {
            "type": server_type,
            "enabled": True
        }
        
        if server_type == "sse":
            base_config.update({
                "url": kwargs.get("url"),
                "headers": kwargs.get("headers", {})
            })
        elif server_type == "stdio":
            base_config.update({
                "command": kwargs.get("command"),
                "args": kwargs.get("args", []),
                "env": kwargs.get("env", {})
            })
        else:
            return False
        
        servers[server_name] = base_config
        self._data["mcp_servers"] = servers
        self._save_manager_config()
        return True
    
    def remove_mcp_server(self, server_name: str) -> bool:
        """移除MCP服务器配置"""
        servers = self.get_mcp_servers()
        if server_name in servers:
            del servers[server_name]
            self._data["mcp_servers"] = servers
            self._save_manager_config()
            return True
        return False
    
    # 群聊触发概率管理
    def get_group_chat_probability(self) -> float:
        """获取群聊触发概率"""
        return self._data.get("group_chat_probability", 0.2)
    
    def set_group_chat_probability(self, probability: float) -> bool:
        """设置群聊触发概率"""
        if not 0 <= probability <= 1:
            return False
        
        if self._data.get("group_chat_probability", 0.2) != probability:
            self._data["group_chat_probability"] = probability
            self._save_manager_config()
            return True
        return False
    
    # 管理员管理
    def is_super_user(self, user_id: str) -> bool:
        """检查用户是否为管理员"""
        return user_id in self._data.get("super_users", [])

    def get_super_users(self) -> List[str]:
        """获取所有管理员"""
        return self._data.get("super_users", [])
    
    # 群聊管理
    def is_group_enabled(self, group_id: str) -> bool:
        """检查群聊是否启用"""
        return group_id in self._data.get("enabled_groups", [])
    
    def enable_group(self, group_id: str) -> bool:
        """启用群聊"""
        if group_id not in self._data.get("enabled_groups", []):
            if "enabled_groups" not in self._data:
                self._data["enabled_groups"] = []
            self._data["enabled_groups"].append(group_id)
            self._save_manager_config()
            return True
        return False
    
    def disable_group(self, group_id: str) -> bool:
        """禁用群聊"""
        if group_id in self._data.get("enabled_groups", []):
            self._data["enabled_groups"].remove(group_id)
            self._save_manager_config()
            return True
        return False
    
    def get_enabled_groups(self) -> List[str]:
        """获取所有启用的群聊"""
        return self._data.get("enabled_groups", [])
    
    # AI配置管理
    def get_ai_configs(self) -> List[Dict[str, str]]:
        """获取所有AI配置"""
        return self._data.get("ai_configs", [])
    
    def get_current_ai_config(self) -> Dict[str, str]:
        """获取当前使用的AI配置"""
        configs = self.get_ai_configs()
        current_index = self._data.get("current_ai_config", 0)
        if configs and 0 <= current_index < len(configs):
            return configs[current_index]
        return {}
    
    def add_ai_config(self, name: str, api_key: str, api_url: str, model: str) -> bool:
        """添加新的AI配置"""
        if "ai_configs" not in self._data:
            self._data["ai_configs"] = []
        
        for config in self._data["ai_configs"]:
            if config.get("name") == name:
                return False
        
        new_config = {
            "name": name,
            "api_key": api_key,
            "api_url": api_url,
            "model": model
        }
        
        self._data["ai_configs"].append(new_config)
        self._save_manager_config()
        return True
    
    def remove_ai_config(self, name: str) -> bool:
        """移除AI配置"""
        configs = self.get_ai_configs()
        for i, config in enumerate(configs):
            if config.get("name") == name:
                is_current_chat_config = (self._data.get("current_ai_config", 0) == i)
                is_current_image_config = (self._data.get("current_image_recognition_config", 0) == i)
                
                self._data["ai_configs"].pop(i)
                
                current_chat_index = self._data.get("current_ai_config", 0)
                if current_chat_index >= i:
                    self._data["current_ai_config"] = max(0, current_chat_index - 1)
                
                current_image_index = self._data.get("current_image_recognition_config", 0)
                if current_image_index >= i:
                    self._data["current_image_recognition_config"] = max(0, current_image_index - 1)
                
                self._save_manager_config()
                return True, is_current_chat_config, is_current_image_config
        return False, False, False
    
    def switch_ai_config(self, name: str) -> bool:
        """切换到指定的AI配置"""
        configs = self.get_ai_configs()
        for i, config in enumerate(configs):
            if config.get("name") == name:
                self._data["current_ai_config"] = i
                self._save_manager_config()
                return True
        return False
    
    def get_current_config_index(self) -> int:
        """获取当前配置索引"""
        return self._data.get("current_ai_config", 0)
    
    # 全局开关管理
    def is_chat_enabled(self) -> bool:
        """检查AI聊天是否启用"""
        return self._data.get("chat_enabled", True)
    
    def set_chat_enabled(self, enabled: bool) -> bool:
        """设置AI聊天开关"""
        if self._data.get("chat_enabled", True) != enabled:
            self._data["chat_enabled"] = enabled
            self._save_manager_config()
            return True
        return False
    
    # 搜索功能开关
    def is_search_enabled(self) -> bool:
        """检查搜索功能是否启用"""
        return self._data.get("enable_search", False)
    
    def set_search_enabled(self, enabled: bool) -> bool:
        """设置搜索功能开关"""
        if self._data.get("enable_search", False) != enabled:
            self._data["enable_search"] = enabled
            self._save_manager_config()
            return True
        return False
    
    # 人设管理
    def get_personality(self) -> str:
        """获取人设配置"""
        return self._data.get("personality", "")
    
    def set_personality(self, personality: str) -> bool:
        """设置人设配置"""
        if self._data.get("personality", "") != personality:
            self._data["personality"] = personality
            self._save_manager_config()
            return True
        return False
    
    # 权限检查
    def check_permission(self, event: MessageEvent) -> bool:
        """检查用户是否有权限操作"""
        user_id = str(event.user_id)
        return self.is_super_user(user_id)

    # 图片识别相关方法
    def is_image_recognition_enabled(self) -> bool:
        """检查图片识别功能是否启用"""
        return self._data.get("image_recognition_enabled", False)

    def set_image_recognition_enabled(self, enabled: bool) -> bool:
        """设置图片识别功能开关"""
        if self._data.get("image_recognition_enabled", False) != enabled:
            self._data["image_recognition_enabled"] = enabled
            self._save_manager_config()
            return True
        return False

    def get_current_image_recognition_config(self) -> Dict[str, str]:
        """获取当前图片识别使用的AI配置"""
        configs = self.get_ai_configs()
        current_index = self._data.get("current_image_recognition_config", 0)
        if configs and 0 <= current_index < len(configs):
            return configs[current_index]
        return {}

    def switch_image_recognition_config(self, name: str) -> bool:
        """切换到指定的图片识别配置"""
        configs = self.get_ai_configs()
        for i, config in enumerate(configs):
            if config.get("name") == name:
                self._data["current_image_recognition_config"] = i
                self._save_manager_config()
                return True
        return False

    def get_current_image_config_index(self) -> int:
        """获取当前图片识别配置索引"""
        return self._data.get("current_image_recognition_config", 0)

    # ===== 魔改新增：主动聊天管理 =====
    def is_proactive_enabled(self) -> bool:
        """检查主动聊天是否开启"""
        return self._data.get("proactive_enabled", False)

    def set_proactive_enabled(self, enabled: bool) -> bool:
        """设置主动聊天总开关"""
        if self._data.get("proactive_enabled", False) != enabled:
            self._data["proactive_enabled"] = enabled
            self._save_manager_config()
            return True
        return False

    # 全局记忆管理
    def is_memory_enabled(self) -> bool:
        """全局记忆是否启用（默认开启）。"""
        return self._data.get("memory_enabled", True)

    def set_memory_enabled(self, enabled: bool) -> bool:
        if self._data.get("memory_enabled", True) != enabled:
            self._data["memory_enabled"] = enabled
            self._save_manager_config()
            return True
        return False

    def get_proactive_targets(self) -> List[str]:
        """获取主动聊天目标用户列表"""
        return self._data.get("proactive_targets", [])

    def add_proactive_target(self, user_id: str) -> bool:
        """添加主动聊天目标用户"""
        targets = self._data.setdefault("proactive_targets", [])
        if user_id not in targets:
            targets.append(user_id)
            self._save_manager_config()
            return True
        return False

    def remove_proactive_target(self, user_id: str) -> bool:
        """移除主动聊天目标用户"""
        targets = self._data.get("proactive_targets", [])
        if user_id in targets:
            targets.remove(user_id)
            self._save_manager_config()
            return True
        return False

    def get_proactive_interval(self) -> tuple:
        """获取主动聊天随机间隔范围（分钟）"""
        return (
            self._data.get("proactive_interval_min", 30),
            self._data.get("proactive_interval_max", 90),
        )

    def set_proactive_interval(self, min_minutes: int, max_minutes: int) -> bool:
        """设置主动聊天随机间隔范围（分钟）"""
        if min_minutes <= 0 or max_minutes < min_minutes:
            return False
        self._data["proactive_interval_min"] = int(min_minutes)
        self._data["proactive_interval_max"] = int(max_minutes)
        self._save_manager_config()
        return True

    def get_proactive_cooldown(self) -> int:
        """获取同一用户最短发送间隔（分钟）"""
        return self._data.get("proactive_cooldown", 30)

    def set_proactive_cooldown(self, minutes: int) -> bool:
        """设置同一用户最短发送间隔（分钟）"""
        if minutes < 0:
            return False
        self._data["proactive_cooldown"] = int(minutes)
        self._save_manager_config()
        return True

    def get_proactive_quiet_hours(self) -> tuple:
        """获取免打扰时段（开始小时, 结束小时）"""
        return (
            self._data.get("proactive_quiet_start", 0),
            self._data.get("proactive_quiet_end", 8),
        )

    def set_proactive_quiet_hours(self, start_hour: int, end_hour: int) -> bool:
        """设置免打扰时段（0-23 小时，支持跨天如 23-7）"""
        if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
            return False
        self._data["proactive_quiet_start"] = int(start_hour)
        self._data["proactive_quiet_end"] = int(end_hour)
        self._save_manager_config()
        return True

    # ===== 魔改新增：主动聊天群聊 =====
    def get_proactive_groups(self) -> List[str]:
        """获取主动聊天群聊列表"""
        return self._data.get("proactive_groups", [])

    def add_proactive_group(self, group_id: str) -> bool:
        """添加主动聊天群聊"""
        groups = self._data.setdefault("proactive_groups", [])
        if group_id not in groups:
            groups.append(group_id)
            self._save_manager_config()
            return True
        return False

    def remove_proactive_group(self, group_id: str) -> bool:
        """移除主动聊天群聊"""
        groups = self._data.get("proactive_groups", [])
        if group_id in groups:
            groups.remove(group_id)
            self._save_manager_config()
            return True
        return False

    # ===== 魔改新增：群聊搭话 =====
    def is_interject_enabled(self) -> bool:
        """检查群聊搭话是否开启"""
        return self._data.get("interject_enabled", False)

    def set_interject_enabled(self, enabled: bool) -> bool:
        """设置群聊搭话总开关"""
        if self._data.get("interject_enabled", False) != enabled:
            self._data["interject_enabled"] = enabled
            self._save_manager_config()
            return True
        return False

    def get_interject_probability(self) -> float:
        """获取搭话概率"""
        return self._data.get("interject_probability", 0.3)

    def set_interject_probability(self, probability: float) -> bool:
        """设置搭话概率（0.0-1.0）"""
        if not 0 <= probability <= 1:
            return False
        if self._data.get("interject_probability", 0.3) != probability:
            self._data["interject_probability"] = probability
            self._save_manager_config()
            return True
        return False

    def get_interject_interval(self) -> tuple:
        """获取搭话随机间隔范围（分钟）"""
        return (
            self._data.get("interject_interval_min", 30),
            self._data.get("interject_interval_max", 90),
        )

    def set_interject_interval(self, min_minutes: int, max_minutes: int) -> bool:
        """设置搭话随机间隔范围（分钟）"""
        if min_minutes <= 0 or max_minutes < min_minutes:
            return False
        self._data["interject_interval_min"] = int(min_minutes)
        self._data["interject_interval_max"] = int(max_minutes)
        self._save_manager_config()
        return True

    def get_interject_history_count(self) -> int:
        """获取搭话时读取的最近消息条数"""
        return self._data.get("interject_history_count", 10)

    def set_interject_history_count(self, count: int) -> bool:
        """设置搭话时读取的最近消息条数"""
        if count <= 0:
            return False
        self._data["interject_history_count"] = int(count)
        self._save_manager_config()
        return True

    # ===== 魔改新增：群聊免@会话 =====
    def get_session_expire_seconds(self) -> int:
        """获取免@会话有效期（秒）"""
        return self._data.get("session_expire_seconds", 30)

    def set_session_expire_seconds(self, seconds: int) -> bool:
        """设置免@会话有效期（秒）"""
        if seconds <= 0:
            return False
        self._data["session_expire_seconds"] = int(seconds)
        self._save_manager_config()
        return True

    def get_session_unrelated_limit(self) -> int:
        """获取连续无关消息条数上限"""
        return self._data.get("session_unrelated_limit", 5)

    def set_session_unrelated_limit(self, count: int) -> bool:
        """设置连续无关消息条数上限"""
        if count <= 0:
            return False
        self._data["session_unrelated_limit"] = int(count)
        self._save_manager_config()
        return True

    def is_group_auto_participate_enabled(self) -> bool:
        """检查旧版群聊随机参与是否开启"""
        return self._data.get("group_auto_participate", False)

    def set_group_auto_participate(self, enabled: bool) -> bool:
        """设置旧版群聊随机参与开关"""
        if self._data.get("group_auto_participate", False) != enabled:
            self._data["group_auto_participate"] = enabled
            self._save_manager_config()
            return True
        return False

# 全局管理器实例
chat_manager = ChatManager()
