"""Servidor WSGI del prototipo. Gunicorn en producción; servidor local en manage.py."""
import hmac
import json
import logging
import os
import re
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie, CookieError
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from domain import Problem, public_user
from service import Service, SESSION_SECONDS
from storage import Database

ROOT = Path(__file__).resolve().parent

class Application:
    def __init__(self, service, origin='http://127.0.0.1:8000', secure=False):
        self.service, self.origin, self.secure = service, origin.rstrip('/'), secure

    def cookie(self, value, clear=False):
        return ('Set-Cookie', f'ust_session={value}; Path=/; HttpOnly; SameSite=Lax; Max-Age={0 if clear else SESSION_SECONDS}' + ('; Secure' if self.secure else ''))

    def __call__(self, env, start_response):
        headers = [('X-Content-Type-Options', 'nosniff'), ('X-Frame-Options', 'DENY'),
                   ('Referrer-Policy', 'same-origin'), ('Cache-Control', 'no-store'),
                   ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
                   ('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')]
        if self.secure:
            headers.append(('Strict-Transport-Security', 'max-age=31536000'))
        try:
            status, payload, extra, mime = self.dispatch(env)
            headers.extend(extra)
        except Problem as error:
            status, payload, mime = error.status, {'error': error.message}, 'application/json'
            if status == 429:
                headers.append(('Retry-After', '900'))
        except Exception:
            logging.exception('Error interno al procesar la solicitud')
            status, payload, mime = 500, {'error': 'No fue posible completar la operación. Intenta nuevamente; si continúa, avisa a biblioteca.'}, 'application/json'
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers.extend([('Content-Type', mime + '; charset=utf-8'), ('Content-Length', str(len(body)))])
        start_response(f'{status} {HTTPStatus(status).phrase}', headers)
        return [] if env.get('REQUEST_METHOD') == 'HEAD' else [body]

    def dispatch(self, env):
        path, method = env.get('PATH_INFO', '/'), env.get('REQUEST_METHOD', 'GET')
        if method == 'HEAD':
            method = 'GET'
        static = {'/': ('index.html', 'text/html'), '/static/app.js': ('static/app.js', 'text/javascript'),
                  '/static/style.css': ('static/style.css', 'text/css')}
        if path in static:
            if method != 'GET':
                raise Problem('Método no permitido.', 405)
            file, mime = static[path]
            return 200, (ROOT / file).read_bytes(), [], mime
        if path == '/health' and method == 'GET':
            with self.service.db.transaction() as q:
                q.one('SELECT 1 AS ok')
            return 200, {'status': 'ok'}, [], 'application/json'
        if path == '/reservas' or path.startswith('/reservas/'):
            raise Problem('Esta dirección pertenece a la versión anterior. Recarga la web e ingresa con tu cuenta para usar el sistema actualizado.', 410)
        if not path.startswith('/api/'):
            raise Problem('No se encontró esta dirección.', 404)
        if method not in ('GET', 'POST'):
            raise Problem('Método no permitido.', 405)
        data = {}
        if method == 'POST':
            if env.get('HTTP_ORIGIN') != self.origin:
                raise Problem('El origen de la solicitud no está permitido.', 403)
            if env.get('CONTENT_TYPE', '').split(';')[0].strip().lower() != 'application/json':
                raise Problem('Se requiere una solicitud JSON.', 415)
            try:
                length = int(env.get('CONTENT_LENGTH') or '0')
                if length < 1 or length > 16384:
                    raise Problem('La solicitud supera el tamaño permitido o está vacía.', 413)
                data = json.loads(env['wsgi.input'].read(length))
            except (ValueError, UnicodeDecodeError):
                raise Problem('La solicitud no contiene un JSON válido.')
            if not isinstance(data, dict):
                raise Problem('El formato de la solicitud no es válido.')
        service = self.service
        # REMOTE_ADDR lo proporciona el servidor; no se confía en cabeceras reenviadas del cliente.
        peer = env.get('REMOTE_ADDR', 'unknown')
        if path == '/api/register' and method == 'POST':
            service.throttle('register-ip', peer, 20)
            return 202, service.register(data), [], 'application/json'
        if path == '/api/login' and method == 'POST':
            service.throttle('login-ip', peer, 60)
            token, result = service.login(data)
            return 200, result, [self.cookie(token)], 'application/json'
        try:
            cookie = SimpleCookie(env.get('HTTP_COOKIE', ''))
            raw = cookie['ust_session'].value if 'ust_session' in cookie else ''
        except CookieError:
            raw = ''
        user = service.authenticate(raw)
        if method == 'POST' and not hmac.compare_digest(env.get('HTTP_X_CSRF_TOKEN', ''), user['csrf']):
            raise Problem('No se pudo validar la sesión. Recarga la página y vuelve a intentar.', 403)
        if user['must_change'] and path not in ('/api/session', '/api/logout', '/api/password'):
            raise Problem('Debes cambiar tu contraseña temporal antes de continuar.', 403)
        result, extra, status = None, [], 200
        if path == '/api/session' and method == 'GET':
            result = {'user': public_user(user), 'csrf': user['csrf']}
        elif path == '/api/logout' and method == 'POST':
            result, extra = service.logout(user), [self.cookie('', clear=True)]
        elif path == '/api/password' and method == 'POST':
            service.throttle('password', user['id'])
            result, extra = service.change_password(user, data), [self.cookie('', clear=True)]
        elif path == '/api/availability' and method == 'GET':
            result = service.availability(user)
        elif path == '/api/bookings' and method == 'GET':
            try:
                query = parse_qs(env.get('QUERY_STRING', ''), max_num_fields=10)
            except ValueError:
                raise Problem('Demasiados parámetros.')
            result = service.bookings(user, query.get('day', [None])[0])
        elif path == '/api/bookings' and method == 'POST':
            result, status = service.reserve(user, data), 201
        elif re.fullmatch(r'/api/bookings/[a-f0-9-]{36}/cancel', path) and method == 'POST':
            result = service.cancel(user, path.split('/')[3], data)
        elif path == '/api/members/lookup' and method == 'POST':
            service.throttle('lookup', user['id'], 60)
            result = service.find_member(user, data)
        elif path == '/api/admin/users' and method == 'GET':
            result = service.users(user)
        elif re.fullmatch(r'/api/admin/users/[a-f0-9-]{36}', path) and method == 'POST':
            result = service.update_user(user, path.split('/')[4], data)
        else:
            raise Problem('No se encontró esta operación.', 404)
        return status, result, extra, 'application/json'

_application = None
_lock = threading.Lock()

class StartupConfigurationError(RuntimeError):
    pass

def production_origin(environ):
    origin = (environ.get('APP_ORIGIN') or environ.get('RENDER_EXTERNAL_URL') or '').strip()
    missing = []
    if not origin:
        missing.append('APP_ORIGIN (o RENDER_EXTERNAL_URL en Render)')
    if not environ.get('DATABASE_URL', '').strip():
        missing.append('DATABASE_URL')
    if missing:
        raise StartupConfigurationError('Falta configurar: ' + ', '.join(missing))
    parts = urlsplit(origin)
    if (parts.scheme != 'https' or not parts.hostname or parts.username or parts.password
            or parts.path not in ('', '/') or parts.query or parts.fragment or any(c.isspace() for c in origin)):
        raise StartupConfigurationError('APP_ORIGIN debe ser un origen HTTPS válido, sin ruta ni credenciales.')
    return origin.rstrip('/')

def unavailable(env, start_response, message):
    body = json.dumps({'error': message}, ensure_ascii=False).encode('utf-8')
    start_response('503 Service Unavailable', [
        ('Content-Type', 'application/json; charset=utf-8'),
        ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'),
        ('X-Content-Type-Options', 'nosniff'), ('Retry-After', '30')])
    return [] if env.get('REQUEST_METHOD') == 'HEAD' else [body]

def app(env, start_response):
    """Inicialización única por worker; no se crea ninguna contraseña por defecto."""
    global _application
    try:
        if _application is None:
            with _lock:
                if _application is None:
                    origin = production_origin(os.environ)
                    db = Database()
                    db.initialize()
                    _application = Application(Service(db), origin=origin, secure=True)
    except StartupConfigurationError as error:
        logging.error('Configuración incompleta: %s', error)
        return unavailable(env, start_response, 'Servicio pendiente de configuración. Revisa APP_ORIGIN y DATABASE_URL en Render.')
    except RuntimeError:
        logging.error('La inicialización fue detenida. Revisa la base de datos y si contiene reservas de la versión anterior.')
        return unavailable(env, start_response, 'La base de datos requiere revisión antes de activar el sistema. Contacta al encargado.')
    except Exception as error:
        # No volcar cadenas de conexión o secretos a la respuesta ni a los logs.
        logging.error('No se pudo inicializar el servicio (%s). Revisa la conexión PostgreSQL y las dependencias.', type(error).__name__)
        return unavailable(env, start_response, 'No se pudo conectar con el servicio de reservas. Intenta nuevamente más tarde.')
    return _application(env, start_response)
