"""End-to-end checks of the rules that matter: blindness, security, persistence, stats."""

import json
import os
import re
import tempfile
import unittest

from tasting import create_app, security, stats
from tasting.catalog import SCALE_KEYS
from tasting.manage import main as manage_main
from tasting.store import Store

PASS = "test-pass-phrase-111"


def add_user(store, uid, name, role="player"):
    users = store.users()
    users[uid] = {"name": name, "role": role, "hash": security.hash_passphrase(PASS)}
    store.save_users(users)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ.pop("PUBLIC_URL", None)
        self.app = create_app(self.tmp.name)
        self.store = self.app.extensions["store"]
        add_user(self.store, "admin", "Admin", "admin")
        for uid, name in (("a", "Alice"), ("b", "Bob"), ("c", "Cleo")):
            add_user(self.store, uid, name)

    def client(self, uid=None):
        client = self.app.test_client()
        if uid:
            response = self.post(client, "/login", user=uid, passphrase=PASS)
            self.assertEqual(response.status_code, 302)
        return client

    def token(self, client):
        html = client.get("/login", follow_redirects=True).get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def post(self, client, url, **fields):
        return client.post(url, data={"csrf_token": self.token(client), **fields})

    def add_chips(self):
        admin = self.client("admin")
        self.post(admin, "/chips", name="Geheimchip", brand="Funny", flavor_type="Paprika", price="1,99")
        self.post(admin, "/chips", name="Zweitchip", brand="Lorenz", flavor_type="Gesalzen", own_brand="on")
        self.post(admin, "/chips", name="Drittchip", brand="Pringles", flavor_type="BBQ", price="3")
        return admin, self.store.read()["chips"]

    def rate(self, client, chip_id, enjoyment, score=3, **extra):
        fields = {f"score_{k}": str(score) for k in SCALE_KEYS}
        return self.post(client, f"/schale/{chip_id}", enjoyment=str(enjoyment), **fields, **extra)


class Security(Base):
    def test_pages_need_login(self):
        client = self.client()
        for url in ("/", "/admin", "/ergebnisse", "/admin/export.json"):
            self.assertEqual(client.get(url).status_code, 302, url)
        for url in ("/api/progress", "/api/results", "/api/ceremony"):
            self.assertEqual(client.get(url).status_code, 401, url)

    def test_players_cannot_reach_admin(self):
        player = self.client("a")
        for url in ("/admin", "/admin/daten", "/admin/export.json", "/admin/export.csv", "/admin/qr.svg"):
            self.assertEqual(player.get(url).status_code, 403, url)
        self.assertEqual(self.post(player, "/admin/shuffle").status_code, 403)
        self.assertEqual(self.post(player, "/admin/reset", confirm="ASCHE").status_code, 403)
        self.assertEqual(self.post(player, "/admin/ceremony/start").status_code, 403)
        self.assertEqual(self.post(player, "/api/ceremony/next").status_code, 403)
        self.assertEqual(self.store.read()["chips"], [])

    def test_post_without_csrf_is_rejected(self):
        admin = self.client("admin")
        response = admin.post("/chips", data={"name": "x", "flavor_type": "BBQ"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.store.read()["chips"], [])
        self.assertEqual(self.app.test_client().post("/login", data={"user": "a", "passphrase": PASS}).status_code, 403)

    def test_wrong_passphrase_then_lockout(self):
        client = self.client()
        for _ in range(security.MAX_FAILS_PER_LOGIN):
            self.assertEqual(self.post(client, "/login", user="a", passphrase="wrong").status_code, 401)
        # The right passphrase no longer gets through.
        response = self.post(client, "/login", user="a", passphrase=PASS)
        self.assertEqual(response.status_code, 401)
        self.assertIn("Fehlversuche", response.get_data(as_text=True))

    def test_passphrase_forgives_phone_keyboards(self):
        client = self.client()
        self.assertEqual(self.post(client, "/login", user="a", passphrase=f" {PASS.capitalize()} ").status_code, 302)

    def test_passphrase_reset_ends_session(self):
        player = self.client("a")
        self.assertEqual(player.get("/").status_code, 200)
        users = self.store.users()
        users["a"]["hash"] = security.hash_passphrase("new-pass-phrase-222")
        self.store.save_users(users)
        self.assertEqual(player.get("/").status_code, 302)

    def test_headers(self):
        response = self.client().get("/login")
        csp = response.headers["Content-Security-Policy"]
        self.assertIn("script-src 'self'", csp)
        self.assertNotIn("unsafe", csp)
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        cookie = response.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_templates_have_no_inline_code_or_external_urls(self):
        root = os.path.join(os.path.dirname(stats.__file__), "templates")
        for name in os.listdir(root):
            with open(os.path.join(root, name), encoding="utf-8") as f:
                html = f.read()
            self.assertNotRegex(html, r"\sstyle=", name)
            self.assertNotRegex(html, r"\son\w+=", name)
            self.assertNotRegex(html, r"<script(?![^>]*src=)", name)
            self.assertNotRegex(html, r'(src|href)="https?:', name)

    def test_host_header_check(self):
        os.environ["PUBLIC_URL"] = "http://192.168.1.50:9001"
        self.addCleanup(os.environ.pop, "PUBLIC_URL", None)
        with tempfile.TemporaryDirectory() as tmp:
            client = create_app(tmp).test_client()
            self.assertEqual(client.get("/login", headers={"Host": "192.168.1.50:9001"}).status_code, 200)
            self.assertEqual(client.get("/login", headers={"Host": "evil.example"}).status_code, 400)
            self.assertEqual(client.get("/healthz", headers={"Host": "127.0.0.1:8000"}).status_code, 200)

    def test_oversized_request_is_rejected(self):
        client = self.client("a")
        response = client.post("/logout", data={"csrf_token": self.token(client), "x": "y" * 70000})
        self.assertEqual(response.status_code, 413)

    def test_notes_are_escaped(self):
        _, chips = self.add_chips()
        player = self.client("a")
        self.rate(player, chips[0]["id"], 10, notes="<script>alert(1)</script>")
        html = player.get(f"/schale/{chips[0]['id']}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)", html)

    def test_csv_export_neutralizes_formulas(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10, notes="=HYPERLINK(1)")
        body = admin.get("/admin/export.csv").get_data(as_text=True)
        self.assertIn("'=HYPERLINK", body)

    def test_exports_contain_no_hashes(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        for url in ("/admin/export.json", "/admin/export.csv"):
            self.assertNotIn("scrypt", admin.get(url).get_data(as_text=True))


class Blindness(Base):
    def test_nothing_leaks_before_reveal(self):
        _, chips = self.add_chips()
        player = self.client("a")
        self.rate(self.client("b"), chips[0]["id"], 17, notes="Bobs geheime Notiz")
        for url in ("/", "/api/progress", f"/schale/{chips[0]['id']}", "/api/ceremony", "/enthuellung", "/ergebnisse"):
            body = player.get(url).get_data(as_text=True)
            for secret in ("Geheimchip", "Funny", "Bobs geheime Notiz"):
                self.assertNotIn(secret, body, url)
        self.assertEqual(player.get("/api/results").status_code, 403)
        self.assertEqual(player.get("/urkunde/crown").status_code, 200)
        self.assertNotIn("Funny", player.get("/urkunde/crown").get_data(as_text=True))

    def test_ceremony_reveals_one_at_a_time_worst_first(self):
        admin, chips = self.add_chips()
        player = self.client("a")
        for chip, score in zip(chips, (20, 5, 12)):
            self.rate(player, chip["id"], score)
        self.post(admin, "/admin/ceremony/start")

        ceremony = player.get("/api/ceremony").get_json()
        self.assertEqual(ceremony["revealed"], [])
        self.assertEqual(player.get("/api/results").status_code, 403)

        headers = {"X-CSRF-Token": self.token(admin)}
        first = admin.post("/api/ceremony/next", headers=headers).get_json()
        self.assertEqual([c["label"] for c in first["revealed"]], ["Lorenz Zweitchip"])
        self.assertEqual(first["revealed"][0]["place"], 3)
        visible = json.dumps(player.get("/api/ceremony").get_json())
        self.assertNotIn("Geheimchip", visible)
        self.assertNotIn("Drittchip", visible)

        admin.post("/api/ceremony/next", headers=headers)
        last = admin.post("/api/ceremony/next", headers=headers).get_json()
        self.assertEqual(last["phase"], "revealed")
        self.assertEqual(last["revealed"][-1]["label"], "Funny Geheimchip")
        self.assertEqual(last["revealed"][-1]["place"], 1)
        self.assertEqual(player.get("/api/results").status_code, 200)

    def test_ratings_lock_during_ceremony(self):
        admin, chips = self.add_chips()
        player = self.client("a")
        self.rate(player, chips[0]["id"], 10)
        self.post(admin, "/admin/ceremony/start")
        self.rate(player, chips[0]["id"], 20)
        self.assertEqual(self.store.read()["ratings"][chips[0]["id"]]["a"]["enjoyment"], 10)

    def test_reopen_keeps_ratings(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        self.post(admin, "/admin/ceremony/start")
        self.post(admin, "/admin/ceremony/reopen")
        data = self.store.read()
        self.assertEqual(data["phase"], "tasting")
        self.assertEqual(data["ratings"][chips[0]["id"]]["a"]["enjoyment"], 10)


class Rating(Base):
    def test_incomplete_or_invalid_rating_is_rejected(self):
        _, chips = self.add_chips()
        player = self.client("a")
        chip = chips[0]["id"]
        self.assertEqual(self.post(player, f"/schale/{chip}", enjoyment="10").status_code, 422)
        self.assertEqual(self.rate(player, chip, 21).status_code, 422)
        self.assertEqual(self.rate(player, chip, 0).status_code, 422)
        self.assertEqual(self.rate(player, chip, 10, score=6).status_code, 422)
        self.assertEqual(self.store.read()["ratings"], {})

    def test_rating_can_be_updated_not_duplicated(self):
        _, chips = self.add_chips()
        player = self.client("a")
        chip = chips[0]["id"]
        self.assertEqual(self.rate(player, chip, 10).status_code, 302)
        self.assertEqual(self.rate(player, chip, 15).status_code, 302)
        ratings = self.store.read()["ratings"][chip]
        self.assertEqual(list(ratings), ["a"])
        self.assertEqual(ratings["a"]["enjoyment"], 15)

    def test_unknown_extras_are_dropped(self):
        _, chips = self.add_chips()
        player = self.client("a")
        self.rate(player, chips[0]["id"], 10, npc="Vecna", coins="999", guess_flavor="Blut", contract="maybe")
        rating = self.store.read()["ratings"][chips[0]["id"]]["a"]
        self.assertIsNone(rating["npc"])
        self.assertIsNone(rating["coins"])
        self.assertIsNone(rating["guess_flavor"])
        self.assertIsNone(rating["contract"])

    def test_admin_cannot_rate(self):
        admin, chips = self.add_chips()
        self.assertEqual(self.rate(admin, chips[0]["id"], 10).status_code, 403)

    def test_bad_price_is_rejected(self):
        admin = self.client("admin")
        for bad in ("abc", "nan", "inf", "-1"):
            self.post(admin, "/chips", name="x", flavor_type="BBQ", price=bad)
        self.assertEqual(self.store.read()["chips"], [])

    def test_rated_chips_cannot_be_shuffled(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        before = {c["id"]: c["bowl"] for c in self.store.read()["chips"]}
        self.post(admin, "/admin/shuffle")
        self.assertEqual({c["id"]: c["bowl"] for c in self.store.read()["chips"]}, before)


class PlayerChips(Base):
    def add(self, client, name="Meinchip"):
        self.assertEqual(self.post(client, "/chips", name=name, brand="Zauberknusper", flavor_type="BBQ").status_code, 302)
        return next(c for c in self.store.read()["chips"] if c["name"] == name)

    def test_any_player_can_add_and_rate_own_chip(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.assertEqual(chip["added_by"], "a")
        self.assertEqual(self.rate(alice, chip["id"], 15).status_code, 302)
        self.assertIn("a", self.store.read()["ratings"][chip["id"]])

    def test_only_the_adder_sees_what_is_inside(self):
        alice, bob = self.client("a"), self.client("b")
        chip = self.add(alice)
        self.assertIn("Meinchip", alice.get("/").get_data(as_text=True))
        self.assertIn("Meinchip", alice.get(f"/schale/{chip['id']}").get_data(as_text=True))
        for url in ("/", f"/?edit={chip['id']}", "/api/progress", f"/schale/{chip['id']}"):
            body = bob.get(url).get_data(as_text=True)
            self.assertNotIn("Meinchip", body, url)
            self.assertNotIn("Zauberknusper", body, url)
        self.assertNotIn('"added_by"', bob.get("/api/progress").get_data(as_text=True))

    def test_others_cannot_change_a_chip(self):
        alice, bob = self.client("a"), self.client("b")
        chip = self.add(alice)
        self.assertEqual(self.post(bob, f"/chips/{chip['id']}", name="Gehackt", flavor_type="BBQ").status_code, 403)
        self.assertEqual(self.post(bob, f"/chips/{chip['id']}/delete").status_code, 403)
        self.assertEqual(self.store.read()["chips"][0]["name"], "Meinchip")

    def test_adder_can_edit_but_keeps_ownership(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.post(alice, f"/chips/{chip['id']}", name="Neu", flavor_type="Käse", added_by="b")
        updated = self.store.read()["chips"][0]
        self.assertEqual((updated["name"], updated["added_by"]), ("Neu", "a"))

    def test_adder_cannot_delete_once_others_rated(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.rate(alice, chip["id"], 10)
        self.rate(self.client("b"), chip["id"], 10)
        self.post(alice, f"/chips/{chip['id']}/delete")
        self.assertEqual(len(self.store.read()["chips"]), 1)

    def test_adder_can_delete_with_only_own_rating(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.rate(alice, chip["id"], 10)
        self.post(alice, f"/chips/{chip['id']}/delete")
        data = self.store.read()
        self.assertEqual(data["chips"], [])
        self.assertEqual(data["ratings"], {})

    def test_players_cannot_add_after_lock(self):
        admin, _ = self.add_chips()
        self.rate(self.client("a"), self.store.read()["chips"][0]["id"], 10)
        self.post(admin, "/admin/ceremony/start")
        before = len(self.store.read()["chips"])
        self.post(self.client("b"), "/chips", name="Spät", flavor_type="BBQ")
        self.assertEqual(len(self.store.read()["chips"]), before)

    def test_own_chip_guesses_are_dropped_and_score_nothing(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.rate(alice, chip["id"], 10, guess_flavor="BBQ", guess_brand="Zauberknusper")
        rating = self.store.read()["ratings"][chip["id"]]["a"]
        self.assertIsNone(rating["guess_flavor"])
        self.assertEqual(rating["guess_brand"], "")


class Cleanup(Base):
    def setUp(self):
        super().setUp()
        self.admin, self.chips = self.add_chips()
        self.chip = self.chips[0]["id"]
        self.alice = self.client("a")
        self.rate(self.alice, self.chip, 10, notes="Peinliche Notiz")
        self.rate(self.client("b"), self.chip, 12)

    def test_data_page_lists_entries(self):
        body = self.admin.get("/admin/daten").get_data(as_text=True)
        self.assertIn("Peinliche Notiz", body)
        self.assertIn("Alice", body)

    def test_delete_note_keeps_rating(self):
        self.post(self.admin, f"/admin/daten/{self.chip}/a/note/delete")
        rating = self.store.read()["ratings"][self.chip]["a"]
        self.assertEqual(rating["notes"], "")
        self.assertEqual(rating["enjoyment"], 10)

    def test_delete_rating(self):
        self.post(self.admin, f"/admin/daten/{self.chip}/a/delete")
        self.assertEqual(list(self.store.read()["ratings"][self.chip]), ["b"])

    def test_delete_unknown_rating_is_404(self):
        self.assertEqual(self.post(self.admin, f"/admin/daten/{self.chip}/nobody/delete").status_code, 404)

    def test_admin_deletes_rated_chip_with_ratings(self):
        self.post(self.admin, f"/chips/{self.chip}/delete")
        data = self.store.read()
        self.assertNotIn(self.chip, data["ratings"])
        self.assertEqual(len(data["chips"]), 2)

    def test_players_cannot_cleanse(self):
        for url in (f"/admin/daten/{self.chip}/b/delete", f"/admin/daten/{self.chip}/b/note/delete"):
            self.assertEqual(self.post(self.alice, url).status_code, 403)
        self.assertIn("b", self.store.read()["ratings"][self.chip])

    def test_reset_needs_the_word_and_keeps_logins(self):
        self.post(self.admin, "/admin/reset", confirm="nein")
        self.assertEqual(len(self.store.read()["chips"]), 3)
        self.post(self.admin, "/admin/reset", confirm="asche")
        data = self.store.read()
        self.assertEqual((data["chips"], data["ratings"], data["phase"]), ([], {}, "tasting"))
        self.assertIn("a", self.store.users())

    def test_delete_makes_a_backup_first(self):
        backups = os.path.join(self.tmp.name, "backups")
        for name in os.listdir(backups):
            os.unlink(os.path.join(backups, name))
        self.post(self.admin, f"/admin/daten/{self.chip}/a/delete")
        contents = [open(os.path.join(backups, n), encoding="utf-8").read() for n in os.listdir(backups)]
        self.assertTrue(any("Peinliche Notiz" in text for text in contents))

    def test_no_deleting_during_ceremony(self):
        self.post(self.admin, "/admin/ceremony/start")
        self.post(self.admin, f"/admin/daten/{self.chip}/a/delete")
        self.post(self.admin, f"/chips/{self.chip}/delete")
        data = self.store.read()
        self.assertIn("a", data["ratings"][self.chip])
        self.assertEqual(len(data["chips"]), 3)

    def test_delete_after_reveal_updates_order(self):
        self.post(self.admin, "/admin/ceremony/start")
        headers = {"X-CSRF-Token": self.token(self.admin)}
        last = self.admin.post("/api/ceremony/next", headers=headers).get_json()
        self.assertEqual(last["phase"], "revealed")
        self.post(self.admin, f"/chips/{self.chip}/delete")
        data = self.store.read()
        self.assertEqual((data["ceremony_order"], data["reveal_count"]), ([], 0))
        self.assertEqual(self.alice.get("/api/results").status_code, 200)
        self.assertEqual(self.alice.get("/api/ceremony").status_code, 200)


class Persistence(Base):
    def test_data_survives_restart(self):
        _, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 13, notes="Ümläute öäü")
        reloaded = Store(self.tmp.name).read()
        self.assertEqual(reloaded["ratings"][chips[0]["id"]]["a"]["enjoyment"], 13)
        with open(os.path.join(self.tmp.name, "tasting.json"), encoding="utf-8") as f:
            self.assertIn("Ümläute", f.read())

    def test_login_survives_restart(self):
        client = self.client("a")
        cookie = client.get_cookie("avernus").value
        restarted = create_app(self.tmp.name).test_client()
        restarted.set_cookie("avernus", cookie)
        self.assertEqual(restarted.get("/").status_code, 200)

    def test_failed_edit_leaves_data_untouched(self):
        with self.assertRaises(RuntimeError):
            with self.store.edit() as data:
                data["phase"] = "broken"
                raise RuntimeError
        self.assertEqual(self.store.read()["phase"], "tasting")
        self.assertEqual(Store(self.tmp.name).read()["phase"], "tasting")

    def test_corrupt_file_refuses_to_start_and_stays(self):
        path = os.path.join(self.tmp.name, "tasting.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{kaputt")
        with self.assertRaises(ValueError):
            Store(self.tmp.name)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{kaputt")

    def test_private_files_are_private(self):
        mode = os.stat(os.path.join(self.tmp.name, "users.json")).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        mode = os.stat(os.path.join(self.tmp.name, "secret.key")).st_mode & 0o777
        self.assertEqual(mode, 0o600)


class Manage(unittest.TestCase):
    def test_init_only_stores_hashes_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["DATA_DIR"] = tmp
            os.environ["PLAYERS"] = "Der Lenny, Milka"
            self.addCleanup(os.environ.pop, "DATA_DIR", None)
            self.addCleanup(os.environ.pop, "PLAYERS", None)
            manage_main(["init"])
            users = Store(tmp).users()
            self.assertEqual(set(users), {"admin", "der-lenny", "milka"})
            hashes = {k: v["hash"] for k, v in users.items()}
            manage_main(["init"])
            self.assertEqual({k: v["hash"] for k, v in Store(tmp).users().items()}, hashes)
            manage_main(["reset", "Milka"])
            self.assertNotEqual(Store(tmp).users()["milka"]["hash"], hashes["milka"])
            self.assertEqual(Store(tmp).users()["der-lenny"]["hash"], hashes["der-lenny"])


class Stats(unittest.TestCase):
    def tasting(self):
        def rating(enjoyment, **extra):
            return {"scores": {k: 3 for k in SCALE_KEYS}, "enjoyment": enjoyment, **extra}

        chips = [
            {"id": "x", "bowl": 1, "name": "X", "brand": "Funny-Frisch", "flavor_type": "Paprika", "price": 2.0, "own_brand": False},
            {"id": "y", "bowl": 2, "name": "Y", "brand": "Lorenz", "flavor_type": "BBQ", "price": 1.0, "own_brand": True},
            {"id": "z", "bowl": 3, "name": "Z", "brand": "Pringles", "flavor_type": "Käse", "price": None, "own_brand": False},
        ]
        ratings = {
            "x": {"a": rating(20, guess_brand="funny frisch", guess_flavor="Paprika"), "b": rating(20), "c": rating(1)},
            "y": {"a": rating(10, guess_flavor="Paprika"), "b": rating(10), "c": rating(10)},
            "z": {"a": rating(1), "b": rating(1), "c": rating(20, notes="Lecker")},
        }
        return {"chips": chips, "ratings": ratings}

    users = {
        "admin": {"name": "Admin", "role": "admin", "hash": ""},
        "a": {"name": "A", "role": "player", "hash": ""},
        "b": {"name": "B", "role": "player", "hash": ""},
        "c": {"name": "C", "role": "player", "hash": ""},
    }

    def award(self, result, key):
        return next((a for a in result["awards"] if a["key"] == key), None)

    def test_ranking_and_spread(self):
        result = stats.compute(self.tasting(), self.users)
        self.assertEqual([c["id"] for c in result["chips"]], ["x", "y", "z"])
        self.assertAlmostEqual(result["chips"][1]["spread"], 0)
        self.assertEqual(self.award(result, "crown")["winner"], "Funny-Frisch X")
        self.assertEqual(self.award(result, "elturel")["winner"], "Pringles Z")

    def test_guess_scoring_skips_own_chip(self):
        tasting = self.tasting()
        board = stats.compute(tasting, self.users)["guessing"]["board"]
        self.assertEqual(board[0], {"name": "A", "points": 5, "flavor_hits": 1, "brand_hits": 1})
        self.assertEqual(self.award(stats.compute(tasting, self.users), "maggie")["winner"], "A")
        tasting["chips"][0]["added_by"] = "a"
        result = stats.compute(tasting, self.users)
        self.assertEqual(result["guessing"]["board"][0]["points"], 0)
        self.assertIsNone(self.award(result, "maggie"))

    def test_twins_and_heretic(self):
        result = stats.compute(self.tasting(), self.users)
        self.assertEqual({result["twins"]["closest"]["a"], result["twins"]["closest"]["b"]}, {"A", "B"})
        self.assertAlmostEqual(result["twins"]["closest"]["r"], 1.0)
        self.assertLess(result["twins"]["furthest"]["r"], -0.99)
        self.assertEqual(self.award(result, "thavius")["winner"], "C")

    def test_ties_name_all_winners(self):
        result = stats.compute(self.tasting(), self.users)
        self.assertEqual(self.award(result, "fate")["winner"], "A & B & C")

    def test_bargain_ignores_missing_price(self):
        result = stats.compute(self.tasting(), self.users)
        self.assertEqual(self.award(result, "bargain")["winner"], "Lorenz Y")

    def test_empty_tasting_does_not_crash(self):
        result = stats.compute({"chips": [], "ratings": {}}, self.users)
        self.assertEqual(result["awards"], [])
        self.assertEqual(result["summary"]["ratings"], 0)

    def test_single_rating_does_not_crash(self):
        tasting = self.tasting()
        tasting["ratings"] = {"x": {"a": tasting["ratings"]["x"]["a"]}}
        result = stats.compute(tasting, self.users)
        self.assertIsNone(result["twins"]["closest"])
        self.assertIsNone(self.award(result, "elturel"))

    def test_brand_matching(self):
        self.assertTrue(stats.brand_matches("funny", "Funny-Frisch"))
        self.assertTrue(stats.brand_matches("Lorentz", "Lorenz"))
        self.assertFalse(stats.brand_matches("xy", "Funny-Frisch"))
        self.assertFalse(stats.brand_matches("Pringles", "Lorenz"))
        self.assertFalse(stats.brand_matches("", "Lorenz"))


if __name__ == "__main__":
    unittest.main()
