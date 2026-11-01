"""Login management. Passphrases are only ever shown here, on your terminal, and
are never written to disk or to the server logs.

  python -m tasting.manage init            create logins for everyone in PLAYERS
  python -m tasting.manage add "Name"      add a player
  python -m tasting.manage reset "Name"    give someone a new passphrase
  python -m tasting.manage list            show who has a login
"""

import argparse
import os
import sys

from . import security
from .store import Store

ADMIN_ID = "admin"
DEFAULT_PLAYERS = "Der Lenny,Milka,Spargehirn,Waschschlappen,Rentier"


def _create(users, uid, name, role):
    passphrase = security.generate_passphrase()
    users[uid] = {"name": name, "role": role, "hash": security.hash_passphrase(passphrase)}
    return passphrase


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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["init", "add", "reset", "list"])
    parser.add_argument("name", nargs="?")
    args = parser.parse_args(argv)
    if args.command in ("add", "reset") and not args.name:
        parser.error(f"{args.command} braucht einen Namen")

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
        created.append((users[uid]["name"], _create(users, uid, users[uid]["name"], users[uid]["role"])))
    elif args.command == "list":
        for user in users.values():
            print(f"{user['name']} ({user['role']})")
        return

    store.save_users(users)
    _print_table(created)


if __name__ == "__main__":
    main()
