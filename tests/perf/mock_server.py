"""Frontend profiling server: serves the real CampusPath templates/static files and a
small mock of the JSON API (the real FastAPI stack cannot be installed in this sandbox).
Usage: python3 -I mock_server.py <project_root> <port>
Sign-in state is a cookie: mock=student|teacher|admin."""
import json, sys, os, gzip, mimetypes
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit

ROOT = os.path.abspath(sys.argv[1]); PORT = int(sys.argv[2]); GZIP = len(sys.argv) > 3 and sys.argv[3] == 'gzip'
APP = os.path.join(ROOT, 'app')

USERS = {
    'student': {'id': 2, 'name': 'Saim Bashir', 'role': 'student', 'university_id': '23F-1234', 'email': 'saim@campuspath.demo', 'profile': {}},
    'teacher': {'id': 5, 'name': 'Dr Ayesha Khan', 'role': 'teacher', 'university_id': 'FAC-01', 'email': 'teacher@campuspath.demo', 'profile': {}},
    'admin': {'id': 9, 'name': 'Admin User', 'role': 'admin', 'university_id': 'ADM-01', 'email': 'admin@campuspath.demo', 'profile': {}},
}
TOPICS = [{'id': i, 'name': n, 'mastery': m, 'attempts': 6, 'confidence': .6, 'prerequisites': p, 'clo': 'CLO-1', 'description': 'Demo topic'}
          for i, (n, m, p) in enumerate([('Agents', 82, []), ('Uninformed search', 64, [1]), ('Heuristics', 41, [2]), ('A* search', 38, [2, 3]), ('CSP', 55, [1]), ('Games', 47, [2])], start=1)]
PROGRESS = {'mastery': 58, 'readiness': 51, 'quiz_average': 67, 'attempts': 48, 'revisions': [{'topic': 'Heuristics', 'due': '2026-11-27'}],
            'path': [{'id': 3, 'name': 'Heuristics', 'why': 'Prerequisite for A* search.', 'confidence': .5}, {'id': 4, 'name': 'A* search', 'why': 'Builds on heuristics.', 'confidence': .4}],
            'topics': TOPICS, 'clos': {'CLO-1': 62, 'CLO-2': 48, 'CLO-3': 71}, 'misconceptions': []}
COURSE = [{'id': 1, 'code': 'AI-301', 'name': 'Artificial Intelligence', 'section': 'A', 'semester': 'Fall 2026', 'enrollment_code': 'AI-FALL26-DEMO', 'description': ''}]
ANALYTICS = {'students': 32, 'mastery': 61, 'support_count': 4, 'topics': TOPICS, 'clos': {'CLO-1': 60}, 'distribution': {}, 'at_risk': [], 'bloom': {}}


def api(path, role):
    if path == '/api/health':
        return 200, {'status': 'ok', 'demo_mode': True, 'max_upload_mib': 25}
    if path == '/api/auth/me':
        return (200, {'user': USERS[role], 'csrf': 'mock'}) if role else (401, {'detail': 'Sign in required.'})
    if not role:
        return 401, {'detail': 'Sign in required.'}
    if path == '/api/courses':
        return 200, COURSE
    if path.endswith('/progress'):
        return 200, PROGRESS
    if path.endswith('/analytics'):
        return 200, ANALYTICS
    if path.endswith('/topics'):
        return 200, TOPICS
    return 200, []


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *a): pass
    def send(self, code, body, ctype, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
        for k, v in (extra or {}).items(): self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD': self.wfile.write(body)
    def role(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == 'mock' and v in USERS: return v
        return None
    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/api/'):
            code, data = api(path, self.role())
            return self.send(code, json.dumps(data).encode(), 'application/json', {'Cache-Control': 'no-store'})
        if path.startswith('/static/'):
            f = os.path.normpath(os.path.join(APP, path.lstrip('/')))
            if not f.startswith(os.path.join(APP, 'static')) or not os.path.isfile(f):
                return self.send(404, b'not found', 'text/plain')
            data = open(f, 'rb').read(); extra = {}
            if GZIP and 'gzip' in (self.headers.get('Accept-Encoding') or ''):
                data = gzip.compress(data, 6); extra['Content-Encoding'] = 'gzip'
            if GZIP and 'v=' in urlsplit(self.path).query: extra['Cache-Control'] = 'public, max-age=31536000, immutable'
            return self.send(200, data, mimetypes.guess_type(f)[0] or 'application/octet-stream', extra)
        if path in ('/robots.txt', '/sitemap.xml', '/site.webmanifest'):
            f = os.path.join(APP, 'static', path.lstrip('/'))
            if os.path.isfile(f): return self.send(200, open(f, 'rb').read(), mimetypes.guess_type(f)[0] or 'text/plain')
            return self.send(404, b'', 'text/plain')
        return self.send(200, open(os.path.join(APP, 'templates', 'index.html'), 'rb').read(), 'text/html; charset=utf-8')
    do_HEAD = do_GET
    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0); self.rfile.read(n)
        return self.send(200, b'{}', 'application/json')

ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
