"""SoloVibe HTTP boundary. Every accepted chat request runs the compiled graph."""
import os
from contextlib import asynccontextmanager
from typing import Any, Literal
from uuid import UUID

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_graph import build_graph
from config import configuration_status, cors_origins, cookie_secure, allowed_hosts
from domain.context import ContextSnapshot
from domain.errors import AppError
from services.application import Application

VERSION = '0.12.0'
STAGE = 'v3-6'
COOKIE = 'solovibe_session'


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    message: str = Field(min_length=1, max_length=8000)
    thread_id: UUID
    request_id: UUID
    expected_revision: int = Field(ge=0)

    @field_validator('message')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('message must not be blank')
        return value


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    plan_set_id: UUID
    plan_id: str = Field(min_length=1, max_length=180)
    kind: str = Field(pattern='^(save|navigate)$')
    expected_revision: int = Field(ge=0)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    proposal_version: int = Field(ge=1)
    proposal_digest: str = Field(pattern='^[0-9a-f]{64}$')
    approve: bool


class HandoffRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID


class BrowserOriginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_revision: int = Field(ge=0)
    longitude: float = Field(ge=73, le=135, allow_inf_nan=False)
    latitude: float = Field(ge=18, le=54, allow_inf_nan=False)
    accuracy_m: float = Field(ge=0, le=300, allow_inf_nan=False)


class AdjustmentRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_revision: int = Field(ge=0)
    field: Literal['city', 'location_text', 'return_location_text',
                   'desired_dwell_minutes', 'budget_cny', 'available_minutes',
                   'max_walk_minutes', 'departure_time_local', 'meal_requirement',
                   'interests', 'exclusions']
    value: Any


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    plan_set_id: UUID
    plan_id: str = Field(min_length=1, max_length=180)
    category: Literal['considered', 'went', 'did_not_go', 'other']
    note: str = Field(min_length=1, max_length=500)

    @field_validator('note')
    @classmethod
    def note_not_blank(cls, value):
        if not value.strip():
            raise ValueError('note must not be blank')
        return value.strip()


class RecheckRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    expected_revision: int = Field(ge=0)
    plan_set_id: UUID
    poi_id: str = Field(min_length=1, max_length=80)


def create_app():
    runtime = Application()

    @asynccontextmanager
    async def lifespan(app):
        await runtime.start()
        yield
        await runtime.close()

    app = FastAPI(title='SoloVibe API', version=VERSION, lifespan=lifespan)
    app.state.runtime = runtime
    origins = cors_origins()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts())
    if os.getenv('APP_ENV', 'development').lower() == 'production':
        cookie_secure('https')
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type'])

    @app.middleware('http')
    async def boundaries(request, call_next):
        origin = request.headers.get('origin')
        if request.method in ('POST', 'DELETE') and origin and origin.rstrip('/') not in origins:
            return JSONResponse(status_code=403, content={'error':{'code':'ORIGIN_DENIED','message':'请求来源不在允许列表中。'}})
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(AppError)
    async def app_error(request, exc):
        return JSONResponse(status_code=exc.status, content={'error':{'code':exc.code,'message':exc.message},'stage':STAGE})

    async def owner(request):
        runtime.require_ready()
        value = await runtime.repo.owner(request.cookies.get(COOKIE))
        if not value:
            raise AppError('SESSION_REQUIRED','请先建立浏览器会话。',401)
        return value

    @app.get('/')
    async def root():
        return {'service':'solovibe','version':VERSION,'stage':STAGE,'docs':'/docs'}

    @app.get('/health', include_in_schema=False)
    @app.get('/api/v1/health')
    async def health():
        services = configuration_status()
        if runtime.ready:
            services['model']['verification'] = 'generation_passed_at_startup'
            services['database']['verification'] = 'connection_passed_at_startup'
        return {'status':'ok','ready':runtime.ready,'stage':STAGE,'version':VERSION,
                'services':services,
                'blocker':None if runtime.ready else {'code':runtime.error.code,'message':runtime.error.message}}

    @app.get('/api/v1/readiness')
    async def readiness():
        runtime.require_ready()
        try:
            async with runtime.pool.connection() as conn:
                await conn.execute('SELECT 1')
        except Exception:
            raise AppError('DATABASE_UNAVAILABLE','数据库暂时不可连接。') from None
        return {'ready':True,'stage':STAGE,'model_check':'authenticated_at_startup'}

    @app.get('/api/v1/config-status')
    async def config_status():
        return {'services':configuration_status(),'stage':STAGE}

    @app.get('/api/v1/graph')
    async def graph_description():
        graph = runtime.graph or build_graph(None,None)
        return {'mermaid':graph.get_graph().draw_mermaid(),
                'context_schema':ContextSnapshot.model_json_schema(),
                'running':runtime.ready}

    @app.post('/api/session')
    async def session(request:Request,response:Response):
        runtime.require_ready()
        _,token = await runtime.repo.session(request.cookies.get(COOKIE))
        response.set_cookie(COOKIE,token,max_age=30*86400,httponly=True,samesite='lax',secure=cookie_secure(request.url.scheme))
        return {'authenticated':True,'mode':'anonymous_browser_session'}

    @app.get('/api/conversations')
    async def conversations(request:Request):
        actor = await owner(request)
        return {'conversations':jsonable_encoder(await runtime.repo.list_threads(actor))}

    @app.post('/api/conversations')
    async def new_conversation(request:Request):
        actor = await owner(request)
        return await runtime.repo.create(actor)

    @app.get('/api/conversations/{thread_id}')
    async def conversation(thread_id:UUID,request:Request):
        return await runtime.read_conversation(await owner(request),str(thread_id))

    @app.delete('/api/conversations/{thread_id}')
    async def delete_conversation(thread_id:UUID,request:Request):
        actor = await owner(request)
        return await runtime.repo.delete_owned(actor,str(thread_id))

    @app.get('/api/conversations/{thread_id}/plans')
    async def plans(thread_id:UUID,request:Request):
        current = await runtime.read_conversation(await owner(request),str(thread_id))
        return {'thread_id':str(thread_id), 'context_revision':current['snapshot']['revision'],
                'plan_set':current['plan_set']}

    @app.post('/api/conversations/{thread_id}/origin')
    async def browser_origin(thread_id:UUID, body:BrowserOriginRequest, request:Request):
        return await runtime.set_browser_origin(await owner(request), str(thread_id),
            str(body.request_id), body.expected_revision,
            body.longitude, body.latitude, body.accuracy_m)

    @app.post('/api/conversations/{thread_id}/actions')
    async def prepare_action(thread_id:UUID,body:ActionRequest,request:Request):
        return await runtime.prepare_action(await owner(request),str(thread_id),str(body.request_id),
            str(body.plan_set_id),body.plan_id,body.kind,body.expected_revision)

    @app.get('/api/actions/{action_id}')
    async def action(action_id:UUID,request:Request):
        from persistence.actions import public_action
        actor = await owner(request)
        return public_action(await runtime.repo.actions.get(actor,str(action_id)))

    @app.post('/api/actions/{action_id}/decision')
    async def decide_action(action_id:UUID,body:DecisionRequest,request:Request):
        return await runtime.decide_action(await owner(request),str(action_id),str(body.request_id),
                                           body.proposal_version,body.proposal_digest,body.approve)

    @app.post('/api/actions/{action_id}/recover')
    async def recover_action(action_id:UUID,request:Request):
        return await runtime.recover_action(await owner(request),str(action_id))

    @app.post('/api/actions/{action_id}/handoff')
    async def handoff(action_id:UUID,body:HandoffRequest,request:Request):
        from persistence.actions import public_action
        actor = await owner(request)
        return public_action(await runtime.repo.actions.record_handoff(
            actor,str(action_id),str(body.request_id)))

    @app.post('/api/chat')
    async def chat(body:ChatRequest,request:Request):
        return await runtime.chat(await owner(request),str(body.thread_id),str(body.request_id),body.message,body.expected_revision)

    @app.post('/api/conversations/{thread_id}/adjustments')
    async def adjust(thread_id:UUID, body:AdjustmentRequest, request:Request):
        return await runtime.adjust(await owner(request), str(thread_id),
                                    str(body.request_id), body.field, body.value,
                                    body.expected_revision)

    @app.post('/api/conversations/{thread_id}/recheck')
    async def recheck(thread_id:UUID, body:RecheckRequest, request:Request):
        return await runtime.recheck_place(await owner(request), str(thread_id),
            str(body.request_id), str(body.plan_set_id), body.poi_id,
            body.expected_revision)

    @app.post('/api/conversations/{thread_id}/runs/{run_id}/retry')
    async def retry(thread_id:UUID,run_id:UUID,request:Request):
        return await runtime.retry(await owner(request),str(thread_id),str(run_id))

    @app.get('/api/conversations/{thread_id}/runs/{run_id}')
    async def run_status(thread_id:UUID,run_id:UUID,request:Request):
        actor = await owner(request)
        return await runtime.repo.run_status(actor,str(thread_id),run_id=str(run_id))

    @app.get('/api/conversations/{thread_id}/requests/{request_id}')
    async def request_status(thread_id:UUID,request_id:UUID,request:Request):
        actor = await owner(request)
        return await runtime.repo.run_status(actor,str(thread_id),request_id=str(request_id))

    @app.get('/api/conversations/{thread_id}/timeline')
    async def timeline(thread_id:UUID,request:Request):
        actor = await owner(request)
        return {'events':await runtime.repo.timeline(actor,str(thread_id))}

    @app.post('/api/conversations/{thread_id}/feedback')
    async def feedback(thread_id:UUID,body:FeedbackRequest,request:Request):
        actor = await owner(request)
        row = await runtime.repo.submit_feedback(actor,str(thread_id),
            str(body.request_id),str(body.plan_set_id),body.plan_id,body.category,body.note)
        return {'feedback_id':str(row['feedback_id']), 'plan_id':row['plan_id'],
                'category':row['category'], 'note':row['note'],
                'source_kind':'user_report', 'created_at':row['created_at']}

    @app.get('/api/conversations/{thread_id}/runs/{run_id}/trace')
    async def trace(thread_id:UUID,run_id:UUID,request:Request):
        actor = await owner(request)
        return {'events':await runtime.repo.trace(actor,str(thread_id),str(run_id))}

    @app.post('/api/v1/stream_chat')
    @app.post('/api/v1/threads/{thread_id}/resume')
    @app.get('/api/v2/wander-plans')
    async def future_feature(thread_id:str|None=None):
        raise AppError('FEATURE_NOT_IMPLEMENTED','旧版入口不可用；请在已授权会话中使用 /api/conversations/{thread_id}/plans 查询真实方案。')

    return app


app = create_app()
