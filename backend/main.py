"""Stage 1 HTTP boundary. Every accepted chat request runs the compiled graph."""
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agent_graph import build_graph
from config import configuration_status, cors_origins
from domain.context import ContextSnapshot
from domain.errors import AppError
from services.application import Application

VERSION = '0.3.0'
STAGE = 'stage1'
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
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])

    @app.middleware('http')
    async def boundaries(request, call_next):
        origin = request.headers.get('origin')
        if request.method == 'POST' and origin and origin.rstrip('/') not in origins:
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
        return {'status':'ok','ready':runtime.ready,'stage':STAGE,'version':VERSION,
                'services':configuration_status(),
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
        response.set_cookie(COOKIE,token,max_age=30*86400,httponly=True,samesite='lax',secure=request.url.scheme=='https')
        return {'authenticated':True,'mode':'anonymous_browser_session'}

    @app.get('/api/conversations')
    async def conversations(request:Request):
        return {'conversations':jsonable_encoder(await runtime.repo.list_threads(await owner(request)))}

    @app.post('/api/conversations')
    async def new_conversation(request:Request):
        return await runtime.repo.create(await owner(request))

    @app.get('/api/conversations/{thread_id}')
    async def conversation(thread_id:UUID,request:Request):
        return await runtime.repo.read(await owner(request),str(thread_id))

    @app.post('/api/chat')
    async def chat(body:ChatRequest,request:Request):
        return await runtime.chat(await owner(request),str(body.thread_id),str(body.request_id),body.message,body.expected_revision)

    @app.post('/api/conversations/{thread_id}/runs/{run_id}/retry')
    async def retry(thread_id:UUID,run_id:UUID,request:Request):
        return await runtime.retry(await owner(request),str(thread_id),str(run_id))

    @app.get('/api/conversations/{thread_id}/runs/{run_id}/trace')
    async def trace(thread_id:UUID,run_id:UUID,request:Request):
        return {'events':await runtime.repo.trace(await owner(request),str(thread_id),str(run_id))}

    @app.post('/api/v1/stream_chat')
    @app.post('/api/v1/threads/{thread_id}/resume')
    @app.get('/api/v2/wander-plans')
    async def future_feature(thread_id:str|None=None):
        raise AppError('FEATURE_NOT_IMPLEMENTED','此入口属于后续阶段，尚未执行地点查询或行动。')

    return app


app = create_app()
