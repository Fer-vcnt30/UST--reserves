import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from app import Application
from domain import Problem, ZONE, clean_rut, hash_password, verify_password
from service import Service
from storage import Database

PASSWORD = 'Clave exclusiva de pruebas 2026'

def rut(number):
    total = sum(int(d) * (2+i%6) for i,d in enumerate(reversed(str(number))))
    digit = 11-total%11
    return str(number)+'-'+('0' if digit==11 else 'K' if digit==10 else str(digit))

class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded = hash_password(PASSWORD)

    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / 'instance' / 'tests'
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.db = Database(url='', path=str(Path(self.temp.name)/'test.sqlite3'))
        self.db.initialize()
        self.instant = datetime(2026,10,9,7,30,tzinfo=ZONE)
        self.service = Service(self.db, clock=lambda:self.instant)
        self.web = Application(self.service)
        with self.db.transaction(write=True) as q:
            for i in range(10):
                q.run('INSERT INTO pilot_users VALUES (?,?,?,?,?,?,?,?,?)',
                      (str(i),f'Estudiante {i}',f'estudiante{i}@alumnos.santotomas.cl',rut(12000000+i),self.encoded,'student','active',0,self.instant.isoformat()))
            q.run('INSERT INTO pilot_users VALUES (?,?,?,?,?,?,?,?,?)',
                  ('admin','Encargado Biblioteca','encargado@example.com',None,self.encoded,'admin','active',0,self.instant.isoformat()))
        self.student=self.user('0');self.other=self.user('1');self.admin=self.user('admin')

    def tearDown(self):
        allowed = Path(__file__).resolve().parents[1] / 'instance' / 'tests'
        self.assertTrue(Path(self.temp.name).resolve().is_relative_to(allowed.resolve()))
        self.temp.cleanup()

    def user(self, uid):
        with self.db.transaction() as q:
            return q.one('SELECT * FROM pilot_users WHERE id=?',(uid,))

    def booking(self, user=None, room=1, block=0, members=None, **extra):
        return self.service.reserve(user or self.student,{'room':room,'block':block,'members':members or [],'day':self.instant.date().isoformat(),**extra})

    def rejected(self, callable_, code=409):
        with self.assertRaises(Problem) as error: callable_()
        self.assertEqual(error.exception.status,code)

    def request(self,path,method='GET',data=None,token='',csrf='',origin='http://127.0.0.1:8000',raw=None):
        body=raw if raw is not None else json.dumps(data or {}).encode()
        route,_,query=path.partition('?')
        env={'PATH_INFO':route,'QUERY_STRING':query,'REQUEST_METHOD':method,'CONTENT_TYPE':'application/json',
             'CONTENT_LENGTH':str(len(body)),'wsgi.input':io.BytesIO(body),'HTTP_ORIGIN':origin,
             'HTTP_COOKIE':'ust_session='+token,'HTTP_X_CSRF_TOKEN':csrf,'REMOTE_ADDR':'127.0.0.1'}
        response={}
        def start(status,headers):response.update(status=int(status.split()[0]),headers=dict(headers))
        payload=b''.join(self.web(env,start))
        response['body']=json.loads(payload) if 'application/json' in response['headers']['Content-Type'] else payload
        return response

    def session(self,user=None):
        return self.service.login({'email':(user or self.student)['email'],'password':PASSWORD})

    def test_rut_check_digit_and_normalization(self):
        self.assertEqual(clean_rut('12.345.678-5'),'12345678-5')
        self.rejected(lambda:clean_rut('12345678-9'),400)

    def test_hash_not_plaintext_and_wrong_password(self):
        self.assertNotIn(PASSWORD,self.encoded)
        self.assertTrue(verify_password(PASSWORD,self.encoded))
        self.assertFalse(verify_password('contraseña incorrecta',self.encoded))

    def test_registration_cannot_select_admin_or_active(self):
        self.service.register({'name':'Cuenta Nueva','email':'nueva@alumnos.santotomas.cl','rut':rut(14000000),'password':PASSWORD,'role':'admin','status':'active'})
        with self.db.transaction() as q: user=q.one('SELECT * FROM pilot_users WHERE email=?',('nueva@alumnos.santotomas.cl',))
        self.assertEqual((user['role'],user['status']),('student','pending'))
        self.rejected(lambda:self.service.login({'email':user['email'],'password':PASSWORD}),403)

    def test_rejects_nonstudent_email_and_weak_password(self):
        data={'name':'Cuenta Nueva','email':'nueva@santotomas.cl','rut':rut(14000000),'password':PASSWORD}
        self.rejected(lambda:self.service.register(data),400)
        data.update(email='nueva@alumnos.santotomas.cl',password='1234')
        self.rejected(lambda:self.service.register(data),400)

    def test_duplicate_identity_rejected(self):
        self.rejected(lambda:self.service.register({'name':'Otra Persona','email':'otra@alumnos.santotomas.cl','rut':self.student['rut'],'password':PASSWORD}))

    def test_wrong_password_rejected(self):
        self.rejected(lambda:self.service.login({'email':self.student['email'],'password':'inventada'}),401)

    def test_session_digest_and_logout_revocation(self):
        raw,session=self.session()
        user=self.service.authenticate(raw)
        self.assertEqual(user['id'],self.student['id'])
        with self.db.transaction() as q:
            stored=q.one('SELECT * FROM pilot_sessions')
        self.assertNotEqual(stored['digest'],raw)
        self.assertEqual(stored['digest'],hashlib.sha256(raw.encode()).hexdigest())
        self.service.logout(user)
        self.rejected(lambda:self.service.authenticate(raw),401)

    def test_session_expires(self):
        raw,_=self.session();self.instant+=timedelta(hours=8)
        self.rejected(lambda:self.service.authenticate(raw),401)

    def test_password_change_invalidates_all_sessions(self):
        first,_=self.session();second,_=self.session()
        self.service.change_password(self.service.authenticate(first),{'current_password':PASSWORD,'password':'Mi nueva contraseña de prueba'})
        self.rejected(lambda:self.service.authenticate(first),401)
        self.rejected(lambda:self.service.authenticate(second),401)

    def test_admin_recovery_revokes_sessions_and_preserves_role(self):
        raw,_=self.session(self.admin)
        self.service.recover_admin(self.admin['email'],'Nueva clave del encargado')
        self.rejected(lambda:self.service.authenticate(raw),401)
        self.assertEqual(self.user('admin')['role'],'admin')
        self.rejected(lambda:self.service.recover_admin(self.student['email'],PASSWORD),404)

    def test_bootstrap_cannot_replace_existing_admin(self):
        self.rejected(lambda:self.service.bootstrap_admin('Otra Persona','otra@example.com',PASSWORD))
        self.assertEqual(self.user('admin')['password_hash'],self.encoded)

    def test_no_authentication_no_data(self):
        for path in ['/api/availability','/api/bookings','/api/admin/users']:
            self.assertEqual(self.request(path)['status'],401)

    def test_csrf_and_origin_enforced(self):
        raw,session=self.session()
        self.assertEqual(self.request('/api/bookings','POST',{},raw)['status'],403)
        self.assertEqual(self.request('/api/bookings','POST',{},raw,session['csrf'],origin='https://evil.example')['status'],403)

    def test_security_headers_and_cookie(self):
        self.web.secure=True
        response=self.request('/api/login','POST',{'email':self.student['email'],'password':PASSWORD})
        self.assertEqual(response['status'],200)
        for flag in ['HttpOnly','SameSite=Lax','Secure']:self.assertIn(flag,response['headers']['Set-Cookie'])
        self.assertEqual(response['headers']['Cache-Control'],'no-store')
        self.assertIn("script-src 'self'",response['headers']['Content-Security-Policy'])

    def test_http_booking_and_cancel_flow(self):
        raw,session=self.session()
        response=self.request('/api/bookings','POST',{'day':'2026-10-09','room':1,'block':0,'members':['1']},raw,session['csrf'])
        self.assertEqual(response['status'],201)
        bid=response['body']['id']
        self.assertEqual(self.request('/api/bookings',token=raw)['body']['bookings'][0]['id'],bid)
        response=self.request('/api/bookings/'+bid+'/cancel','POST',{'reason':'No asistiremos'},raw,session['csrf'])
        self.assertEqual(response['status'],200)
        self.assertEqual(self.service.availability(self.student)['occupied'],[])

    def test_room_cannot_be_double_booked(self):
        self.booking()
        self.rejected(lambda:self.booking(self.other))

    def test_owner_cannot_book_two_rooms_at_same_time(self):
        self.booking();self.rejected(lambda:self.booking(room=2))

    def test_member_cannot_overlap_another_group(self):
        self.booking(members=['1'])
        self.rejected(lambda:self.booking(self.user('2'),room=2,members=['1']))
        self.rejected(lambda:self.booking(self.other,room=2))

    def test_owner_cannot_bypass_identity_via_payload(self):
        bid=self.booking(owner_id='1',usuario=self.other['email'])['id']
        with self.db.transaction() as q: owner=q.one('SELECT owner_id FROM pilot_bookings WHERE id=?',(bid,))
        self.assertEqual(owner['owner_id'],self.student['id'])

    def test_daily_limit_includes_membership(self):
        self.booking(members=['1']);self.booking(self.user('2'),block=1,members=['1'])
        self.rejected(lambda:self.booking(self.other,block=2))

    def test_capacity_and_duplicate_members(self):
        self.rejected(lambda:self.booking(members=['1','2','3','4','5','6']),400)
        self.rejected(lambda:self.booking(members=['1','1']),400)
        self.rejected(lambda:self.booking(members=['0']),400)

    def test_pending_or_admin_cannot_be_member(self):
        with self.db.transaction(write=True) as q:q.run("UPDATE pilot_users SET status='pending' WHERE id='1'")
        self.rejected(lambda:self.booking(members=['1']))
        self.rejected(lambda:self.booking(members=['admin']))

    def test_invalid_room_block_and_old_day(self):
        self.rejected(lambda:self.booking(room=99),400)
        self.rejected(lambda:self.booking(block=True),400)
        self.rejected(lambda:self.booking(block=6),400)
        self.rejected(lambda:self.booking(day='2026-10-08'))

    def test_past_block_rejected_and_chile_day_used(self):
        self.instant=self.instant.replace(hour=8,minute=0)
        self.rejected(lambda:self.booking())
        self.assertEqual(self.service.availability(self.student)['day'],'2026-10-09')

    def test_only_owner_or_admin_can_cancel(self):
        bid=self.booking(members=['1'])['id']
        self.rejected(lambda:self.service.cancel(self.other,bid,{'reason':'Quiero cancelar'}),403)
        self.service.cancel(self.admin,bid,{'reason':'Solicitud del grupo'})
        self.assertEqual(self.service.availability(self.student)['my_blocks'],[])

    def test_cancellation_releases_room_and_all_members_but_preserves_history(self):
        bid=self.booking(members=['1'])['id']
        self.service.cancel(self.student,bid,{'reason':'Cambio de planes'})
        self.booking(self.other)
        history=self.service.bookings(self.student)['bookings']
        self.assertEqual(history[0]['status'],'cancelled')
        self.assertEqual(history[0]['reason'],'Cambio de planes')

    def test_student_cannot_cancel_after_start(self):
        bid=self.booking()['id'];self.instant=self.instant.replace(hour=8)
        self.rejected(lambda:self.service.cancel(self.student,bid,{'reason':'Cambio de planes'}))
        self.service.cancel(self.admin,bid,{'reason':'Liberación en biblioteca'})

    def test_students_only_see_their_groups_no_rut_in_responses(self):
        self.booking(members=['1'])
        self.assertEqual(self.service.bookings(self.user('2'))['bookings'],[])
        mine=self.service.bookings(self.other)['bookings']
        self.assertEqual(len(mine),1)
        self.assertNotIn('rut',mine[0]['members'][0])
        self.assertIn('rut',self.service.bookings(self.admin)['bookings'][0]['members'][0])
        public=json.dumps(self.service.availability(self.user('2')))
        self.assertNotIn(self.student['email'],public)
        self.assertNotIn(self.student['rut'],public)

    def test_student_cannot_administer_or_admin_reserve(self):
        self.rejected(lambda:self.service.users(self.student),403)
        self.rejected(lambda:self.service.update_user(self.student,'1',{'action':'approve'}),403)
        self.rejected(lambda:self.booking(self.admin),403)

    def test_disable_blocks_until_bookings_cancelled_then_revokes(self):
        raw,_=self.session();bid=self.booking()['id']
        self.rejected(lambda:self.service.update_user(self.admin,'0',{'action':'disable'}))
        self.service.cancel(self.admin,bid,{'reason':'Baja del estudiante'})
        self.service.update_user(self.admin,'0',{'action':'disable'})
        self.rejected(lambda:self.service.authenticate(raw),401)

    def test_temporary_password_requires_change(self):
        password=self.service.update_user(self.admin,'0',{'action':'reset_password'})['temporary_password']
        raw,session=self.service.login({'email':self.student['email'],'password':password})
        self.assertEqual(self.request('/api/availability',token=raw)['status'],403)
        self.assertEqual(self.request('/api/session',token=raw)['status'],200)

    def test_throttle_persists(self):
        for _ in range(3):self.service.throttle('test','identity',3)
        self.rejected(lambda:self.service.throttle('test','identity',3),429)
        self.instant+=timedelta(minutes=16)
        self.service.throttle('test','identity',3)

    def test_simultaneous_room_requests_only_one_wins(self):
        def reserve(uid):
            try:self.booking(self.user(uid));return True
            except Problem:return False
        with ThreadPoolExecutor(max_workers=6) as pool: results=list(pool.map(reserve,[str(i) for i in range(6)]))
        self.assertEqual(sum(results),1)

    def test_simultaneous_person_requests_only_one_wins(self):
        def reserve(room):
            try:self.booking(room=room);return True
            except Problem:return False
        with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(reserve,range(1,7)))
        self.assertEqual(sum(results),1)

    def test_simultaneous_daily_quota_only_two_wins(self):
        def reserve(block):
            try:self.booking(block=block);return True
            except Problem:return False
        with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(reserve,range(6)))
        self.assertEqual(sum(results),2)

    def test_database_unique_indexes_are_second_defense(self):
        self.booking()
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db.transaction(write=True) as q:
                q.run('INSERT INTO pilot_bookings (id,room,block,day,owner_id,status,created_at) VALUES (?,?,?,?,?,?,?)',('direct',1,0,'2026-10-09','1','active',self.instant.isoformat()))

    def test_bad_json_large_body_and_legacy_routes_rejected(self):
        self.assertEqual(self.request('/api/login','POST',raw=b'{broken')['status'],400)
        self.assertEqual(self.request('/api/login','POST',raw=b'a'*17000)['status'],413)
        self.assertEqual(self.request('/reservas')['status'],404)

    def test_legacy_database_is_not_silently_overwritten(self):
        with self.db.transaction(write=True) as q:
            q.run('CREATE TABLE reservas (id TEXT)');q.run("INSERT INTO reservas VALUES ('legacy')")
        with self.assertRaises(RuntimeError):self.db.initialize()
        with self.db.transaction() as q:self.assertEqual(q.one('SELECT COUNT(*) AS n FROM reservas')['n'],1)

if __name__=='__main__':unittest.main()
