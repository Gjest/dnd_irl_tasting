"""JSON file persistence.

Two files live in the data directory:
  tasting.json  chips, ratings and game state. Safe to share and extract.
  users.json    logins with passphrase hashes. Never part of an export.

Every write goes to a temp file first and is then renamed over the original, so
a crash or power cut can't leave a half-written file behind.
"""

import copy
import json
import os
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path

BACKUP_INTERVAL_SECONDS = 300
BACKUPS_TO_KEEP = 100


def _empty_tasting():
    return {
        "version": 1,
        "phase": "tasting",  # tasting -> ceremony -> revealed
        "ceremony_order": [],
        "reveal_count": 0,
        "chips": [],
        "ratings": {},  # chip id -> player id -> rating
        "shopping": [],  # the shared shopping list before the tasting
    }


def _upgrade(tasting):
    tasting.setdefault("shopping", [])
    # List items from before photos and full bowl details lack these fields.
    for item in tasting["shopping"]:
        for key in ("price", "weight", "image"):
            item.setdefault(key, None)
    # Ratings from before the Sucht-Save stored their d20 value as "enjoyment".
    for ratings in tasting["ratings"].values():
        for rating in ratings.values():
            if "enjoyment" in rating:
                rating["dc"] = rating.pop("enjoyment")
    return tasting


def write_json_atomic(path, data, private=False):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Store:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.tasting_path = self.data_dir / "tasting.json"
        self.users_path = self.data_dir / "users.json"
        self.backup_dir = self.data_dir / "backups"
        self.images_dir = self.data_dir / "images"
        self._lock = threading.RLock()
        self._last_backup = 0.0
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(exist_ok=True)
        self.images_dir.mkdir(exist_ok=True)
        # A corrupt file raises here on purpose: better to refuse to start than
        # to silently overwrite ratings with an empty tasting.
        if self.tasting_path.exists():
            self._tasting = _upgrade(json.loads(self.tasting_path.read_text(encoding="utf-8")))
        else:
            self._tasting = _empty_tasting()
            write_json_atomic(self.tasting_path, self._tasting)

    def read(self):
        with self._lock:
            return copy.deepcopy(self._tasting)

    @contextmanager
    def edit(self):
        """Yield the live data and save it afterwards. An exception discards the edit."""
        with self._lock:
            draft = copy.deepcopy(self._tasting)
            yield draft
            write_json_atomic(self.tasting_path, draft)
            self._tasting = draft
            self._backup()

    def snapshot(self):
        """Backs up right now. Call this before anything that deletes data."""
        with self._lock:
            self._backup(force=True)

    def _backup(self, force=False):
        now = time.time()
        if not force and now - self._last_backup < BACKUP_INTERVAL_SECONDS:
            return
        self._last_backup = now
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        shutil.copyfile(self.tasting_path, self.backup_dir / f"tasting-{stamp}.json")
        for old in sorted(self.backup_dir.glob("tasting-*.json"))[:-BACKUPS_TO_KEEP]:
            old.unlink()

    # Users are re-read on every request so that passphrase changes made with
    # manage.py (a separate process) apply without restarting the server.
    def users(self):
        if not self.users_path.exists():
            return {}
        return json.loads(self.users_path.read_text(encoding="utf-8"))

    def save_users(self, users):
        write_json_atomic(self.users_path, users, private=True)
