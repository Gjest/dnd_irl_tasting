"""Login, CSRF, rate limiting and response headers."""

import hmac
import os
import re
import secrets
import threading
import time
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from .catalog import PASSPHRASE_OBJECTS, PASSPHRASE_SUBJECTS, PASSPHRASE_VERBS

MAX_FAILS_PER_LOGIN = 6
MAX_FAILS_GLOBAL = 60
FAIL_WINDOW_SECONDS = 300

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; "
    "frame-ancestors 'none'"
)


def generate_passphrase():
    return "-".join([
        secrets.choice(PASSPHRASE_SUBJECTS),
        secrets.choice(PASSPHRASE_VERBS),
        secrets.choice(PASSPHRASE_OBJECTS),
        str(secrets.randbelow(900) + 100),
    ])


def normalize_passphrase(text):
    # Phones like to capitalize the first letter and append a space.
    return text.strip().lower()


def hash_passphrase(passphrase):
    return generate_password_hash(normalize_passphrase(passphrase), method="scrypt")


def verify_passphrase(stored_hash, attempt):
    return check_password_hash(stored_hash, normalize_passphrase(attempt))


# Compared against when the user doesn't exist, so that a wrong name takes as
# long as a wrong passphrase.
DUMMY_HASH = hash_passphrase(secrets.token_hex(16))


def slugify(name):
    table = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
    return re.sub(r"[^a-z0-9]+", "-", name.lower().translate(table)).strip("-")


def load_or_create_secret_key(data_dir):
    path = Path(data_dir) / "secret.key"
    if path.exists():
        return path.read_bytes()
    key = secrets.token_bytes(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def csrf_token_for(session):
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def csrf_valid(session, submitted):
    expected = session.get("csrf")
    return bool(expected and submitted and hmac.compare_digest(expected, submitted))


class LoginLimiter:
    """Counts failed logins in memory. Restarting the app resets the counters."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._fails = {}

    def _recent(self, key, now):
        recent = [t for t in self._fails.get(key, []) if now - t < FAIL_WINDOW_SECONDS]
        if recent:
            self._fails[key] = recent
        else:
            self._fails.pop(key, None)
        return recent

    def blocked(self, ip, user):
        now = self._clock()
        with self._lock:
            return (
                len(self._recent((ip, user), now)) >= MAX_FAILS_PER_LOGIN
                or len(self._recent("global", now)) >= MAX_FAILS_GLOBAL
            )

    def record_failure(self, ip, user):
        now = self._clock()
        with self._lock:
            for key in ((ip, user), "global"):
                self._fails.setdefault(key, []).append(now)

    def clear(self, ip, user):
        with self._lock:
            self._fails.pop((ip, user), None)


def apply_security_headers(response):
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if response.mimetype in ("text/html", "application/json", "text/csv"):
        response.headers["Cache-Control"] = "no-store"
    return response
