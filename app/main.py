from pathlib import Path
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse,JSONResponse,PlainTextResponse,Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError,OperationalError
from app.api import auth,courses,learning,teaching,generation,speech,workflows,viva,attachments,admin,research,universal,formal_viva
from app.auth.security import current_user,role
from app.config import DEMO_MODE,MAX_UPLOAD
ROOT=Path(__file__).resolve().parent
from contextlib import asynccontextmanager
@asynccontextmanager
async def lifespan(_app):
    # Free hosts restart the app often; continue any book that was still being indexed.
    from app.services.indexing import resume_pending
    from app.services.bootstrap import ensure_accounts
    ensure_accounts()
    resume_pending()
    yield
app=FastAPI(title='CampusPath AI',version='0.7.0',docs_url='/api/docs' if DEMO_MODE else None,redoc_url=None,lifespan=lifespan)
from app.http_limits import BodyLimitMiddleware
app.add_middleware(BodyLimitMiddleware,limit=MAX_UPLOAD+1024*1024)
for router in (universal.router,formal_viva.router,workflows.router,viva.router,attachments.router,admin.router,research.router):app.include_router(router)
app.include_router(generation.router);app.include_router(speech.router);app.include_router(auth.router);app.include_router(courses.router);app.include_router(learning.router);app.include_router(teaching.router)
from app.voice.streaming import router as voice_router
app.include_router(voice_router)
from app.performance import CachedStaticFiles,SelectiveGZipMiddleware,render_shell,robots_txt,sitemap_xml
# Versioned assets (?v=) are cached for a year; index.html changes the version to invalidate them.
app.mount('/static',CachedStaticFiles(directory=ROOT/'static'),name='static')
def same_origin(request:Request,origin:str)->bool:
    """True when the browser Origin is this site.

    Behind a hosting proxy (Render, Railway, Koyeb) the app may see http:// while the
    browser uses https://. The host must still match exactly, so other sites stay blocked.
    """
    from urllib.parse import urlsplit
    if origin==str(request.base_url).rstrip('/'):return True
    parts=urlsplit(origin);host=request.headers.get('host','')
    return parts.scheme in ('https','http') and bool(host) and parts.netloc.lower()==host.lower() and not parts.path.strip('/')
@app.middleware('http')
async def security_headers(request:Request,call_next):
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and not same_origin(request,origin):
        return JSONResponse({'detail':'Cross-origin requests are not allowed.'},403)
    if request.method not in ('GET','HEAD','OPTIONS'):
        length=request.headers.get('content-length')
        if length and (not length.isdigit() or int(length)>MAX_UPLOAD+1024*1024):
            return JSONResponse({'detail':'Request exceeds the size limit.'},413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['Permissions-Policy']='microphone=(self), camera=()'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith('/api'):response.headers['Cache-Control']='no-store'
    return response
# Compress text responses (HTML/CSS/JS/JSON); binary downloads and audio pass through.
app.add_middleware(SelectiveGZipMiddleware,minimum_size=1024)
@app.exception_handler(IntegrityError)
async def conflict(request,exc):
    return JSONResponse({'detail':'This operation conflicts with an existing record. Refresh and retry.'},409)
@app.get('/api/health')
def health():
    import os
    return {'max_upload_mib':MAX_UPLOAD//(1024*1024),'stt_configured':bool(os.getenv('SPEECH_API_KEY') and os.getenv('STT_MODEL')),'tts_configured':bool(os.getenv('SPEECH_API_KEY') and os.getenv('TTS_MODEL')),'status':'ok','demo_mode':DEMO_MODE,'teacher_self_registration':auth.teacher_self_registration_enabled(),'version':'0.7.0','voice':'PCM WebSocket with energy VAD, per-turn STT and controlled playback'
        ,'voice_transport':'websocket-pcm-vad','retrieval':'Lexical index with optional Qdrant hybrid search'}
SHELL=ROOT/'templates'/'index.html'
def shell_response(request:Request,private:bool=False):
    # The HTML shell is small and always revalidated, so a new release is picked up at once.
    headers={'Cache-Control':'no-cache'}
    if private:headers['X-Robots-Tag']='noindex, nofollow'
    return HTMLResponse(render_shell(SHELL,request,private),headers=headers)
@app.get('/')
@app.get('/login')
@app.get('/register')
def shell(request:Request):return shell_response(request)
@app.get('/app')
def app_shell(request:Request):return shell_response(request,private=True)
@app.get('/teacher/students')
def teacher_page(request:Request,user=Depends(current_user)):
    role(user,'teacher');return shell_response(request,private=True)
@app.get('/student/{sid}')
def student_page(sid:int,request:Request,user=Depends(current_user)):
    if user.role!='student' or user.id!=sid:raise HTTPException(403,'Student records are private.')
    return shell_response(request,private=True)
@app.get('/robots.txt',include_in_schema=False)
def robots(request:Request):return PlainTextResponse(robots_txt(request),headers={'Cache-Control':'public, max-age=86400'})
@app.get('/sitemap.xml',include_in_schema=False)
def sitemap(request:Request):return Response(sitemap_xml(request),media_type='application/xml',headers={'Cache-Control':'public, max-age=86400'})

@app.exception_handler(OperationalError)
async def database_unavailable(request,exc):
    return JSONResponse({'detail':'The database is busy or needs setup. Retry shortly; if it persists, run python run.py --check.'},503)
@app.exception_handler(Exception)
async def unexpected_error(request,exc):
    import logging,secrets
    reference=secrets.token_hex(4)
    logging.getLogger('campuspath').error('Unhandled %s; reference=%s',type(exc).__name__,reference)
    return JSONResponse({'detail':'An unexpected error occurred. Your request was not confirmed. Refresh and retry. Reference: '+reference},500)
