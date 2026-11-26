"""HTTP performance helpers (v0.9.2): compression, static caching and the SEO shell.

- Static files referenced with ?v=<version> (as the HTML shell does) are cached by browsers
  and CDNs for a year; changing the version in index.html invalidates them. Unversioned
  requests revalidate cheaply with ETag/Last-Modified (304).
- Text responses (HTML, CSS, JS, JSON) are gzip-compressed. Binary downloads, audio and
  WebSockets pass through untouched so no CPU is wasted re-compressing PDFs or MP3s.
- The HTML shell is read once and given a per-route title, canonical URL and robots policy.
"""
from __future__ import annotations

import gzip
import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

STATIC_IMMUTABLE = 'public, max-age=31536000, immutable'
STATIC_REVALIDATE = 'public, no-cache'
# Binary or already-compressed API responses that must not be gzipped.
_NO_GZIP = re.compile(r'^/api/(?:courses/\d+/resources/\d+/download|submissions/\d+/attachment|courses/\d+/speech/)')


_COMPRESSIBLE = ('text/', 'application/javascript', 'application/json', 'image/svg+xml', 'application/xml')


@lru_cache(maxsize=256)
def _gzipped(file_path: str, mtime: float, size: int) -> bytes:
    """Compress a static file once per version (mtime/size are part of the cache key)."""
    return gzip.compress(Path(file_path).read_bytes(), compresslevel=9, mtime=0)


class CachedStaticFiles(StaticFiles):
    """StaticFiles with long-lived caching for versioned URLs and pre-compressed text assets.

    Each text asset is gzip-compressed once and served from memory afterwards, so compression
    costs no CPU per request (the generic middleware would recompress on every hit)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code in (200, 304):
            query = scope.get('query_string', b'')
            # Local/demo runs always revalidate (cheap 304s), so edited files can never stay stale;
            # production (DEMO_MODE=false) caches versioned files for a year.
            cache = STATIC_IMMUTABLE if b'v=' in query and os.getenv('DEMO_MODE', 'true').lower() != 'true' else STATIC_REVALIDATE
            response.headers['Cache-Control'] = cache
            response.headers['Vary'] = 'Accept-Encoding'
            file_path = getattr(response, 'path', None)
            ctype = response.headers.get('content-type', '')
            accepts = any(b'gzip' in v for k, v in scope.get('headers', []) if k == b'accept-encoding')
            if response.status_code == 200 and file_path and accepts and ctype.startswith(_COMPRESSIBLE):
                st = os.stat(file_path)
                if st.st_size >= 1024:
                    body = await run_in_threadpool(_gzipped, str(file_path), st.st_mtime, st.st_size)
                    headers = {k: v for k, v in response.headers.items() if k.lower() not in ('content-length', 'content-type')}
                    headers['Content-Encoding'] = 'gzip'
                    return Response(body, status_code=200, headers=headers, media_type=ctype)
        return response


class SelectiveGZipMiddleware:
    """gzip for text responses only (static assets, HTML shell, JSON API)."""

    def __init__(self, app, minimum_size: int = 1024, compresslevel: int = 6):
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and not scope.get('path', '').startswith('/static/') and not _NO_GZIP.match(scope.get('path', '')):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)


# ---------------------------------------------------------------- SEO shell
PUBLIC_ROUTES = {
    '/': ('CampusPath AI · Your next step, understood',
          'CampusPath AI: a course-connected adaptive learning workspace for students, teachers and administrators.'),
    '/login': ('Sign in · CampusPath AI',
               'Sign in to CampusPath AI to continue your course-connected learning path, practice and viva preparation.'),
    '/register': ('Create your account · CampusPath AI',
                  'Create a CampusPath AI student account with your course enrollment code, or register with a faculty invitation.'),
}
PRIVATE_ROBOTS = 'noindex, nofollow'


def public_base_url(request) -> str:
    """Absolute site origin for canonical links and the sitemap.

    PUBLIC_BASE_URL (e.g. https://campuspath.example.edu) is preferred. Otherwise the request
    origin is used, honouring the proxy's X-Forwarded-Proto so hosted sites report https://.
    """
    configured = os.getenv('PUBLIC_BASE_URL', '').strip().rstrip('/')
    if configured:
        return configured
    proto = request.headers.get('x-forwarded-proto', request.url.scheme).split(',')[0].strip() or 'https'
    host = request.headers.get('host', request.url.netloc)
    return f'{proto}://{host}'


@lru_cache(maxsize=4)
def _template(path: str, mtime: float) -> str:
    return Path(path).read_text(encoding='utf-8')


@lru_cache(maxsize=64)
def _asset_hash(path: str, mtime_ns: int, size: int) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


_STATIC_ASSET = re.compile(r'(/static/([A-Za-z0-9_.-]+\.(?:css|js)))\?v=[^"\'<>\s]+')


def _version_assets(html: str, static_root: Path) -> str:
    """Use a content version rather than reusing a release number across changed files."""
    def replace(match):
        asset = static_root / match.group(2)
        try:
            info = asset.stat()
            version = _asset_hash(str(asset), info.st_mtime_ns, info.st_size)
        except OSError:
            return match.group(0)
        return f'{match.group(1)}?v={version}'
    return _STATIC_ASSET.sub(replace, html)


def render_shell(template: Path, request, private: bool = False) -> str:
    html = _template(str(template), template.stat().st_mtime)
    html = _version_assets(html, template.parent.parent / 'static')
    path = request.url.path.rstrip('/') or '/'
    title, description = PUBLIC_ROUTES.get(path, PUBLIC_ROUTES['/'])
    base = public_base_url(request)
    if private:
        meta = f'<meta name="robots" content="{PRIVATE_ROBOTS}">'
    else:
        url = base + ('' if path == '/' else path)
        meta = (f'<link rel="canonical" href="{url}">\n<meta property="og:url" content="{url}">\n'
                f'<meta property="og:title" content="{title}">\n<meta property="og:description" content="{description}">')
    html = re.sub(r'<title>.*?</title>', f'<title>{title}</title>', html, count=1)
    html = re.sub(r'(<meta name="description" content=")[^"]*(">)', lambda m: m.group(1) + description + m.group(2), html, count=1)
    return html.replace('<!--seo-->', meta, 1)


def robots_txt(request) -> str:
    base = public_base_url(request)
    return ('User-agent: *\n'
            'Allow: /$\nAllow: /login$\nAllow: /register$\nAllow: /static/\n'
            'Disallow: /api/\nDisallow: /app\nDisallow: /teacher/\nDisallow: /student/\n'
            f'\nSitemap: {base}/sitemap.xml\n')


def sitemap_xml(request) -> str:
    base = public_base_url(request)
    urls = ''.join(f'<url><loc>{base}{"" if p == "/" else p}</loc><changefreq>monthly</changefreq><priority>{"1.0" if p == "/" else "0.5"}</priority></url>'
                   for p in PUBLIC_ROUTES)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'
