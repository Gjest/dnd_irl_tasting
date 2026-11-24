"""Logins, shared by the command line (manage.py) and the admin panel.

users.json maps a uid to {"name", "role", "hash"} and, optionally,
"active": false for someone who may no longer log in. A missing "active"
means active, so files from before this field keep working.

Passphrases leave these functions exactly once, as return values. Callers
show them to a person and never store or log them.
"""

from . import security

ADMIN_ID = "admin"
ROLES = {"player": "Spieler", "admin": "Admin"}
MAX_NAME = 40


class AccountError(ValueError):
    pass


def is_active(user):
    return user.get("active", True)


def _set_passphrase(user):
    passphrase = security.generate_passphrase()
    user["hash"] = security.hash_passphrase(passphrase)
    return passphrase


def create(users, name, role="player", uid=None):
    """Adds a login and returns (uid, passphrase). Raises AccountError if it can't."""
    name = (name or "").strip()[:MAX_NAME]
    uid = uid or security.slugify(name)
    if not name or not uid:
        raise AccountError("Dieser Name geht nicht.")
    if role not in ROLES:
        raise AccountError("Unbekannte Rolle.")
    if uid in users:
        raise AccountError(f"„{name}“ gibt es schon. Für eine neue Passphrase: zurücksetzen.")
    users[uid] = {"name": name, "role": role}
    return uid, _set_passphrase(users[uid])


def reset(users, uid):
    """A new passphrase. Every running session of that person ends with it."""
    return _set_passphrase(users[uid])


def active_admins(users):
    return [uid for uid, user in users.items() if user.get("role") == "admin" and is_active(user)]


def check_can_lose_admin(users, uid, acting_uid):
    """Raises unless uid may stop being an active admin (demoted, deactivated or deleted)."""
    if uid == acting_uid:
        raise AccountError("Das geht nicht mit dem eigenen Login.")
    if users[uid].get("role") == "admin" and is_active(users[uid]) and active_admins(users) == [uid]:
        raise AccountError("Mindestens ein Admin muss bleiben.")
