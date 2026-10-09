"""SQLite para desarrollo; PostgreSQL para despliegue con varios procesos."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = [
    '''CREATE TABLE IF NOT EXISTS pilot_users (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
        rut TEXT UNIQUE, password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('admin','student')),
        status TEXT NOT NULL CHECK(status IN ('pending','active','disabled')),
        must_change INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS pilot_sessions (
        digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES pilot_users(id),
        csrf TEXT NOT NULL, expires_at DOUBLE PRECISION NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS pilot_attempts (
        key TEXT PRIMARY KEY, count INTEGER NOT NULL, started DOUBLE PRECISION NOT NULL)''',
    '''CREATE TABLE IF NOT EXISTS pilot_bookings (
        id TEXT PRIMARY KEY, room INTEGER NOT NULL, block INTEGER NOT NULL,
        day TEXT NOT NULL, owner_id TEXT NOT NULL REFERENCES pilot_users(id),
        status TEXT NOT NULL CHECK(status IN ('active','cancelled')),
        created_at TEXT NOT NULL, cancelled_at TEXT, cancelled_by TEXT REFERENCES pilot_users(id),
        reason TEXT)''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS pilot_room_slot
        ON pilot_bookings(room,day,block) WHERE status='active' ''',
    '''CREATE TABLE IF NOT EXISTS pilot_members (
        booking_id TEXT NOT NULL REFERENCES pilot_bookings(id),
        user_id TEXT NOT NULL REFERENCES pilot_users(id), day TEXT NOT NULL,
        block INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(booking_id,user_id))''',
    '''CREATE UNIQUE INDEX IF NOT EXISTS pilot_person_slot
        ON pilot_members(user_id,day,block) WHERE active=1''',
    '''CREATE TABLE IF NOT EXISTS pilot_audit (
        id TEXT PRIMARY KEY, actor_id TEXT, event TEXT NOT NULL,
        target_id TEXT, created_at TEXT NOT NULL)''',
]

class Database:
    def __init__(self, url=None, path=None):
        self.url = os.environ.get('DATABASE_URL') if url is None else url
        self.path = path or os.environ.get('SQLITE_PATH', 'instance/pilot.sqlite3')
        if not self.url:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        if self.url:
            import psycopg2
            import psycopg2.extras
            connection = psycopg2.connect(
                self.url, sslmode=os.environ.get('DB_SSLMODE', 'require'),
                connect_timeout=10, cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            connection = sqlite3.connect(self.path, timeout=20)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA busy_timeout=20000')
        return connection

    @contextmanager
    def transaction(self, write=False):
        connection = self.connect()
        cursor = connection.cursor()
        try:
            if write:
                if self.url:
                    cursor.execute('SELECT pg_advisory_xact_lock(7140392026)')
                else:
                    cursor.execute('BEGIN IMMEDIATE')
            yield Query(cursor, bool(self.url))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def initialize(self):
        with self.transaction(write=True) as q:
            if self.url:
                legacy = q.one("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name='reservas'")
            else:
                legacy = q.one("SELECT name FROM sqlite_master WHERE type='table' AND name='reservas'")
            if legacy and q.one('SELECT COUNT(*) AS n FROM reservas')['n']:
                raise RuntimeError('La base contiene reservas anteriores. Usa una base nueva para el piloto y conserva la anterior; la migración debe revisarse antes de reemplazar producción.')
            for statement in SCHEMA:
                q.run(statement)

class Query:
    def __init__(self, cursor, postgres):
        self.cursor, self.postgres = cursor, postgres

    def run(self, sql, params=()):
        self.cursor.execute(sql.replace('?', '%s') if self.postgres else sql, params)
        return self

    def one(self, sql, params=()):
        row = self.run(sql, params).cursor.fetchone()
        return dict(row) if row is not None else None

    def all(self, sql, params=()):
        return [dict(row) for row in self.run(sql, params).cursor.fetchall()]
