import asyncio
import json
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

# 🔌 Load .env 环境变量
from dotenv import load_dotenv
import os

# 尝试从当前目录和backend目录加载.env文件
backend_env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(backend_env_path):
    dotenv_loaded = load_dotenv(backend_env_path)
    print(f"从 {backend_env_path} 加载环境变量")
else:
    dotenv_loaded = load_dotenv()
    print("从默认位置加载环境变量")

# 检查是否读到了 KEY
deepseek_key = os.getenv('DEEPSEEK_API_KEY')
if not deepseek_key:
  logger.warning("DeepSeek API key未配置，将使用模拟模式")
tavily_key = os.getenv('TAVILY_API_KEY')
if not tavily_key:
  logger.warning("Tavily API key未配置")
amap_key = os.getenv('AMAP_API_KEY')
if not amap_key:
  logger.warning("AMAP_API_KEY未配置，将使用模拟数据")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
from datetime import datetime
from typing import AsyncGenerator, Dict, Any
from fastapi.responses import StreamingResponse
import uuid
import uvicorn

from data_types import (
    StreamChatRequest, StreamChatResponse, ThreadStatus,
    SSEEventType, StreamResponseType, ThreadState
)
from db.supabase_client import SupabaseClient
from services.agent.langgraph_agent import LangGraphAgent
from services.conversation.manager import ConversationManager
from middleware.risk_control import verify_action_risk

# DeepSeek LLM 集成
import openai


# SoloVibe AI 伴侣系统设定
SYSTEM_INSTRUCTION = """
你是用户的 Solo 独处伴侣，一个温柔体贴的城市漫游向导。你的核心使命是帮助用户在城市中找到属于自己的安静时光和治愈体验。

🌿 语气风格：
- 温柔治愈：像好朋友一样轻声细语，给人安心感
- 真诚体贴：站在用户的角度思考，从不敷衍
- 简洁明了：每次只说重点，绝不啰嗦
- 情绪稳定：无论用户什么状态，都保持温和的语调

🎯 核心规则：
1. 字数绝对限制：每次回复严格控制在150字以内
2. 一人友好专注：所有建议都必须考虑"独自一人"的场景需求
3. 零社交压力：推荐的任何活动都不能有社交压力或尴尬感
4. 自适应感知：具备敏锐的同理心。请自行从用户的字里行间、标点符号中，推理出用户当下的心理状态与精力值。如果用户极度疲惫，请自动放缓语气、精简字数；如果用户表达出好奇，请适当提升轻快感，给予探索的勇气。
5. 智能行动触达：在回复结尾，请基于你对用户当前精力和时间的零散推断，自然、无痕地提出一个1-2小时内的短期慢节奏独处行为建议，让回复具备落地感，但严禁出现说教或强迫感。

✨ Few-Shot Examples (对话模仿范本)

示例 1：用户处于【极低能量 / 焦虑疲惫】状态
User: "今天赶论文到深夜，好累，感觉快崩溃了。"
Solo: "（轻轻推过去一杯温水）辛苦啦，我知道你今天已经拼尽全力了。听话，现在立刻把文档保存，合上电脑。天大的事都有明天顶着，今晚你唯一的任务就是属于你自己。闭上眼睛，放空大脑睡一觉。明天醒来如果想吹吹风，我带你去后面那条安静的河边散散步，走 20 分钟就足够让你缓过神来，好吗？"

示例 2：用户处于【中等能量 / 放松放空】状态
User: "周末下午不知道干嘛，一个人在街上瞎晃悠。"
Solo: "一个人没有目的地晃悠，其实是最高级的自由。（笑）既然都在街上了，不如顺着风吹过来的方向随便走走。我猜你附近应该有一家看起来不起眼的老书店，或者开在拐角的水果摊。过去消磨 1 个小时吧，挑一本封面顺眼的杂志，或者买一小袋橘子。不需要和任何人说话，就享受这种和城市擦肩而过的感觉。"

示例 3：用户处于【高能量 / 期待探索】状态
User: "今天天气超级好！突然很想去探索一些没去过的地方！"
Solo: "（眼睛亮了一下）那太棒了！今天这样的阳光，不分给街头巷尾一点简直是浪费。出发吧！今天我们不做任何死板的攻略。你可以试着坐上一辆从没坐过的公交车，随意坐 5 站就下车；或者在一个十字路口，完全凭直觉选一条没走过的林荫路。花 1-2 小时去盲盒一样地探索，去偶遇一家藏在深处的黑胶唱片店，回来记得跟我分享你的新发现！"

🛡️ 安全边界：
- 绝不推荐需要社交互动或团队参与的活动
- 避免任何可能让用户感到尴尬或不适的建议
- 时刻考虑成本控制和时间合理性
- 如果不能确定，宁愿建议"再想想"也不要冒险推荐
"""

class DeepSeekLLMManager:
    """DeepSeek LLM 管理器 - 实现流式聊天和150字限制"""

    def __init__(self):
        # 初始化 DeepSeek
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            logger.warning("DeepSeek API key 未配置，将使用模拟模式")
            self.client = None
        else:
            self.client = openai.OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com"
            )

        # 生成配置 - 严格执行150字限制 (DeepSeek Chat优化配置)
        self.generation_config = {
            "max_tokens": 150,
            "temperature": 0.6,  # 略微降低温度，提高稳定性
            "top_p": 0.9,         # 增加top_p，让创意发挥更好
        }

        logger.info("DeepSeek LLM 管理器初始化完成")

    async def generate_stream_response(self, user_message: str, emotion_context: Dict[str, Any] = None) -> AsyncGenerator[str, None]:
        """生成流式回复"""
        try:
            # 构建完整的提示词
            full_prompt = self._build_enhanced_prompt(user_message, emotion_context)

            if not self.client:
                # 模拟模式 - 用于开发和测试
                async for chunk in self._mock_stream_response(user_message):
                    yield chunk
                return

            # 构建 messages 格式
            messages = []

            # 系统指令作为 system message
            messages.append({"role": "system", "content": SYSTEM_INSTRUCTION})

            # 注入情绪上下文
            if emotion_context:
                pressure_level = emotion_context.get('pressure_level', 5)
                energy_level = emotion_context.get('energy_level', 5)

                if pressure_level >= 7 or energy_level <= 3:
                    # 低能量/高压力场景
                    messages.append({
                        "role": "system",
                        "content": "当前用户状态：疲惫、压力大，需要温柔治愈的建议。请用更温柔的语气，提供简单、零压力的选择。"
                    })
                elif energy_level >= 7:
                    # 高能量场景
                    messages.append({
                        "role": "system",
                        "content": "当前用户状态：充满活力，想要深度探索。请提供更具有挑战性和创造性的建议。"
                    })
                else:
                    messages.append({
                        "role": "system",
                        "content": "当前用户状态：正常平静，请给出平衡的建议。"
                    })

            # 添加用户消息
            messages.append({"role": "user", "content": user_message})

            # 调用 DeepSeek 流式生成（移除了 await ！）
            response_stream = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                **self.generation_config,
                stream=True
            )

            # 流式返回生成的内容
            async for chunk in self._process_deepseek_stream(response_stream):
                yield chunk

        except Exception as e:
            logger.error(f"DeepSeek 生成失败: {e}")
            # 降级到模拟响应
            async for chunk in self._fallback_stream_response(user_message):
                yield chunk

    def _build_enhanced_prompt(self, user_message: str, emotion_context: Dict[str, Any] = None) -> str:
        """构建增强提示词，注入情绪和精力维度"""

        # 基础系统指令
        prompt = f"{SYSTEM_INSTRUCTION}\n\n"

        # 注入情绪上下文
        if emotion_context:
            pressure_level = emotion_context.get('pressure_level', 5)
            energy_level = emotion_context.get('energy_level', 5)

            if pressure_level >= 7 or energy_level <= 3:
                # 低能量/高压力场景
                prompt += "当前用户状态：疲惫、压力大，需要温柔治愈的建议。\n"
                prompt += "请用更温柔的语气，提供简单、零压力的选择。\n\n"
            elif energy_level >= 7:
                # 高能量场景
                prompt += "当前用户状态：充满活力，想要深度探索。\n"
                prompt += "请提供更具有挑战性和创造性的建议。\n\n"
            else:
                # 中等能量场景
                prompt += "当前用户状态：想要轻松放空，平衡的独处时光。\n"
                prompt += "请提供轻松有趣的探索建议。\n\n"

        # 用户消息
        prompt += f"用户说：{user_message}\n\n请根据以上要求回复："

        return prompt

    async def _process_deepseek_stream(self, response_stream) -> AsyncGenerator[str, None]:
        """处理 DeepSeek 流式响应 - 实时转发chunk"""
        try:
            # DeepSeek使用同步迭代器（注意！），但我们在内部用await asyncio.sleep保证非阻塞
            for chunk in response_stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    # SSE 格式包装
                    yield f"data: {content}\n\n"

                # 🚨⚠️关键！确保流过程非阻塞，让上层能实时收到每个字符
                await asyncio.sleep(0.001)

        except Exception as e:
            logger.error(f"处理流式响应时出错: {e}")

    async def _mock_stream_response(self, user_message: str) -> AsyncGenerator[str, None]:
        """模拟流式响应（用于开发测试）"""
        mock_responses = [
            "我理解你现在的心情🌿，",
            "一个人在城市里漫步其实是很治愈的事情，",
            "要不要试试找个安静的咖啡店坐一坐？",
            "或者去公园的长椅上看看风景也很不错~ ✨"
        ]

        for chunk in mock_responses:
            yield f"data: {chunk}\n\n"
            await asyncio.sleep(0.3)

    async def _fallback_stream_response(self, user_message: str) -> AsyncGenerator[str, None]:
        """降级流式响应"""
        fallback_message = "抱歉，我这边有点小状况🧠💦，不过别担心，"
        fallback_message += "推荐去附近的河边散散步、喝一杯手冲咖啡吧！"

        # 分段发送模拟流式效果
        words = fallback_message.split()
        for i, word in enumerate(words):
            yield f"data: {word}{' ' if i < len(words)-1 else ''}\n\n"
            await asyncio.sleep(0.1)

# 全局 LLM 管理器实例
deepseek_manager = DeepSeekLLMManager()

# 配置验证函数
def validate_environment_config() -> Dict[str, Any]:
    """验证环境配置是否正确"""
    import os

    config_status = {
        "status": "ok",
        "missing_vars": [],
        "warnings": [],
        "supabase": False,
        "web_search": False,
        "booking": False
    }

    # 检查基础配置
    supabase_vars = ["SUPABASE_URL", "SUPABASE_KEY"]
    for var in supabase_vars:
        if not os.getenv(var) or os.getenv(var).startswith("your-"):
            config_status["missing_vars"].append(var)

    if not config_status["missing_vars"]:
        config_status["supabase"] = True

    # 检查Web搜索配置
    tavily_key = os.getenv("TAVILY_API_KEY")
    serper_key = os.getenv("SERPER_API_KEY")

    if tavily_key and not tavily_key.startswith("your-"):
        config_status["web_search"] = True
    elif serper_key and not serper_key.startswith("your-"):
        config_status["web_search"] = True
    else:
        config_status["missing_vars"].append("WEB_SEARCH_API")

    # 检查高德地图配置（现在是核心必要服务）
    amap_key = os.getenv("AMAP_API_KEY")
    amap_url = os.getenv("AMAP_BASE_URL")

    if amap_key and not amap_key.startswith("your-") and amap_url:
        config_status["amap"] = True  # 重命名为amap以反映新架构
        config_status["booking"] = True  # 保持旧引用以保持兼容性
    else:
        config_status["missing_vars"].append("AMAP_API")  # 改为必填项

        # 检查DeepSeek API配置
        deepseek_key = os.getenv("DEEPSEEK_API_KEY")
        if deepseek_key and not deepseek_key.startswith("sk-你的"):
            config_status["deepseek"] = True
        else:
            config_status["warnings"].append("DEEPSEEK_API_KEY未配置，将使用模拟模式")
            config_status["missing_vars"].append("DEEPSEEK_API_KEY")

    # 设置整体状态
    if config_status["missing_vars"]:
        # 区分严重程度：AMAP_API是P0，其他是P1
        critical_missing = [var for var in config_status["missing_vars"] if var in ["AMAP_API"]]
        if critical_missing:
            config_status["status"] = "error"
        else:
            config_status["status"] = "warning"
    elif config_status["warnings"]:
        config_status["status"] = "warning"

    return config_status

app = FastAPI(
    title="SoloVibe Backend API",
    description="AI-powered solo experience planning with LangGraph and Supabase",
    version="0.1.0",
    # 重要：允许来自前端的所有跨域访问
    # 不指定host，host由uvicorn控制
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize clients
supabase_client = SupabaseClient()
langgraph_agent = LangGraphAgent()

@app.middleware("http")
async def log_requests(request: Request, call_next):
    print(f"DEBUG: 收到来自 {request.client.host} 的请求，路径: {request.url.path}")
    response = await call_next(request)
    return response

# API端点定义
@app.get("/")
async def root():
    """主页面"""
    config_status = validate_environment_config()
    return {
        "message": "SoloVibe 后端服务运行中 🚀",
        "docs": "/docs",
        "redoc": "/redoc",
        "version": "0.1.0",
        "config_status": "ok" if config_status["status"] == "ok" else "needs_setup"
    }

@app.get("/api/v1/health")
async def health_check():
    """健康检查端点"""
    config_status = validate_environment_config()

    health_info = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0",
        "environment": os.getenv("DEBUG", "production") and "development" or "production"
    }

    # 添加配置状态
    health_info["configuration"] = config_status

    # 根据配置状态设置HTTP状态
    if config_status["status"] == "error":
        health_info["status"] = "unhealthy"
    elif config_status["status"] == "warning":
        health_info["status"] = "degraded"

    return health_info

@app.get("/api/v1/config-status")
async def config_status_endpoint():
    """配置状态详细信息"""
    config_status = validate_environment_config()

    # 在开发环境返回详细信息
    if os.getenv("DEBUG", "").lower() == "true":
        return {
            "status": config_status,
            "documentation": "ENVIRONMENT_SETUP.md",
            "setup_helper": "python setup_env.py"
        }
    else:
        # 生产环境仅返回基础状态
        return {
            "status": config_status["status"],
            "needs_setup": bool(config_status["missing_vars"])
        }

# 导入os模块用于环境变量访问
import os

def generate_booking_confirmation_message(booking_info: Dict) -> str:
    """生成预订确认消息"""
    booking_request = booking_info.get("booking_request", {})
    risk_assessment = booking_info.get("risk_assessment", {})

    merchant_name = booking_request.get("merchant", "")
    estimated_cost = booking_request.get("estimated_cost", 0)
    risk_level = booking_info.get("risk_level", "medium")

    risk_indicators = {
        "low": "预订风险较低",
        "medium": "中等风险，建议确认",
        "high": "高风险预订，请仔细确认",
        "critical": "极高风险，强烈建议确认"
    }

    base_message = f"即将为您预订 {merchant_name}，预估费用 ¥{estimated_cost:.2f}"

    if risk_level in ["high", "critical"]:
        return f"{base_message}。{risk_indicators.get(risk_level, '')}，这是最后确认机会 ⚠️"
    else:
        return f"{base_message}。{risk_indicators.get(risk_level, '')}，请确认是否继续 🤔"


async def deepseek_stream_chat_handler(message: str, thread_id: str) -> AsyncGenerator[str, None]:
    """
    Protocol v2.0 - 事件驱动SSE聊天处理器
    将AI输出转换为结构化事件流：empathy, location_request, business_recommendation等
    """
    try:
        logger.info(f"开始处理thread_id: {thread_id}, message: {message}")

        # 1. 从Supabase恢复或创建thread状态
        logger.info("步骤1: 从Supabase恢复或创建thread状态...")
        thread_state = await supabase_client.get_or_create_thread(thread_id)
        logger.info("步骤1完成: 获取到thread状态")

        # 2. 情感分析用于LLM上下文注入
        logger.info("步骤2: 开始调用LangGraph情感分析...")
        emotion_profile = await langgraph_agent._emotion_sensing(message, thread_state)
        logger.info("步骤2完成: 情感分析结果")
        emotion_context = {
            'pressure_level': emotion_profile.pressure_level,
            'energy_level': emotion_profile.energy_level,
            'detected_keywords': emotion_profile.detected_keywords
        }

        # 3. 收集回复并直接向前端 yield 纯文本字符
        complete_response = ""
        logger.info("步骤3: 开始调用LangGraph process_message执行完整流程...")

        try:
            # 🚨 核心变更：调用 LangGraph 完整流程，不是只跑情绪分析+直连 LLM
            process_result = await langgraph_agent.process_message(message, thread_state)

            # 判断返回类型
            # Phase 3: 转换为Protocol v2.0事件驱动SSE流
            if process_result.get("type") == "clarification":
                # 发送empathy事件
                empathy_text = process_result.get("empathy_response", "亲爱的，你在哪里呢？我帮你看看附近有什么好去处～")
                empathy_event = f"event: empathy\ndata: {json.dumps({'text': empathy_text}, ensure_ascii=False)}\n\n"
                yield empathy_event
                complete_response = empathy_text

                # 检查是否包含地址询问意图
                if "地址查询" in process_result.get("tags", []) or "location" in empathy_text or "地铁" in empathy_text or "区域" in empathy_text:
                    location_event = f"event: location_request\ndata: {json.dumps({'prompt': empathy_text, 'required': True}, ensure_ascii=False)}\n\n"
                    yield location_event
            else:
                # 🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕🆕
                # 走新流程：从 LangGraph 里拿到详细场景、再让 DeepSeek 润色输出
                detailed_scenario = process_result.get("detailed_scenario")
                if detailed_scenario and hasattr(detailed_scenario, "enhanced_response"):
                    # 🎯 即使有详细方案，也让 LLM 润色后再流式输出
                    enhanced_text = getattr(detailed_scenario, "enhanced_response", None)
                    # 让 LLM 再加工一下，加入情绪
                    prompt = f"以下是场景内容，请用治愈语气润色成150字以内的回应：\n{enhanced_text}\n\n用户状态：压力={emotion_context.get('pressure_level', 5)}, 能量={emotion_context.get('energy_level', 5)}"
                    # 事件驱动输出商业推荐
                    final_text = ""  # 用于收集最终文本
                    async for chunk in deepseek_manager.generate_stream_response(prompt, emotion_context):
                        if chunk.startswith('data: '):
                            text_content = chunk[6:].strip().rstrip('\n')
                            if text_content:
                                complete_response += text_content
                                final_text += text_content
                                # 发送文本chunk
                                chunk_event = f"event: text_chunk\ndata: {json.dumps({'content': text_content}, ensure_ascii=False)}\n\n"
                                yield chunk_event

                    # 发送完整的empathy事件
                    if final_text:
                        empathy_event = f"event: empathy\ndata: {json.dumps({'text': final_text}, ensure_ascii=False)}\n\n"
                        yield empathy_event
                elif isinstance(detailed_scenario, dict) and detailed_scenario.get('error_info', {}).get('enhanced_response'):
                    # 🎯 处理字典格式的NoRealTimeDataScenario
                    enhanced_text = detailed_scenario['error_info']['enhanced_response']
                    # 直接使用enhanced_response而不是empathy_response
                    prompt = f"以下是场景内容，请用治愈语气润色成150字以内的回应：\n{enhanced_text}\n\n用户状态：压力={emotion_context.get('pressure_level', 5)}, 能量={emotion_context.get('energy_level', 5)}"
                    # 事件驱动输出商业推荐
                    final_text = ""  # 用于收集最终文本
                    async for chunk in deepseek_manager.generate_stream_response(prompt, emotion_context):
                        if chunk.startswith('data: '):
                            text_content = chunk[6:].strip().rstrip('\n')
                            if text_content:
                                complete_response += text_content
                                final_text += text_content
                                # 发送文本chunk
                                chunk_event = f"event: text_chunk\ndata: {json.dumps({'content': text_content}, ensure_ascii=False)}\n\n"
                                yield chunk_event

                    # 发送完整的empathy事件
                    if final_text:
                        empathy_event = f"event: empathy\ndata: {json.dumps({'text': final_text}, ensure_ascii=False)}\n\n"
                        yield empathy_event
                else:
                    # 没有详细方案，回退到发送empathy_response
                    if "empathy_response" in process_result:
                        empathy_text = process_result["empathy_response"]
                        empathy_event = f"event: empathy\ndata: {json.dumps({'text': empathy_text}, ensure_ascii=False)}\n\n"
                        yield empathy_event
                        complete_response = empathy_text

                # 检查是否有店家信息需要推荐
                if detailed_scenario and hasattr(detailed_scenario, "merchant"):
                    merchant = getattr(detailed_scenario, "merchant", None)
                    if merchant:
                        recommendation_event = f"event: business_recommendation\ndata: {json.dumps({
                            'name': merchant.name if hasattr(merchant, 'name') else str(merchant),
                            'address': merchant.location.address if hasattr(merchant, 'location') else '',
                            'description': final_text[:100] if 'final_text' in locals() else empathy_text[:100] if 'empathy_text' in locals() else ''
                        }, ensure_ascii=False)}\n\n"
                        yield recommendation_event
        except Exception as e:
            import traceback
            logger.error(f"LangGraph流程执行失败: {str(e)}")
            logger.error(f"详细 Traceback:\n{traceback.format_exc()}")
        # 降级到纯LLM
        async for chunk in deepseek_manager.generate_stream_response(message, emotion_context):
            if chunk.startswith('data: '):
                text_content = chunk[6:].strip().rstrip('\n')
                if text_content:
                    complete_response += text_content
                    # 异常时也使用事件
                    chunk_event = f"event: error_fallback\ndata: {json.dumps({'content': text_content}, ensure_ascii=False)}\n\n"
                    yield chunk_event

        # 4. 默默在后台将对话安全地保存到 Supabase 数据库中
        try:
            await supabase_client.add_message(
                thread_id=thread_id,
                role="user",
                content=message
            )
            if complete_response:
                await supabase_client.add_message(
                    thread_id=thread_id,
                    role="assistant",
                    content=complete_response
                )
            logger.info("对话已成功同步保存至 Supabase 数据库")
        except Exception as db_error:
            logger.warning(f"数据库保存失败: {db_error}，已自动激活降级方案")

    except Exception as e:
        logger.error(f"流式数据管道异常: {str(e)}")
        error_message = "抱歉，我的大脑稍微有点断网了 🧠💦。不过别担心，给你推荐去附近的河边散散步、喝一杯手冲咖啡吧！"
        yield error_message  # 发生错误时，也直接返回纯文本兜底



@app.post("/api/v1/stream_chat", response_model=StreamChatResponse)
async def stream_chat_endpoint(request: StreamChatRequest):
    """
    处理流式聊天请求的主入口点
    """
    try:
        # 验证thread_id
        if not request.thread_id:
            raise HTTPException(status_code=400, detail="thread_id是必需的")

        return StreamingResponse(
            deepseek_stream_chat_handler(request.message, request.thread_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # 禁用Nginx缓冲
            }
        )

    except Exception as e:
        logger.error(f"Endpoint错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/threads/{thread_id}/resume")
async def resume_thread(thread_id: str):
    """
    Resume执行中断的线程（用户确认后调用）
    """
    try:
        # 检查当前状态
        thread_state = await supabase_client.get_thread(thread_id)
        if not thread_state:
            raise HTTPException(status_code=404, detail="Thread未找到")

        if thread_state.status != ThreadStatus.WAITING_CONFIRMATION:
            raise HTTPException(status_code=400, detail="Thread不在等待确认状态")

        # 更新状态为活跃，继续执行
        await supabase_client.update_thread_status(thread_id, ThreadStatus.ACTIVE)

        logger.info(f"Thread {thread_id} 已被用户恢复")

        return {"message": "Thread已恢复", "thread_id": thread_id}

    except Exception as e:
        logger.error(f"恢复thread时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/threads/{thread_id}")
async def get_thread_status(thread_id: str):
    """
    获取thread的当前状态
    """
    try:
        thread_state = await supabase_client.get_thread(thread_id)
        if not thread_state:
            raise HTTPException(status_code=404, detail="Thread未找到")

        return thread_state

    except Exception as e:
        logger.error(f"获取thread状态时出错: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """
    健康检查端点
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "supabase_connected": await supabase_client.check_connection()
    }


@app.post("/api/chat")
###
async def chat_endpoint(request: dict):
    """
    处理多轮聊天请求
    """
    try:
        logger.info(f"收到聊天请求: {request}")

        # Protocol v2.0兼容性处理 + thread_id获取
        user_message = ""

        # 先获取thread_id，确保在所有情况下都能正确获取
        thread_id = request.get("thread_id")  # body中的thread_id (新协议)
        if not thread_id and hasattr(request, 'query_params'):
            thread_id = request.query_params.get("thread_id")  # URL参数
        if not thread_id and request.get("messages") and isinstance(request["messages"], list) and request["messages"]:
            thread_id = request["messages"][-1].get("id")  # 消息中的id
        logger.info(f"[Protocol-v2] 原始thread_id: {thread_id}")

        # 情况1: 新协议 (单个message字段)
        if "message" in request:
            user_message = request["message"]
            logger.info("[Protocol-v2] 使用新格式: message字段")

        # 情况2: 旧协议 (messages数组)
        elif "messages" in request:
            messages = request["messages"]
            if not messages or not isinstance(messages, list) or len(messages) == 0:
                logger.warning("消息数组为空或格式错误")
                raise HTTPException(status_code=400, detail="messages 是必需的且必须是数组")

            # 提取最新的用户消息
            latest_message = messages[-1]
            if latest_message.get("role") != "user":
                # 找最后一个用户消息
                latest_user_msg = None
                for msg in reversed(messages):
                    if msg.get("role") == "user":
                        latest_user_msg = msg
                        break
                if not latest_user_msg:
                    latest_user_msg = latest_message  # fallback
            else:
                latest_user_msg = latest_message

            user_message = latest_user_msg.get("content", "")
            logger.info("[Backward Compatibility] 使用旧格式: messages字段")

        else:
            raise HTTPException(status_code=400, detail="请求必须包含message或messages字段")

        if not user_message:
            raise HTTPException(status_code=400, detail="用户消息内容不能为空")

        # 使用ConversationManager管理对话
        client_ip = None
        if hasattr(request, 'client') and request.client:
            client_ip = request.client.host

        # Protocol v2.0: thread_id优先级
        # 1. body中的thread_id (新协议)
        # 2. query_params中的thread_id (兼容性)
        # 3. messages中消息的id (最旧版本)
        thread_id = request.get("thread_id")  # 新协议body中

        if not thread_id and hasattr(request, 'query_params'):
            thread_id = request.query_params.get("thread_id")  # URL参数

        if not thread_id and "messages" in request and request["messages"]:
            thread_id = request["messages"][-1].get("id")  # 旧版本

        logger.info(f"[Protocol-v2] thread_id来源: {thread_id or 'None'}")

        logger.info(f"处理用户消息: {user_message}, thread_id: {thread_id}, client_ip: {client_ip}")

        try:
            # 使用ConversationManager处理完整流程
            conversation_manager = ConversationManager(supabase_client=supabase_client)

            # Phase 1: Thread重用基础逻辑 (API_PROTOCOL v2.0)
            # 规则1: 优先重用现有的thread_id
            # 规则2: 仅当绝对必要时才创建新thread
            stable_thread_id = thread_id
            if not stable_thread_id:
                stable_thread_id = str(uuid.uuid4())
                logger.info(f"[Protocol-v2] 创建新thread: {stable_thread_id}")
            else:
                logger.info(f"[Protocol-v2] 重用现有thread: {stable_thread_id}")

            # 处理消息
            process_result, final_thread_id = await conversation_manager.process_message(
                message=user_message,
                thread_id=stable_thread_id
            )
            logger.info(f"[Protocol-v2] 处理完成: 输入={stable_thread_id} → 输出={final_thread_id}")

            # 生成返回响应
            if process_result.get("type") == "clarification":
                response_text = process_result["empathy_response"]
            else:
                # 对于complete_response，优先使用详细方案信息，而不是简单的共情回复
                detailed_scenario = process_result.get("detailed_scenario")
                if detailed_scenario and hasattr(detailed_scenario, 'merchant') and getattr(detailed_scenario, 'merchant', None):
                    # 构建详细的商业推荐回复
                    merchant_obj = getattr(detailed_scenario, 'merchant')
                    merchant_name = getattr(merchant_obj, 'name', '推荐商家')
                    response_text = f"{process_result.get('empathy_response', '')} 我为你找到了{merchant_name}，这是一个很棒的去处！"
                elif detailed_scenario and hasattr(detailed_scenario, 'enhanced_response'):
                    # 处理没有实时数据但有enhanced_response的情况
                    response_text = getattr(detailed_scenario, 'enhanced_response', process_result.get("empathy_response", "让我为你推荐一些适合的地方。"))
                elif isinstance(detailed_scenario, dict) and detailed_scenario.get('error_info', {}).get('enhanced_response'):
                    # 处理字典格式的NoRealTimeDataScenario
                    response_text = detailed_scenario['error_info']['enhanced_response']
                else:
                    # 降级到empathy response
                    response_text = process_result.get("empathy_response", "很棒的想法！让我为你推荐一些适合的地方。")

            # Protocol v2.0: 根据地址状态生成state_info (Protocol v2.0 修复)
            # 直接从agent返回结果中读取地址状态
            has_location = False
            if process_result.get("type") == "clarification" and "address_query" in process_result:
                has_location = False  # 需要询问地址
            elif process_result.get("type") in ["response", "complete_response"]:
                # 从agent返回的地址状态信息判断
                address_status = process_result.get("address_status", {})
                logger.info(f"[DEBUG-StateInfo] Agent返回的address_status: {address_status}")
                has_location = address_status.get("has_location", True)  # 能生成方案说明有地址
                has_location = bool(has_location)  # 强制转换
            needs_user_input = process_result.get("type") == "clarification" and "address_query" in process_result

        except Exception as e:
            logger.error(f"对话处理错误: {e}")
            response_text = "抱歉，处理消息时遇到问题"
            has_location = False
            needs_user_input = True
            # 协议v2: 错误时也保持thread_id一致性
            final_thread_id = stable_thread_id

        return {
            "response": response_text,
            "thread_id": final_thread_id,
            "state_info": {
                "has_location": has_location,
                "needs_user_input": needs_user_input
            }
        }

    except Exception as e:
        logger.error(f"聊天处理错误: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/wander-plans")
async def get_wander_plans():
    """
    获取三种不同方案的UnifiedWanderPlans - 用于新版方案选择页面
    """
    try:
        # 模拟三种不同方案的数据，符合新版PRD要求
        healing_solo_index = {
            "single_seat_friendly": 0.9,
            "environment_quietness": 0.8,
            "solo_package_support": 0.7,
            "no_awkwardness": 0.9,
            "safety_rating": 0.8,
            "accessibility": 0.7
        }

        explore_solo_index = {
            "single_seat_friendly": 0.7,
            "environment_quietness": 0.6,
            "solo_package_support": 0.8,
            "no_awkwardness": 0.8,
            "safety_rating": 0.9,
            "accessibility": 0.9
        }

        free_solo_index = {
            "single_seat_friendly": 0.8,
            "environment_quietness": 0.9,
            "solo_package_support": 0.9,
            "no_awkwardness": 0.8,
            "safety_rating": 0.7,
            "accessibility": 0.6
        }

        cafe_recommendation = {
            "name": "滨江治愈咖啡馆",
            "address": "滨江区滨江大道123号",
            "distance": "步行5分钟",
            "rating": 4.8,
            "solo_seats": 8,
            "quiet_score": 0.85,
            "phone": "021-12345678"
        }

        plans = [
            {
                "id": "healing-riverside",
                "title": "滨江治愈漫步",
                "emoji": "🌊",
                "subtitle": "听流水声发呆，喂鸽子，吹风15分钟",
                "vibe_tags": ["治愈", "发呆", "低能耗"],
                "estimated_time": "45-60min",
                "solo_index": healing_solo_index,
                "merchant_recommendations": [cafe_recommendation]
            },
            {
                "id": "explore-artstreet",
                "title": "艺术街区漫游",
                "emoji": "🎨",
                "subtitle": "街头涂鸦，独立咖啡，小众设计师店",
                "vibe_tags": ["探索", "创意", "拍照"],
                "estimated_time": "90-120min",
                "solo_index": explore_solo_index,
                "merchant_recommendations": [cafe_recommendation]
            },
            {
                "id": "quiet-park",
                "title": "公园长椅计划",
                "emoji": "🌳",
                "subtitle": "零开销放空，风中读诗，免费治愈",
                "vibe_tags": ["免费", "阅读", "自然"],
                "estimated_time": "30-45min",
                "solo_index": free_solo_index,
                "merchant_recommendations": []
            }
        ]

        return {
            "success": True,
            "data": plans
        }

    except Exception as e:
        logger.error(f"获取漫游方案时出错: {str(e)}")
        raise HTTPException(status_code=500, detail="获取漫游方案失败")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # 禁用reload防止multiprocessing问题
        log_level="info"
    )
