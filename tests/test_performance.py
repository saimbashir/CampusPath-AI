"""v0.9.2 performance/SEO behaviour of the real FastAPI app: caching, compression, crawler rules."""
from fastapi.testclient import TestClient
from app.main import app
from app.performance import _NO_GZIP


def test_static_is_compressed_and_revalidated_in_demo_mode(setup):
    c = TestClient(app)
    r = c.get('/static/cp3d.js?v=0.9.2', headers={'Accept-Encoding': 'gzip'})
    assert r.status_code == 200
    assert r.headers['content-encoding'] == 'gzip'
    assert r.headers['cache-control'] == 'public, no-cache'      # tests run with DEMO_MODE=true
    assert r.headers['vary'] == 'Accept-Encoding'
    assert r.text.startswith('/* CampusPath AI')            # httpx decompresses transparently
    plain = c.get('/static/cp3d.js', headers={'Accept-Encoding': 'identity'})
    assert 'content-encoding' not in plain.headers and plain.headers['cache-control'] == 'public, no-cache'
    assert c.get('/static/cp3d.js', headers={'If-None-Match': plain.headers['etag']}).status_code == 304


def test_public_pages_have_titles_canonical_and_open_graph(setup):
    c = TestClient(app)
    home = c.get('/')
    assert home.status_code == 200 and home.headers['cache-control'] == 'no-cache'
    assert '<link rel="canonical" href="http://testserver">' in home.text and 'og:title' in home.text
    login = c.get('/login')
    assert '<title>Sign in · CampusPath AI</title>' in login.text and 'href="http://testserver/login"' in login.text
    assert '<title>Create your account · CampusPath AI</title>' in c.get('/register').text


def test_private_pages_are_not_indexed(setup, clients):
    c = TestClient(app)
    r = c.get('/app')
    assert r.headers['x-robots-tag'] == 'noindex, nofollow' and 'noindex, nofollow' in r.text and 'canonical' not in r.text
    teacher, _ = clients('teacher@campuspath.demo')
    page = teacher.get('/teacher/students')
    assert page.status_code == 200 and page.headers['x-robots-tag'] == 'noindex, nofollow'


def test_robots_and_sitemap(setup):
    c = TestClient(app)
    robots = c.get('/robots.txt').text
    assert 'Disallow: /api/' in robots and 'Disallow: /app' in robots and 'Sitemap: http://testserver/sitemap.xml' in robots
    sitemap = c.get('/sitemap.xml')
    assert sitemap.headers['content-type'].startswith('application/xml')
    assert sitemap.text.count('<loc>') == 3 and '/app' not in sitemap.text


def test_api_stays_uncached_and_binary_routes_are_never_compressed(setup, clients):
    student, _ = clients('saim@campuspath.demo')
    r = student.get('/api/courses')
    assert r.status_code == 200 and r.headers['cache-control'] == 'no-store' and isinstance(r.json(), list)
    for path in ('/api/courses/1/resources/4/download', '/api/submissions/9/attachment', '/api/courses/1/speech/synthesize'):
        assert _NO_GZIP.match(path), path
    assert not _NO_GZIP.match('/api/courses/1/analytics')


def test_production_caches_versioned_static_for_a_year(setup, monkeypatch):
    monkeypatch.setenv('DEMO_MODE', 'false')
    r = TestClient(app).get('/static/cp3d.js?v=0.9.4')
    assert r.headers['cache-control'] == 'public, max-age=31536000, immutable'
