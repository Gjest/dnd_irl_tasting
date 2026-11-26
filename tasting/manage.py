"""Login management. Passphrases are only ever shown here, on your terminal, and
are never written to disk or to the server logs.

  python -m tasting.manage init            create logins for everyone in PLAYERS
  python -m tasting.manage add "Name"      add a player
  python -m tasting.manage reset "Name"    give someone a new passphrase
  python -m tasting.manage list            show who has a login
  python -m tasting.manage muster-zurueckholen cola
                                           bring back a deleted built-in tasting (chips, cola, wasser);
                                           its data comes back by hand from data/backups
"""

import argparse
import os
import sys

from . import accounts, security
from .accounts import ADMIN_ID
from .store import Store

DEFAULT_PLAYERS = "Der Lenny,Milka,Spargehirn,Waschschlappen,Rentier"


def _create(users, uid, name, role):
    return accounts.create(users, name, role, uid=uid)[1]


def _print_table(created):
    if not created:
        print("Nichts zu tun, alle Logins existieren schon.")
        return
    width = max(len(name) for name, _ in created)
    print("\nDiese Passphrasen werden nur jetzt angezeigt. Notiere oder verteile sie:\n")
    for name, passphrase in created:
        print(f"  {name.ljust(width)}  {passphrase}")
    print()


def _find(users, name):
    needle = security.slugify(name)
    if needle in users:
        return needle
    sys.exit(f"Kein Login für '{name}'. Vorhanden: {', '.join(u['name'] for u in users.values())}")


def _restore_sample(slug):
    """Removes a built-in tasting's "deleted" mark in start.json, so it shows up again (empty)."""
    import json

    from .registry import BY_SLUG
    from .store import write_json_atomic

    if slug not in BY_SLUG:
        sys.exit(f"Kein mitgeliefertes Tasting '{slug}'. Vorhanden: {', '.join(BY_SLUG)}")
    path = Store(os.environ.get("DATA_DIR", "./data")).data_dir / "start.json"
    start = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if slug not in start.get("deleted", []):
        print(f"'{slug}' ist nicht gelöscht.")
        return
    start["deleted"] = [d for d in start["deleted"] if d != slug]
    write_json_atomic(path, start)
    print(f"'{slug}' ist wieder da, ohne Daten. Ältere Daten liegen unter data/backups. "
          "Danach den Container neu starten, damit die App die Änderung liest.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["init", "add", "reset", "list", "muster-zurueckholen"])
    parser.add_argument("name", nargs="?")
    args = parser.parse_args(argv)
    if args.command in ("add", "reset", "muster-zurueckholen") and not args.name:
        parser.error(f"{args.command} braucht einen Namen")
    if args.command == "muster-zurueckholen":
        return _restore_sample(args.name)

    store = Store(os.environ.get("DATA_DIR", "./data"))
    users = store.users()
    created = []

    if args.command == "init":
        if ADMIN_ID not in users:
            created.append(("Admin", _create(users, ADMIN_ID, "Admin", "admin")))
        names = os.environ.get("PLAYERS") or DEFAULT_PLAYERS
        for name in (n.strip() for n in names.split(",")):
            uid = security.slugify(name)
            if uid and uid not in users:
                created.append((name, _create(users, uid, name, "player")))
    elif args.command == "add":
        uid = security.slugify(args.name)
        if not uid or uid == ADMIN_ID:
            sys.exit("Dieser Name geht nicht.")
        if uid in users:
            sys.exit(f"'{args.name}' existiert schon. Für eine neue Passphrase: reset")
        created.append((args.name, _create(users, uid, args.name, "player")))
    elif args.command == "reset":
        uid = _find(users, args.name)
        created.append((users[uid]["name"], accounts.reset(users, uid)))
    elif args.command == "list":
        for user in users.values():
            print(f"{user['name']} ({user['role']}{'' if accounts.is_active(user) else ', deaktiviert'})")
        return

    store.save_users(users)
    _print_table(created)


if __name__ == "__main__":
    main()
