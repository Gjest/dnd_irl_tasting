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
    # Items used to point at one bowl. Now a bowl points at its item, since
    # one bag can fill several bowls.
    chips = {chip["id"]: chip for chip in tasting["chips"]}
    for item in tasting["shopping"]:
        chip = chips.get(item.pop("chip_id", None))
        if chip:
            chip.setdefault("item_id", item["id"])
    for chip in tasting["chips"]:
        chip.setdefault("item_id", None)
        # Whoever set a bowl up used to be whoever bought it.
        chip.setdefault("bought_by", chip.get("added_by"))
    # Ratings from before the Sucht-Save stored their d20 value as "enjoyment".
    for ratings in tasting["ratings"].values():
        for rating in ratings.values():
            if "enjoyment" in rating:
                rating["dc"] = rating.pop("enjoyment")
    return tasting


PHASES = ("tasting", "ceremony", "revealed")


def validate_tasting(data):
    """Returns what is wrong with an imported tasting, or None if it can be used."""
    if not isinstance(data, dict):
        return "Die Datei enthält kein JSON-Objekt."
    if data.get("phase") not in PHASES:
        return "Der Spielstand (phase) fehlt oder ist unbekannt."
    if not isinstance(data.get("chips"), list) or not isinstance(data.get("ratings"), dict):
        return "Schalen oder Wertungen fehlen."
    if not isinstance(data.get("shopping", []), list):
        return "Die Einkaufsliste ist kaputt."
    if not isinstance(data.get("ceremony_order", []), list) or not isinstance(data.get("reveal_count", 0), int):
        return "Der Stand der Enthüllung ist kaputt."
    for chip in data["chips"]:
        if not isinstance(chip, dict) or not isinstance(chip.get("id"), str) or not isinstance(chip.get("bowl"), int):
            return "Eine Schale hat keine gültige Id oder Nummer."
    for item in data.get("shopping", []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return "Ein Eintrag der Einkaufsliste hat keine gültige Id."
    for ratings in data["ratings"].values():
        if not isinstance(ratings, dict):
            return "Eine Wertung ist kaputt."
        for rating in ratings.values():
            dc = rating.get("dc", rating.get("enjoyment")) if isinstance(rating, dict) else None
            if not isinstance(dc, int) or not isinstance(rating.get("scores"), dict):
                return "Eine Wertung hat keinen DC oder keine Kategorien."
    return None


def write_json_atomic(path, data, private=False):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600 if private else 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class JsonDocument:
    """One JSON file, kept in memory, written atomically, with rolling backups.

    Every tasting keeps its data in one of these: the chips tasting in
    tasting.json, a finished tasting in <slug>.json. A new tasting reuses it.
    """

    def __init__(self, path, backup_dir, empty=None, upgrade=lambda data: data):
        self.path = Path(path)
        self.backup_dir = Path(backup_dir)
        self._upgrade = upgrade
        self._lock = threading.RLock()
        self._last_backup = 0.0
        # A corrupt file raises here on purpose: better to refuse to start than
        # to silently overwrite ratings with an empty tasting.
        if self.path.exists():
            self._data = upgrade(json.loads(self.path.read_text(encoding="utf-8")))
        elif empty is not None:
            self._data = empty()
            write_json_atomic(self.path, self._data)
        else:
            self._data = None  # nothing yet, e.g. a finished tasting before its upload

    def exists(self):
        return self._data is not None

    def read(self):
        with self._lock:
            return copy.deepcopy(self._data)

    @contextmanager
    def edit(self):
        """Yield the live data and save it afterwards. An exception discards the edit."""
        with self._lock:
            draft = copy.deepcopy(self._data)
            yield draft
            write_json_atomic(self.path, draft)
            self._data = draft
            self._backup()

    def replace(self, data):
        """Swaps in the whole document, keeping a backup of what was there."""
        with self._lock:
            if self._data is not None:
                self._backup(force=True)
            data = self._upgrade(data)
            write_json_atomic(self.path, data)
            self._data = data
            self._backup(force=True)

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
        prefix = self.path.stem
        shutil.copyfile(self.path, self.backup_dir / f"{prefix}-{stamp}.json")
        for old in sorted(self.backup_dir.glob(f"{prefix}-*.json"))[:-BACKUPS_TO_KEEP]:
            old.unlink()


class Store:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.users_path = self.data_dir / "users.json"
        self.backup_dir = self.data_dir / "backups"
        self.images_dir = self.data_dir / "images"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(exist_ok=True)
        self.images_dir.mkdir(exist_ok=True)
        self._tasting = JsonDocument(self.data_dir / "tasting.json", self.backup_dir, _empty_tasting, _upgrade)
        self.tasting_path = self._tasting.path
        self._documents = {}

    # The chips tasting. These keep their old names so the chips code stays as it was.
    def read(self):
        return self._tasting.read()

    def edit(self):
        return self._tasting.edit()

    def replace(self, tasting):
        """Swaps in a whole tasting, for example an edited export."""
        self._tasting.replace({**_empty_tasting(), **tasting})

    def snapshot(self):
        self._tasting.snapshot()

    def document(self, slug, empty=None):
        """data/<slug>.json, e.g. a finished tasting. Without `empty` it may not exist yet."""
        if slug not in self._documents:
            self._documents[slug] = JsonDocument(self.data_dir / f"{slug}.json", self.backup_dir, empty)
        return self._documents[slug]

    # Users are re-read on every request so that passphrase changes made with
    # manage.py (a separate process) apply without restarting the server.
    def users(self):
        if not self.users_path.exists():
            return {}
        return json.loads(self.users_path.read_text(encoding="utf-8"))

    def save_users(self, users):
        write_json_atomic(self.users_path, users, private=True)
