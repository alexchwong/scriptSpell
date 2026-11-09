"""Local, token-protected developer server. Browser adapter for the headless authoring session."""
import argparse
import json
import os
from pathlib import Path
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import webbrowser

import modelspell
from scriptspell import AuthoringSession
from . import service
from .presets import PRESETS


class UIServer(ThreadingHTTPServer):
    # Join handlers after cancellation so a Monty invocation retains cleanup ownership.
    daemon_threads = False

    def __init__(self, port=0, *, runs='runs'):
        super().__init__(('127.0.0.1', port), Handler)
        self.token = secrets.token_urlsafe(32)
        self.operation = threading.Lock()
        self.api_key = ''
        self.session = AuthoringSession(runs)
        self.models = {}
        self.model_cancel = modelspell.CancelHandle()
        self.run_cancel = threading.Event()
        self.closing = False
        self.index = Path(__file__).with_name('index.html').read_bytes()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_port}/?t={self.token}'

    def endpoint(self):
        return modelspell.Endpoint('openrouter', api_key=self.api_key or None)

    def close(self):
        self.closing = True
        self.model_cancel.cancel()
        self.run_cancel.set()
        self.server_close()
        self.api_key = ''


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *args):
        pass

    def send(self, status, payload, content_type='application/json; charset=utf-8'):
        data = payload if type(payload) is bytes else json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)
        except (OSError, TimeoutError):
            pass

    def authorised(self):
        address = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != address:
            return False
        origin = self.headers.get('Origin')
        if origin is not None and origin != f'http://{address}':
            return False
        token = self.headers.get('X-Session-Token', '')
        if self.command == 'GET' and urlsplit(self.path).path == '/':
            token = parse_qs(urlsplit(self.path).query).get('t', [''])[0]
        return token.isascii() and secrets.compare_digest(token, self.server.token)

    def do_GET(self):
        if not self.authorised():
            return self.send(403, {'error': 'unauthorised'})
        path = urlsplit(self.path).path
        if path == '/':
            return self.send(200, self.server.index, 'text/html; charset=utf-8')
        if path == '/api/state':
            return self.send(200, dict(service.view(self.server.session), presets=PRESETS,
                                       key_set=bool(self.server.api_key or os.getenv('OPENROUTER_API_KEY'))))
        self.send(404, {'error': 'not_found'})

    def do_POST(self):
        if not self.authorised():
            return self.send(403, {'error': 'unauthorised'})
        if not self.server.operation.acquire(blocking=False):
            return self.send(409, {'error': 'operation_in_progress'})
        try:
            if self.server.closing:
                return self.send(503, {'error': 'shutting_down'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise service.UIError('json_required')
            if self.headers.get('Transfer-Encoding'):
                raise service.UIError('invalid_request')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 524288:
                raise service.UIError('request_limit')
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise service.UIError('invalid_request')
            body = service.parse_json(raw.decode('utf-8'), max_chars=524288)
            if type(body) is not dict:
                raise service.UIError('invalid_request')
            self.route(urlsplit(self.path).path, body)
        except service.UIError as exc:
            self.send(400, {'error': exc.code})
        except modelspell.ModelSpellError as exc:
            # Class names give useful failure categories without echoing credentials or prompts.
            self.send(502, {'error': type(exc).__name__})
        except RuntimeError:
            self.send(503, {'error': 'cleanup_failed'})
        except OSError:
            self.send(500, {'error': 'local_io_failed'})
        except (ValueError, TypeError, RecursionError, KeyError, UnicodeError):
            self.send(400, {'error': 'invalid_request'})
        finally:
            self.server.operation.release()

    def route(self, path, body):
        s = self.server
        if path == '/api/key':
            key = body.get('api_key')
            if type(key) is not str or len(key) > 4096:
                raise service.UIError('invalid_key')
            s.api_key = key.strip()
            return self.send(200, {'key_set': bool(s.api_key or os.getenv('OPENROUTER_API_KEY'))})
        if path == '/api/models':
            models = modelspell.list_models(s.endpoint(), timeout=20)
            s.models = {m.id: m for m in models}
            return self.send(200, {'models': [{'id': m.id, 'name': m.name} for m in models]})

        session = s.session
        revision_id = body.get('revision_id')
        if path == '/api/revision':
            return self.send(200, service.view(session, revision_id))
        if path == '/api/attempt':
            return self.send(200, service.attempt_view(session, body.get('attempt_id')))
        if path == '/api/export':
            return self.send(200, session.export(revision_id))

        if path in ('/api/generate', '/api/correct', '/api/improve'):
            s.model_cancel = modelspell.CancelHandle()
            if s.closing:
                s.model_cancel.cancel()
            dispatch = service.dispatch(s.endpoint(), s.model_cancel, s.models)
            settings = service.settings(body)
        if path in ('/api/run', '/api/improve', '/api/decide'):
            s.run_cancel = threading.Event()
            if s.closing:
                s.run_cancel.set()
        attempt_id = None
        if path == '/api/generate':
            session.generate(revision_id, dispatch, settings, body.get('instruction'),
                             example_count=body.get('example_count', 1))
        elif path == '/api/run':
            session.run(revision_id, cancel=s.run_cancel)
        elif path == '/api/edit':
            session.edit(revision_id, body.get('example_id'),
                         service.parse_json(body.get('input_json')),
                         service.parse_json(body.get('expected_json')))
        elif path == '/api/correct':
            attempt_id = session.correct(revision_id, dispatch, settings, body.get('example_id'), body.get('guidance'))
        elif path == '/api/improve':
            attempt_id = session.improve(revision_id, dispatch, settings, body.get('example_ids'),
                                         body.get('guidance', ''), cancel=s.run_cancel)
        elif path == '/api/decide':
            session.decide(revision_id, body.get('attempt_id'), body.get('accept'), cancel=s.run_cancel)
        elif path == '/api/restore':
            session.restore(revision_id, body.get('selected_id'))
        else:
            return self.send(404, {'error': 'not_found'})
        view = service.view(session)
        if attempt_id is not None:
            view['attempt'] = service.attempt_view(session, attempt_id)
        self.send(200, view)


def main(argv=None):
    parser = argparse.ArgumentParser(description='scriptSpell developer playground (OpenRouter calls are billable).')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('port must be between 0 and 65535')
    server = UIServer(args.port)
    print(server.url, flush=True)
    if not args.no_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()


if __name__ == '__main__':
    main()
