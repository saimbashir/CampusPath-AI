"""Static/HTML serving layer of CampusPath, before vs after, for load testing under uvicorn.
FastAPI + database are unavailable offline, so API/DB endpoints are not part of this test."""
import os, sys
from pathlib import Path
from starlette.applications import Starlette
from starlette.responses import FileResponse, HTMLResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
MODE = os.environ['MODE']; ROOT = Path(os.environ['ROOT']) / 'app'
if MODE == 'after':
    sys.path.insert(0, os.environ['ROOT'])
    from app.performance import CachedStaticFiles, SelectiveGZipMiddleware, render_shell
    async def shell(r): return HTMLResponse(render_shell(ROOT / 'templates/index.html', r), headers={'Cache-Control': 'no-cache'})
    inner = Starlette(routes=[Route('/', shell), Mount('/static', CachedStaticFiles(directory=ROOT / 'static'))])
    app = SelectiveGZipMiddleware(inner, minimum_size=1024)
else:
    async def shell(r): return FileResponse(ROOT / 'templates/index.html')
    app = Starlette(routes=[Route('/', shell), Mount('/static', StaticFiles(directory=ROOT / 'static'))])
