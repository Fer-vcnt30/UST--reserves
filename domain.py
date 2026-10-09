"""Reglas del piloto. No contiene dependencias web ni datos institucionales."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('America/Santiago')
BLOCKS = [f'{h:02}:00 - {h + 2:02}:00' for h in range(8, 20, 2)]
ROOMS = [{'id': i, 'name': f'Sala {i}', 'capacity': 6} for i in range(1, 8)]
MAX_DAILY = 2

class Problem(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status

def now():
    return datetime.now(ZONE)

def clean_name(value):
    if not isinstance(value, str):
        raise Problem('Escribe tu nombre completo.')
    value = ' '.join(value.split())
    if not 3 <= len(value) <= 100 or any(c in value for c in '<>'):
        raise Problem('El nombre debe tener entre 3 y 100 caracteres.')
    return value

def clean_email(value, student=True):
    if not isinstance(value, str):
        raise Problem('Escribe un correo válido.')
    value = value.strip().lower()
    if len(value) > 254 or not re.fullmatch(r'[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}', value):
        raise Problem('Escribe un correo válido.')
    if student and value.split('@')[1] != 'alumnos.santotomas.cl':
        raise Problem('Usa tu correo @alumnos.santotomas.cl.')
    return value

def clean_rut(value):
    if not isinstance(value, str):
        raise Problem('Escribe un RUT válido con dígito verificador.')
    raw = value.replace('.', '').replace('-', '').strip().upper()
    if not re.fullmatch(r'[1-9][0-9]{6,7}[0-9K]', raw):
        raise Problem('El RUT debe incluir un dígito verificador válido.')
    total = sum(int(d) * (2 + i % 6) for i, d in enumerate(reversed(raw[:-1])))
    check = 11 - total % 11
    expected = '0' if check == 11 else 'K' if check == 10 else str(check)
    if raw[-1] != expected:
        raise Problem('El dígito verificador del RUT no coincide.')
    return raw[:-1] + '-' + raw[-1]

def validate_password(value):
    if not isinstance(value, str) or not 12 <= len(value) <= 128:
        raise Problem('La contraseña debe tener entre 12 y 128 caracteres.')
    return value

def hash_password(value):
    validate_password(value)
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', value.encode(), salt.encode(), 600_000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'

def verify_password(value, encoded):
    if not isinstance(value, str) or len(value) > 128:
        return False
    _, iterations, salt, digest = encoded.split('$')
    actual = hashlib.pbkdf2_hmac('sha256', value.encode(), salt.encode(), int(iterations)).hex()
    return hmac.compare_digest(actual, digest)

def public_user(user):
    return {k: user[k] for k in ('id', 'name', 'email', 'rut', 'role', 'status', 'must_change')}

def parse_day(value):
    from datetime import date
    try:
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError()
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise Problem('La fecha debe usar el formato AAAA-MM-DD.')
