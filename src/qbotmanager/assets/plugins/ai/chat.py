from openai import BadRequestError, AsyncOpenAI
from nonebot import logger
from .manager import chat_manager
from .mcp_manager import mcp_client  # 导入MCP管理器
import json

def get_current_time() -> str:
    """获取当前时间"""
    import datetime
    now = datetime.datetime.now()
    return f"当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')}"

def _extract_message_text(message) -> str:
    """提取回复文本：优先 content，为空时回退 reasoning_content（兼容带推理的模型）"""
    content = getattr(message, "content", None) or ""
    if content.strip():
        return content
    reasoning = getattr(message, "reasoning_content", None) or ""
    return reasoning


def _extract_content_text(message) -> str:
    """只取正式回复 content，不回退 reasoning_content（思考过程不能直接发给用户）"""
    return (getattr(message, "content", None) or "").strip()



async def get_short_ai_text(prompt: str, max_tokens: int = 200) -> str:
    """调用当前 AI 配置生成一句短文本（经济/问候等功能的 AI 润色），失败返回空字符串"""
    ai_config = chat_manager.get_current_ai_config()
    if not ai_config:
        return ""
    try:
        client = AsyncOpenAI(
            api_key=ai_config.get("api_key", ""),
            base_url=ai_config.get("api_url", ""),
        )
        messages = [
            {"role": "system", "content": chat_manager.get_personality()},
            {"role": "user", "content": prompt},
        ]
        for attempt in range(2):
            completion_obj = await client.chat.completions.create(
                model=ai_config.get("model", ""),
                messages=messages,
                max_tokens=max_tokens,
            )
            reply = _extract_content_text(completion_obj.choices[0].message)
            if reply:
                return reply
            if attempt == 0:
                messages.append({"role": "user", "content": "请直接输出最终回复，不要输出思考过程。"})
        return ""
    except Exception as e:
        logger.warning(f"AI 短文本生成失败: {e}")
        return ""



def _extract_json_text(text: str) -> str:
    """从文本中截取第一段完整 JSON（用于从推理内容里提取回复）"""
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start:end + 1]
    return ""


# 定义本地工具列表
from qbotmanager.core.agent.runtime import get_runtime
from qbotmanager.core.agent.tool import ToolContext

_TOOL_PERMISSIONS = {
    "send_message",
    "group_admin",
    "timer",
    "memory",
    "network",
    "media",
}

async def get_chat_reply_with_tools(messages: list, is_group: bool = False) -> str:
    """
    结合function call和分段回复的聊天回复函数 - 使用消息副本处理工具调用
    """
    # 检查全局开关
    if not chat_manager.is_chat_enabled():
        raise Exception("聊天功能当前已关闭")
    
    # 检查MCP功能是否启用
    if not chat_manager.is_mcp_enabled():
        logger.info("MCP功能未启用，使用普通聊天模式")
        return await get_chat_reply(messages, is_group)
    
    # 获取当前AI配置
    ai_config = chat_manager.get_current_ai_config()
    
    if not ai_config:
        raise Exception("未配置服务，请使用 'ac ai add' 命令添加配置")
    
    try:
        # 创建消息副本用于工具调用处理
        processing_messages = messages.copy()
        
        # 获取工具列表
        runtime = get_runtime()
        all_tools = runtime.schemas().copy()  # 本地 + 已装工具包
        
        # 检查是否有启用的MCP服务器
        enabled_servers = chat_manager.get_enabled_mcp_servers()
        if enabled_servers:
            try:
                mcp_tools_list = await mcp_client.get_tools()
                mcp_tools = mcp_client.get_openai_tools_format()
                all_tools.extend(mcp_tools)
                logger.info(f"MCP功能已启用，可用工具总数: {len(all_tools)} (Agent: {len(runtime.schemas())}, MCP: {len(mcp_tools)})")
            except Exception as e:
                logger.warning(f"获取MCP工具失败，将只使用本地工具: {e}")
        else:
            logger.info("没有启用的MCP服务器，只使用本地工具")
        
        # 动态创建客户端
        client = AsyncOpenAI(
            api_key=ai_config.get("api_key", ""),
            base_url=ai_config.get("api_url", ""),
        )
        
        # 单次调用：模型需要工具就返回 tool_calls，不需要直接给出回复（省一次往返）
        logger.info("Agent 单次调用（tools 自动）")
        response = await client.chat.completions.create(
            model=ai_config.get("model", ""),
            messages=[{"role": "system", "content": get_system_prompt(is_group)}]
            + processing_messages,
            max_tokens=4096,
            tools=all_tools,
            tool_choice="auto",
        )

        message = response.choices[0].message
        tool_calls = message.tool_calls

        if not tool_calls:
            reply = _extract_content_text(message)
            if reply:
                logger.info("无工具调用，直接返回回复")
                return reply
            logger.info("无工具调用且无内容，回退普通聊天")
            return await get_chat_reply(messages, is_group)
        
        # 如果有工具调用，执行调用（在副本上进行）
        if tool_calls:
            logger.info("检测到工具调用，开始执行函数")
            
            # 将模型的回复添加到消息副本中
            processing_messages.append({
                "role": "assistant",
                "content": message.content if message.content else "",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    } for tool_call in tool_calls
                ]
            })
            
            # 处理每个工具调用
            for tool_call in tool_calls:
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)
                
                logger.info(f"调用函数: {function_name}, 参数: {function_args}")
                
                # 判断是本地工具还是MCP工具
                if runtime.registry.get(function_name):
                    # 调用 Agent 工具（内置/工具包）
                    function_result = runtime.execute(
                        function_name,
                        function_args,
                        ToolContext(permissions=_TOOL_PERMISSIONS),
                    )
                    logger.info(f"Agent 工具结果: {function_result}")
                    
                    processing_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": str(function_result)
                    })
                else:
                    # 调用MCP工具
                    try:
                        mcp_result = await mcp_client.call_tool(function_name, function_args)
                        processing_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": function_name,
                            "content": str(mcp_result)
                        })
                    except Exception as e:
                        error_msg = f"MCP工具调用失败: {str(e)}"
                        processing_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id, 
                            "name": function_name,
                            "content": error_msg
                        })
        
        # 第二阶段：使用处理后的消息副本生成最终回复
        tmp_record = "\n".join(str(msg) for msg in processing_messages[-5:])
        logger.info(f"最近5条处理消息记录（含工具调用过程）:\n{tmp_record}")
        # 使用 processing_messages（包含工具调用过程）来生成最终回复
        logger.info("调用原有逻辑生成格式化回复")
        final_reply = await get_chat_reply(processing_messages, is_group)
        
        # 但只将最终回复添加到原始消息中，不包含工具调用过程
        return final_reply
        
    except Exception as e:
        logger.error(f"get_chat_reply_with_tools 发生异常: {e}")
        # 如果工具调用失败，回退到普通聊天模式
        logger.info("工具调用失败，回退到普通聊天模式")
        return await get_chat_reply(messages, is_group)

def get_reply_format(is_group: bool = False):
    base_format = ""
    if is_group:
        base_format += """
你现在在群聊中，请注意：
    - 你的发言会出现在群聊中，所有成员都能看到
    - 保持自然，像普通群成员一样参与讨论
    - 不要表现得像机器人，要有自己的观点和性格
"""
    base_format += """
请严格按照以下JSON格式回复，不要包含任何其他内容：
{
  "reply": [
    "第一段内容",
    "第二段内容",
    "可能还有更多段..."
  ]
}

内容要求：
1. 不要使用markdown格式，只返回纯JSON
2. 回复段数随机，80%的情况下保持一段内容，保持简洁
3. 在以下情况下必须分段：
   - 内容明显切换主题（比如从问题分析转到个人建议）
   - 包含代码块、示例或需要突出显示的部分
   - 回复较长时，分段模仿自然停顿，像网友打字时的换行习惯
4. 每个段落应该是一个完整的句子或者语义单元，结尾不要出现句号
5. 如果是一段代码，保持代码完整作为一个段落
6. 整体风格贴近真实网友：多用'我'开头，带点小错误或口语化表达（如'可能吧'、'反正我觉得'），但别过度啰嗦
7. 工具返回的是结构化数据或执行结果，不要照搬工具原文，由你按当前人设用自己的话组织回复
"""    
    return base_format

def get_system_prompt(is_group: bool = False):
    personality = chat_manager.get_personality()
    return personality + get_reply_format(is_group)

async def get_chat_reply(messages: list, is_group: bool = False) -> str:
    """
    messages: [{"role": "user|assistant|system", "content": str}, ...]
    is_group: 是否为群聊环境
    """
    # 检查全局开关
    if not chat_manager.is_chat_enabled():
        raise Exception("聊天功能当前已关闭")
    
    # 获取当前AI配置
    ai_config = chat_manager.get_current_ai_config()
    
    if not ai_config:
        raise Exception("未配置服务，请使用 'ac ai add' 命令添加配置")
    
    try:
        # 动态创建客户端
        client = AsyncOpenAI(
            api_key=ai_config.get("api_key", ""),
            base_url=ai_config.get("api_url", ""),
        )
        
        # 构建请求参数
        request_params = {
            "model": ai_config.get("model", ""),
            "messages": [{"role": "system", "content": get_system_prompt(is_group)}] + messages,
            "max_tokens": 4096
        }
        
        # 只有在搜索功能启用时才添加搜索参数
        if chat_manager.is_search_enabled():
            request_params["extra_body"] = {
                "enable_search": True,
                "search_options": {"forced_search": True}
            }
        
        # 直接使用异步调用
        reply_obj = await client.chat.completions.create(**request_params)
        _msg = reply_obj.choices[0].message
        reply = (_msg.content or "").strip()
        if not reply:
            # 兼容带推理的模型：答案可能放在 reasoning_content 里
            reply = _extract_json_text(getattr(_msg, "reasoning_content", None) or "")
        
        # 获取并记录Token消耗
        if hasattr(reply_obj, 'usage') and reply_obj.usage:
            usage_info = reply_obj.usage
            prompt_tokens = getattr(usage_info, 'prompt_tokens', 0)
            completion_tokens = getattr(usage_info, 'completion_tokens', 0)
            total_tokens = getattr(usage_info, 'total_tokens', 0)
            logger.info(f"对话Token消耗 - 提示Token: {prompt_tokens}, 补全Token: {completion_tokens}, 总计: {total_tokens}")

        if not reply:
            raise Exception("AI返回了空回复")
            
        return reply
        
    except BadRequestError as e:
        # 处理请求错误
        error_msg = f"对话请求异常\n{e}"
        raise Exception(error_msg)
    except Exception as e:
        # 重新抛出其他异常
        raise e

async def should_reply_in_group(messages: list) -> bool:
    """
    判断在群聊中是否应该回复（当没有被@时）
    """
    # 获取当前AI配置
    ai_config = chat_manager.get_current_ai_config()
    
    if not ai_config:
        return False
    
    try:
        # 构建判断提示词
        judgment_prompt = """
你是一个在群聊中的参与者，需要判断是否要主动参与对话。请基于以下原则判断：

【需要回复的情况】
1. 有人直接发出提问或寻求建议（即使没at你）
2. 有人表达了困惑或需要帮助
3. 有人分享有趣内容，适合互动回应
4. 话题与你相关或你有独特见解

【不需要回复的情况】
1. 其他人正在相互对话
2. 话题与你完全无关
3. 对话已经有很多人参与，不缺互动
4. 如果出现了at的内容，注意不是at你

请分析最近的对话，判断是否需要你参与
只回复 "YES" 或 "NO"，不要其他内容。
"""
        
        client = AsyncOpenAI(
            api_key=ai_config.get("api_key", ""),
            base_url=ai_config.get("api_url", ""),
        )
        
        judge_content = []
        for msg in messages[-10:]:
            if msg["role"] == "user":
                judge_content.append(f"{msg['content']}")
            else:
                data = json.loads(msg['content'])
                judge_content.append(f"你(ac)回复说: {data.get('reply', [''])}")
        content = "\n".join(judge_content)
        
        completion_obj = await client.chat.completions.create(
            model=ai_config.get("model", ""),
            messages=[{"role": "system", "content": chat_manager.get_personality() + judgment_prompt}, {"role": "user", "content": "群聊记录\n" + content}],
            max_tokens=2048,
            temperature=0,
        )
        
        judgment = _extract_content_text(completion_obj.choices[0].message)

        # 获取并记录Token消耗
        if hasattr(completion_obj, 'usage') and completion_obj.usage:
            usage_info = completion_obj.usage
            prompt_tokens = getattr(usage_info, 'prompt_tokens', 0)
            completion_tokens = getattr(usage_info, 'completion_tokens', 0)
            total_tokens = getattr(usage_info, 'total_tokens', 0)
            logger.info(f"判断Token消耗 - 提示Token: {prompt_tokens}, 补全Token: {completion_tokens}, 总计: {total_tokens}")

        logger.info(f"群聊回复判断结果: {judgment.strip().upper()}")

        judgment = judgment.strip().upper() if judgment else "NO"
        
        # 兼容模型返回 "YES 因为..." 等带解释的情况
        return judgment.startswith("YES")
        
    except Exception as e:
        raise e


async def judge_user_continues(
    messages: list,
    user_id: str,
    nickname: str = "该用户",
    last_reply_to: str = "",
) -> bool:
    """
    判断群聊中某用户（曾与机器人聊天、这次未@）的最新消息是否是在继续和机器人对话。
    是 → 回复；不是（与别人说话/话题无关）→ 不回复。
    """
    ai_config = chat_manager.get_current_ai_config()
    if not ai_config:
        return False

    try:
        recent = messages[-8:]
        history_lines = []
        for msg in recent[:-1]:
            if msg["role"] == "user":
                history_lines.append(msg["content"])
            else:
                try:
                    data = json.loads(msg["content"])
                    history_lines.append("机器人: " + " / ".join(data.get("reply", [""])))
                except Exception:
                    history_lines.append("机器人: ...")
        history_text = "\n".join(history_lines) if history_lines else "（暂无更多历史）"

        # 最后一条消息就是目标用户刚发的消息
        target_msg = ""
        if recent:
            target_msg = recent[-1].get("content", "")
        # 去掉存储时加的 "用户xxx(昵称)说：" 前缀，避免身份信息重复
        if "说：" in target_msg:
            target_msg = target_msg.split("说：", 1)[-1]
        target_msg = target_msg.strip()

        if last_reply_to:
            if last_reply_to == user_id:
                reply_context = "机器人上一次回复的对象就是该用户（你们刚在对话）"
            else:
                reply_context = f"机器人上一次回复的是用户{last_reply_to}，不是该用户"
        else:
            reply_context = "机器人还没有回复过该用户"

        judgment_rules = f"""你是群聊中的AI机器人，负责判断某个用户是否在继续和你聊天。

判断规则：
1. 用户最新消息在回应你之前说的话（回答你的问题、接你的话茬、向你提问、提到你们刚才聊的话题）→ 回复 YES
2. 用户最新消息是在和其他人说话、话题与你们刚才聊的完全无关、或明显不是对你说 → 回复 NO
3. {reply_context}。如果机器人上一次回复的对象就是该用户，且TA的消息看起来像是对你说话，优先判定 YES
4. 拿不准时倾向 YES，因为该用户刚刚才和你聊过天

参考示例：
- 你问用户"今天过得怎么样"，用户回"还不错，就是有点累" → YES
- 你刚回复完用户A，用户A马上说"哈哈那太好了" → YES
- 你刚回复完用户A，用户A却@了用户B说"你游戏打得真好" → NO
- 你问用户A"你喜欢什么颜色"，用户A回"蓝色吧" → YES

只回复 "YES" 或 "NO"，不要输出任何其他内容。"""

        client = AsyncOpenAI(
            api_key=ai_config.get("api_key", ""),
            base_url=ai_config.get("api_url", ""),
        )
        completion_obj = await client.chat.completions.create(
            model=ai_config.get("model", ""),
            messages=[
                {"role": "system", "content": judgment_rules},
                {
                    "role": "user",
                    "content": (
                        f"群聊历史记录：\n{history_text}\n\n"
                        f"用户{user_id}（{nickname}）刚发来一条消息（没有@你）：\n{target_msg}\n\n"
                        "这条消息是否在继续和你（机器人）对话？"
                    ),
                },
            ],
            max_tokens=2048,
            temperature=0,
        )
        judgment = (_extract_content_text(completion_obj.choices[0].message) or "NO").strip().upper()

        # 记录Token消耗
        if hasattr(completion_obj, 'usage') and completion_obj.usage:
            usage_info = completion_obj.usage
            prompt_tokens = getattr(usage_info, 'prompt_tokens', 0)
            completion_tokens = getattr(usage_info, 'completion_tokens', 0)
            total_tokens = getattr(usage_info, 'total_tokens', 0)
            logger.info(
                f"免@会话判断Token消耗 - 提示Token: {prompt_tokens}, "
                f"补全Token: {completion_tokens}, 总计: {total_tokens}"
            )

        logger.info(f"免@会话消息判断（用户{user_id}）: {judgment}")
        # 兼容模型返回 "YES 因为..." / "NO，..." 等情况
        return judgment.startswith("YES")
    except Exception as e:
        logger.error(f"免@会话消息判断失败: {e}")
        return False


async def get_poke_reply(who: str = "") -> str:
    """生成戳一戳的回复（**完全由 AI 按人设生成**，纯文本单句）。

    `who` 是戳人那个人的称呼（昵称 / 群名片，取不到就留空）—— 有了它 AI 才知道是谁戳的，
    回复才不会像在对空气说话。

    ⚠ 这里以前有一份 8 句的本地随机兜底话术，一旦 AI 调用失败就挑一句发出去 ——
    用户看到的就成了固定套路。现在改成：
    拿不到 AI 配置或两次都生不出内容，就**返回空串**，由调用方直接不发
    （宁可这一下不理人，也不要发出不像人设的套话）。
    """
    ai_config = chat_manager.get_current_ai_config()
    if not ai_config:
        logger.warning("戳一戳：没有可用的 AI 配置，本次不回复（不用词库兜底）")
        return ""
    try:
        client = AsyncOpenAI(
            api_key=ai_config.get("api_key", ""),
            base_url=ai_config.get("api_url", ""),
        )
        personality = chat_manager.get_personality() or "你是一个说话自然的群友。"
        who_note = (f"戳你的人是「{who}」。" if who
                    else "（对方没留下昵称，就当是个熟人。）")
        prompt = (
            personality
            + "\n有人戳了你一下（QQ 的戳一戳，不是发消息）。" + who_note
            + "用你自己的说话习惯自然反应一句：熟人可以叫名字、可以吐槽、也可以接一句当下的话题；"
            "不要用固定套话、不要每次都同一个句式，不要解释你在做什么，也不要提「戳一戳」这个动作本身。"
            "不超过 30 个字，不要 markdown，不要输出 JSON，直接输出这句话。"
        )
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "（对方戳了你一下）"},
        ]
        # 推理模型（gpt-oss/glm 等）会先输出思考过程：预算太小会导致正式回复为空。
        # 这里给足 token，且只取 content，绝不用 reasoning_content 冒充回复。
        for attempt in range(2):
            completion_obj = await client.chat.completions.create(
                model=ai_config.get("model", ""),
                messages=messages,
                max_tokens=1024,
            )
            reply = _extract_content_text(completion_obj.choices[0].message)
            if reply:
                return reply
            if attempt == 0:
                messages.append({"role": "user", "content": "请直接输出最终回复这句话，不要输出思考过程。"})
        logger.warning("戳一戳：两次都没生成出内容，本次不回复")
        return ""
    except Exception as e:
        logger.error(f"戳一戳AI回复生成失败，本次不回复: {e}")
        return ""


async def get_interject_reply(messages: list, mode: str = "history") -> str:
    """
    生成群聊搭话内容（返回纯文本）。
    mode="history": 读取最近聊天记录，根据前面聊天搭话；
    mode="random": 不读取聊天记录，随便发点什么找话题。
    """
    ai_config = chat_manager.get_current_ai_config()
    if not ai_config:
        raise Exception("未配置AI服务")

    try:
        if mode == "history":
            history_lines = []
            for msg in messages[-10:]:
                if msg["role"] == "user":
                    history_lines.append(msg["content"])
                else:
                    try:
                        data = json.loads(msg["content"])
                        history_lines.append("机器人: " + " / ".join(data.get("reply", [""])))
                    except Exception:
                        history_lines.append("机器人: ...")
            history = "\n".join(history_lines)
            task_content = (
                "（群聊搭话任务）根据以下群聊最近记录，自然地插一句话参与聊天、接个话茬或开启相关话题，"
                "不要提这是任务，也不要@任何人：\n" + history
            )
        else:
            task_content = (
                "（群聊搭话任务）群里现在比较安静，请随便说一句有趣的开场白或话题，"
                "自然地引出聊天，不要提这是任务，也不要@任何人。"
            )

        reply = await get_chat_reply(
            [
                {"role": "user", "content": task_content},
            ],
            is_group=True,
        )
        data = json.loads(reply)
        segments = [seg for seg in data.get("reply", []) if seg and seg.strip()]
        if not segments:
            raise ValueError("AI返回的搭话内容为空")
        return segments[0]
    except Exception as e:
        logger.error(f"生成群聊搭话内容失败: {e}")
        raise
