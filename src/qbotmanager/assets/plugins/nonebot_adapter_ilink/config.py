# -*- coding: utf-8 -*-
from pydantic import BaseModel


class Config(BaseModel):
    """nonebot-adapter-ilink 配置（.env）。"""

    ilink_base_url: str = "https://ilinkai.weixin.qq.com"
    ilink_bot_type: str = "3"
    # 状态文件路径（token/baseurl/游标）；留空则用 localstore 数据目录
    ilink_state_file: str = ""
