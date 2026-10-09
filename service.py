import hashlib
import secrets
import uuid
from domain import (BLOCKS, ROOMS, MAX_DAILY, Problem, now, clean_email, clean_name,
                    clean_rut, hash_password, verify_password, public_user, parse_day)

SESSION_SECONDS = 8 * 60 * 60

class Service:
    def __init__(self, database, clock=now):
        self.db, self.clock = database, clock
        self.dummy_hash = hash_password(secrets.token_urlsafe(24))

    def audit(self, q, actor, event, target):
        q.run('INSERT INTO pilot_audit VALUES (?,?,?,?,?)',
              (str(uuid.uuid4()), actor, event, target, self.clock().isoformat()))

    def throttle(self, scope, identity, limit=10):
        key = hashlib.sha256((scope + ':' + identity).encode()).hexdigest()
        stamp = self.clock().timestamp()
        with self.db.transaction(write=True) as q:
            q.run('DELETE FROM pilot_attempts WHERE started < ?', (stamp - 900,))
            row = q.one('SELECT * FROM pilot_attempts WHERE key=?', (key,))
            if row and row['count'] >= limit:
                raise Problem('Demasiados intentos. Espera 15 minutos antes de volver a intentar.', 429)
            if row:
                q.run('UPDATE pilot_attempts SET count=count+1 WHERE key=?', (key,))
            else:
                q.run('INSERT INTO pilot_attempts VALUES (?,?,?)', (key, 1, stamp))

    def register(self, data):
        name = clean_name(data.get('name'))
        email = clean_email(data.get('email'))
        rut = clean_rut(data.get('rut'))
        password_hash = hash_password(data.get('password'))
        with self.db.transaction(write=True) as q:
            if q.one('SELECT id FROM pilot_users WHERE email=? OR rut=?', (email, rut)):
                raise Problem('No se puede registrar esa cuenta. Si ya la solicitaste, consulta en biblioteca.', 409)
            user_id = str(uuid.uuid4())
            q.run('INSERT INTO pilot_users (id,name,email,rut,password_hash,role,status,created_at) VALUES (?,?,?,?,?,?,?,?)',
                  (user_id, name, email, rut, password_hash, 'student', 'pending', self.clock().isoformat()))
            self.audit(q, user_id, 'account_requested', user_id)
        return {'message': 'Solicitud recibida. Acércate a biblioteca para validar tu identidad y activar tu cuenta.'}

    def bootstrap_admin(self, name, email, password):
        name, email = clean_name(name), clean_email(email, student=False)
        encoded = hash_password(password)
        with self.db.transaction(write=True) as q:
            if q.one("SELECT id FROM pilot_users WHERE role='admin'"):
                raise Problem('Ya existe un administrador. No se modificó ninguna cuenta.', 409)
            uid = str(uuid.uuid4())
            q.run('INSERT INTO pilot_users (id,name,email,password_hash,role,status,created_at) VALUES (?,?,?,?,?,?,?)',
                  (uid, name, email, encoded, 'admin', 'active', self.clock().isoformat()))
            self.audit(q, uid, 'admin_created', uid)

    def login(self, data):
        email = clean_email(data.get('email'), student=False)
        self.throttle('login-email', email, 10)
        with self.db.transaction() as q:
            user = q.one('SELECT * FROM pilot_users WHERE email=?', (email,))
        valid = verify_password(data.get('password'), user['password_hash'] if user else self.dummy_hash)
        if not valid or not user:
            raise Problem('Correo o contraseña incorrectos.', 401)
        if user['status'] != 'active':
            raise Problem('Tu cuenta todavía no está habilitada. Consulta con el encargado de biblioteca.', 403)
        raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self.db.transaction(write=True) as q:
            # Revalidar después del cálculo de contraseña: puede haber sido desactivado.
            fresh = q.one('SELECT * FROM pilot_users WHERE id=?', (user['id'],))
            if fresh['status'] != 'active' or fresh['password_hash'] != user['password_hash']:
                raise Problem('La cuenta cambió. Vuelve a iniciar sesión.', 401)
            q.run('DELETE FROM pilot_sessions WHERE expires_at <= ?', (self.clock().timestamp(),))
            q.run('INSERT INTO pilot_sessions VALUES (?,?,?,?)',
                  (digest, user['id'], csrf, self.clock().timestamp() + SESSION_SECONDS))
        return raw, {'user': public_user(fresh), 'csrf': csrf}

    def recover_admin(self, email, password):
        email = clean_email(email, student=False)
        encoded = hash_password(password)
        with self.db.transaction(write=True) as q:
            user = q.one("SELECT id FROM pilot_users WHERE email=? AND role='admin'", (email,))
            if not user:
                raise Problem('No existe un administrador con ese correo.', 404)
            q.run('UPDATE pilot_users SET password_hash=?, must_change=0 WHERE id=?', (encoded, user['id']))
            q.run('DELETE FROM pilot_sessions WHERE user_id=?', (user['id'],))
            self.audit(q, user['id'], 'admin_password_recovered_from_server', user['id'])

    def authenticate(self, raw):
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self.db.transaction() as q:
            record = q.one('''SELECT u.*, s.csrf, s.digest FROM pilot_users u
                JOIN pilot_sessions s ON s.user_id=u.id
                WHERE s.digest=? AND s.expires_at>? AND u.status='active' ''',
                (digest, self.clock().timestamp()))
        if not record:
            raise Problem('Tu sesión terminó. Ingresa nuevamente.', 401)
        return record

    def logout(self, user):
        with self.db.transaction(write=True) as q:
            q.run('DELETE FROM pilot_sessions WHERE digest=?', (user['digest'],))
        return {'message': 'Sesión cerrada.'}

    def change_password(self, user, data):
        if not verify_password(data.get('current_password'), user['password_hash']):
            raise Problem('La contraseña actual no coincide.', 400)
        encoded = hash_password(data.get('password'))
        with self.db.transaction(write=True) as q:
            self.active_user(q, user)
            q.run('UPDATE pilot_users SET password_hash=?, must_change=0 WHERE id=?', (encoded, user['id']))
            q.run('DELETE FROM pilot_sessions WHERE user_id=?', (user['id'],))
            self.audit(q, user['id'], 'password_changed', user['id'])
        return {'message': 'Contraseña actualizada. Ingresa con tu nueva contraseña.'}

    def active_user(self, q, user, role=None):
        fresh = q.one('SELECT * FROM pilot_users WHERE id=?', (user['id'],))
        if not fresh or fresh['status'] != 'active':
            raise Problem('La cuenta no está habilitada.', 403)
        if role and fresh['role'] != role:
            raise Problem('No tienes permiso para realizar esta acción.', 403)
        # Cuando la llamada procede de HTTP, volver a verificar la sesión bajo el bloqueo.
        if 'digest' in user and not q.one('SELECT digest FROM pilot_sessions WHERE digest=? AND expires_at>?',
                                         (user['digest'], self.clock().timestamp())):
            raise Problem('Tu sesión terminó. Ingresa nuevamente.', 401)
        return fresh

    def users(self, user):
        with self.db.transaction() as q:
            self.active_user(q, user, 'admin')
            return {'users': [public_user(u) for u in q.all("SELECT * FROM pilot_users WHERE role='student' ORDER BY created_at DESC")]}

    def update_user(self, actor, uid, data):
        with self.db.transaction(write=True) as q:
            self.active_user(q, actor, 'admin')
            user = q.one("SELECT * FROM pilot_users WHERE id=? AND role='student'", (uid,))
            if not user:
                raise Problem('No se encontró el estudiante.', 404)
            action = data.get('action')
            if action == 'reset_password':
                password = secrets.token_urlsafe(14)
                q.run('UPDATE pilot_users SET password_hash=?, must_change=1 WHERE id=?', (hash_password(password), uid))
                q.run('DELETE FROM pilot_sessions WHERE user_id=?', (uid,))
                self.audit(q, actor['id'], action, uid)
                return {'temporary_password': password, 'message': 'Entrega esta contraseña al estudiante por un canal privado. Deberá cambiarla al ingresar.'}
            if action not in ('approve', 'disable'):
                raise Problem('Acción no válida.')
            if action == 'disable' and q.one('SELECT booking_id FROM pilot_members WHERE user_id=? AND day>=? AND active=1', (uid, self.clock().date().isoformat())):
                raise Problem('Primero cancela las reservas vigentes en las que participa el estudiante.', 409)
            status = 'active' if action == 'approve' else 'disabled'
            q.run('UPDATE pilot_users SET status=? WHERE id=?', (status, uid))
            q.run('DELETE FROM pilot_sessions WHERE user_id=?', (uid,))
            self.audit(q, actor['id'], action, uid)
        return {'message': 'Estado de la cuenta actualizado.'}

    def find_member(self, actor, data):
        rut = clean_rut(data.get('rut'))
        with self.db.transaction() as q:
            self.active_user(q, actor, 'student')
            user = q.one("SELECT id,name FROM pilot_users WHERE rut=? AND status='active' AND role='student'", (rut,))
        if not user:
            raise Problem('No hay un estudiante habilitado con ese RUT. Debe solicitar y activar su cuenta en biblioteca.', 404)
        return user

    def availability(self, actor):
        instant = self.clock()
        day = instant.date().isoformat()
        with self.db.transaction() as q:
            self.active_user(q, actor)
            occupied = q.all("SELECT room,block FROM pilot_bookings WHERE day=? AND status='active'", (day,))
            mine = q.all('SELECT block FROM pilot_members WHERE user_id=? AND day=? AND active=1', (actor['id'], day))
        past = [i for i in range(len(BLOCKS)) if (instant.hour, instant.minute) >= (8 + i * 2, 0)]
        return {'day': day, 'rooms': ROOMS, 'blocks': BLOCKS, 'occupied': occupied, 'past_blocks': past,
                'my_blocks': [x['block'] for x in mine], 'max_daily': MAX_DAILY, 'server_time': instant.isoformat()}

    def bookings(self, actor, day=None):
        day = parse_day(day or self.clock().date().isoformat())
        with self.db.transaction() as q:
            self.active_user(q, actor)
            sql = '''SELECT b.*, u.name AS owner_name FROM pilot_bookings b
                     JOIN pilot_users u ON u.id=b.owner_id WHERE b.day=?'''
            params = [day]
            if actor['role'] != 'admin':
                sql += ' AND EXISTS (SELECT 1 FROM pilot_members m WHERE m.booking_id=b.id AND m.user_id=?)'
                params.append(actor['id'])
            rows = q.all(sql + ' ORDER BY b.block,b.room,b.created_at', params)
            for booking in rows:
                columns = 'u.id,u.name,u.rut' if actor['role'] == 'admin' else 'u.id,u.name'
                booking['members'] = q.all(f'SELECT {columns} FROM pilot_users u JOIN pilot_members m ON m.user_id=u.id WHERE m.booking_id=? ORDER BY u.name', (booking['id'],))
        return {'bookings': rows, 'day': day}

    def reserve(self, actor, data):
        room, block = data.get('room'), data.get('block')
        if type(room) is not int or room not in [r['id'] for r in ROOMS]:
            raise Problem('Selecciona una sala válida.')
        if type(block) is not int or not 0 <= block < len(BLOCKS):
            raise Problem('Selecciona un bloque válido.')
        members = data.get('members', [])
        if not isinstance(members, list) or any(not isinstance(x, str) for x in members):
            raise Problem('La lista de integrantes no es válida.')
        members = [actor['id']] + members
        if len(set(members)) != len(members):
            raise Problem('No repitas integrantes. El responsable ya está incluido.')
        capacity = next(r['capacity'] for r in ROOMS if r['id'] == room)
        if len(members) > capacity:
            raise Problem(f'Esta sala admite hasta {capacity} personas, incluido el responsable.')
        with self.db.transaction(write=True) as q:
            self.active_user(q, actor, 'student')
            # Consultar el reloj dentro del bloqueo, incluso después de esperar otra transacción.
            instant = self.clock()
            day = instant.date().isoformat()
            if data.get('day') != day:
                raise Problem('La fecha cambió. Actualiza la disponibilidad y vuelve a intentar.', 409)
            if (instant.hour, instant.minute) >= (8 + 2 * block, 0):
                raise Problem('El bloque ya comenzó. Elige un horario posterior.', 409)
            if q.one("SELECT id FROM pilot_bookings WHERE room=? AND block=? AND day=? AND status='active'", (room, block, day)):
                raise Problem('Otra persona acaba de reservar este bloque. Elige otro horario.', 409)
            for uid in members:
                member = q.one("SELECT id FROM pilot_users WHERE id=? AND role='student' AND status='active'", (uid,))
                if not member:
                    raise Problem('Todos los integrantes deben tener una cuenta habilitada.', 409)
                records = q.all('SELECT block FROM pilot_members WHERE user_id=? AND day=? AND active=1', (uid, day))
                if any(x['block'] == block for x in records):
                    raise Problem('Tú o un integrante ya participan en una reserva en ese horario.', 409)
                if len(records) >= MAX_DAILY:
                    raise Problem('Tú o un integrante ya alcanzaron los dos bloques permitidos para hoy.', 409)
            bid = str(uuid.uuid4())
            q.run('INSERT INTO pilot_bookings (id,room,block,day,owner_id,status,created_at) VALUES (?,?,?,?,?,?,?)',
                  (bid, room, block, day, actor['id'], 'active', instant.isoformat()))
            for uid in members:
                q.run('INSERT INTO pilot_members VALUES (?,?,?,?,1)', (bid, uid, day, block))
            self.audit(q, actor['id'], 'booking_created', bid)
        return {'id': bid, 'message': 'Reserva confirmada. Ya puedes verla en Mis reservas.'}

    def cancel(self, actor, bid, data):
        reason = data.get('reason', '')
        if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 300:
            raise Problem('Indica un motivo de entre 3 y 300 caracteres.')
        with self.db.transaction(write=True) as q:
            self.active_user(q, actor)
            booking = q.one('SELECT * FROM pilot_bookings WHERE id=?', (bid,))
            if not booking:
                raise Problem('No se encontró la reserva.', 404)
            if actor['role'] != 'admin' and booking['owner_id'] != actor['id']:
                raise Problem('Solo el responsable o el encargado puede cancelar esta reserva.', 403)
            instant = self.clock()
            if actor['role'] != 'admin' and (booking['day'] < instant.date().isoformat() or
                    (booking['day'] == instant.date().isoformat() and (instant.hour, instant.minute) >= (8 + booking['block'] * 2, 0))):
                raise Problem('El bloque ya comenzó. Solicita la cancelación en biblioteca.', 409)
            if booking['status'] == 'cancelled':
                return {'message': 'La reserva ya estaba cancelada.'}
            q.run("UPDATE pilot_bookings SET status='cancelled',cancelled_at=?,cancelled_by=?,reason=? WHERE id=?",
                  (instant.isoformat(), actor['id'], reason.strip(), bid))
            q.run('UPDATE pilot_members SET active=0 WHERE booking_id=?', (bid,))
            self.audit(q, actor['id'], 'booking_cancelled', bid)
        return {'message': 'Reserva cancelada. El bloque vuelve a estar disponible.'}
