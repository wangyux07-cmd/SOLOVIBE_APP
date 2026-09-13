from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from enum import Enum


class ThreadStatus(str, Enum):
    ACTIVE = "active"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"


class SSEEventType(str, Enum):
    MESSAGE = "message"
    INTERRUPT = "interrupt"
    ERROR = "error"


class StreamResponseType(str, Enum):
    EMPATHY = "[EMPATHY]"
    PLANS = "[PLANS]"
    REQUIRE_USER_CONFIRM = "[REQUIRE_USER_CONFIRM]"


class StreamChatRequest(BaseModel):
    message: str
    thread_id: str


class StreamChatResponse(BaseModel):
    thread_id: str
    status: ThreadStatus
    message_count: int


class ThreadState(BaseModel):
    thread_id: str
    status: ThreadStatus
    messages: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CheckpointData(BaseModel):
    thread_id: str
    checkpoint_id: str
    state: Dict[str, Any]
    timestamp: str


class SoloIndexDimensions(BaseModel):
    """Legacy card dimensions. An absent observation stays unknown."""

    single_seat_friendly: Optional[float] = Field(default=None, ge=0, le=1)
    environment_quietness: Optional[float] = Field(default=None, ge=0, le=1)
    solo_package_support: Optional[float] = Field(default=None, ge=0, le=1)
    no_awkwardness: Optional[float] = Field(default=None, ge=0, le=1)
    safety_rating: Optional[float] = Field(default=None, ge=0, le=1)
    accessibility: Optional[float] = Field(default=None, ge=0, le=1)


class WanderPlan(BaseModel):
    id: str
    title: str
    category: str
    duration: str
    cost: str
    area: str
    quote: str
    highlightTag: str
    subChips: List[str]
    description: str
    image: str
    soloIndex: Optional[SoloIndexDimensions] = None  # 单人友好指数六维度评分


class MerchantRecommendation(BaseModel):
    """商家推荐详情"""
    name: str  # 商家名称
    address: str  # 地址
    distance: str  # 距离
    rating: float  # 评分
    solo_seats: int  # 单人座位数量
    quiet_score: float  # 安静度评分
    phone: Optional[str] = None  # 联系电话


class UnifiedWanderPlan(BaseModel):
    """统一漫游计划 - 新版PRD的CityStrollPackage结构"""
    id: str
    title: str
    emoji: str
    subtitle: str
    vibe_tags: List[str]
    estimated_time: str
    solo_index: Optional[SoloIndexDimensions] = None
    merchant_recommendations: List[MerchantRecommendation] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    is_risky: bool
    risk_level: str
    message: str
    requires_confirmation: bool = False
