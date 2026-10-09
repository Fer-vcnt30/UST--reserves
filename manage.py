import argparse
import getpass
import os
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server
from app import Application
from domain import Problem
from service import Service
from storage import Database

class ThreadedServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True

def main():
    parser = argparse.ArgumentParser(description='Administración del piloto UST Reservas')
    parser.add_argument('command', choices=['init', 'create-admin', 'reset-admin', 'serve'])
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.command == 'serve' and os.environ.get('DATABASE_URL'):
        raise Problem('El servidor local no usa producción. Retira DATABASE_URL y utiliza una base SQLite local.')
    db = Database()
    db.initialize()
    if args.command == 'init':
        print('Base de datos inicializada.')
        return
    service = Service(db)
    if args.command in ('create-admin', 'reset-admin'):
        name = input('Nombre del encargado: ') if args.command == 'create-admin' else ''
        email = input('Correo del encargado: ')
        password = getpass.getpass('Contraseña (mínimo 12 caracteres): ')
        if password != getpass.getpass('Repite la contraseña: '):
            raise Problem('Las contraseñas no coinciden.')
        if args.command == 'create-admin':
            service.bootstrap_admin(name, email, password)
        else:
            service.recover_admin(email, password)
        print('Cuenta de administrador lista. La contraseña no se mostrará ni se guardará en texto plano.')
    else:
        origin = f'http://127.0.0.1:{args.port}'
        application = Application(service, origin=origin)
        print(f'Vista local: {origin}', flush=True)
        print('Servidor de desarrollo. Para publicar utiliza Gunicorn y HTTPS.', flush=True)
        with make_server('127.0.0.1', args.port, application, server_class=ThreadedServer) as server:
            server.serve_forever()

if __name__ == '__main__':
    try:
        main()
    except (Problem, RuntimeError) as error:
        raise SystemExit(str(error))
