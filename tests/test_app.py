"""End-to-end checks of the rules that matter: blindness, security, persistence, stats."""

import contextlib
import io
import json
import os
import re
import tempfile
import unittest

from PIL import Image

from tasting import archive, create_app, plans, security, stats
from tasting.catalog import SCALE_KEYS
from tasting.manage import main as manage_main
from tasting.store import Store

PASS = "test-pass-phrase-111"


def photo_bytes(fmt="PNG", size=(40, 30), exif=None):
    buffer = io.BytesIO()
    image = Image.new("RGB", size, (200, 120, 30))
    if exif:
        image.save(buffer, fmt, exif=exif)
    else:
        image.save(buffer, fmt)
    return buffer.getvalue()


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

    def upload(self, client, url, data=None, fmt="PNG", **fields):
        photo = (io.BytesIO(data if data is not None else photo_bytes(fmt)), "tuete.png")
        return client.post(url, data={"csrf_token": self.token(client), "image": photo, **fields},
                           content_type="multipart/form-data")

    def add_chips(self):
        admin = self.client("admin")
        self.post(admin, "/chips/chips", name="Geheimchip", brand="Funny", flavor_type="Paprika", price="1,99")
        self.post(admin, "/chips/chips", name="Zweitchip", brand="Lorenz", flavor_type="Gesalzen", own_brand="on")
        self.post(admin, "/chips/chips", name="Drittchip", brand="Pringles", flavor_type="BBQ", price="3")
        return admin, self.store.read()["chips"]

    def rate(self, client, chip_id, dc, score=3, **extra):
        fields = {f"score_{k}": str(score) for k in SCALE_KEYS}
        return self.post(client, f"/chips/schale/{chip_id}", dc=str(dc), **fields, **extra)


class Security(Base):
    def test_pages_need_login(self):
        client = self.client()
        for url in ("/chips/", "/chips/admin", "/chips/ergebnisse", "/chips/admin/export.json"):
            self.assertEqual(client.get(url).status_code, 302, url)
        for url in ("/chips/api/progress", "/chips/api/results", "/chips/api/ceremony"):
            self.assertEqual(client.get(url).status_code, 401, url)

    def test_players_cannot_reach_admin(self):
        player = self.client("a")
        for url in ("/chips/admin", "/chips/admin/daten", "/chips/admin/export.json", "/chips/admin/export.csv", "/chips/admin/qr.svg"):
            self.assertEqual(player.get(url).status_code, 403, url)
        self.assertEqual(self.post(player, "/chips/admin/shuffle").status_code, 403)
        self.assertEqual(self.post(player, "/chips/admin/reset", confirm="ASCHE").status_code, 403)
        self.assertEqual(self.post(player, "/chips/admin/ceremony/start").status_code, 403)
        self.assertEqual(self.post(player, "/chips/api/ceremony/next").status_code, 403)
        self.assertEqual(self.store.read()["chips"], [])

    def test_post_without_csrf_is_rejected(self):
        admin = self.client("admin")
        response = admin.post("/chips/chips", data={"name": "x", "flavor_type": "BBQ"})
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
        self.assertEqual(player.get("/chips/").status_code, 200)
        users = self.store.users()
        users["a"]["hash"] = security.hash_passphrase("new-pass-phrase-222")
        self.store.save_users(users)
        self.assertEqual(player.get("/chips/").status_code, 302)

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
        html = player.get(f"/chips/schale/{chips[0]['id']}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;alert(1)", html)

    def test_csv_export_neutralizes_formulas(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10, notes="=HYPERLINK(1)")
        body = admin.get("/chips/admin/export.csv").get_data(as_text=True)
        self.assertIn("'=HYPERLINK", body)

    def test_exports_contain_no_hashes(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        for url in ("/chips/admin/export.json", "/chips/admin/export.csv"):
            self.assertNotIn("scrypt", admin.get(url).get_data(as_text=True))


class Blindness(Base):
    def test_nothing_leaks_before_reveal(self):
        _, chips = self.add_chips()
        player = self.client("a")
        self.rate(self.client("b"), chips[0]["id"], 17, notes="Bobs geheime Notiz")
        for url in ("/chips/", "/chips/api/progress", f"/chips/schale/{chips[0]['id']}", "/chips/api/ceremony", "/chips/enthuellung", "/chips/ergebnisse"):
            body = player.get(url).get_data(as_text=True)
            for secret in ("Geheimchip", "Funny", "Bobs geheime Notiz"):
                self.assertNotIn(secret, body, url)
        self.assertEqual(player.get("/chips/api/results").status_code, 403)
        self.assertEqual(player.get("/chips/urkunde/crown").status_code, 200)
        self.assertNotIn("Funny", player.get("/chips/urkunde/crown").get_data(as_text=True))

    def test_ceremony_reveals_one_at_a_time_worst_first(self):
        admin, chips = self.add_chips()
        player = self.client("a")
        for chip, score in zip(chips, (20, 5, 12)):
            self.rate(player, chip["id"], score)
        self.post(admin, "/chips/admin/ceremony/start")

        ceremony = player.get("/chips/api/ceremony").get_json()
        self.assertEqual(ceremony["revealed"], [])
        self.assertEqual(player.get("/chips/api/results").status_code, 403)

        headers = {"X-CSRF-Token": self.token(admin)}
        first = admin.post("/chips/api/ceremony/next", headers=headers).get_json()
        self.assertEqual([c["label"] for c in first["revealed"]], ["Lorenz Zweitchip"])
        self.assertEqual(first["revealed"][0]["place"], 3)
        visible = json.dumps(player.get("/chips/api/ceremony").get_json())
        self.assertNotIn("Geheimchip", visible)
        self.assertNotIn("Drittchip", visible)

        admin.post("/chips/api/ceremony/next", headers=headers)
        last = admin.post("/chips/api/ceremony/next", headers=headers).get_json()
        self.assertEqual(last["phase"], "revealed")
        self.assertEqual(last["revealed"][-1]["label"], "Funny Geheimchip")
        self.assertEqual(last["revealed"][-1]["place"], 1)
        self.assertEqual(player.get("/chips/api/results").status_code, 200)

    def test_ratings_lock_during_ceremony(self):
        admin, chips = self.add_chips()
        player = self.client("a")
        self.rate(player, chips[0]["id"], 10)
        self.post(admin, "/chips/admin/ceremony/start")
        self.rate(player, chips[0]["id"], 20)
        self.assertEqual(self.store.read()["ratings"][chips[0]["id"]]["a"]["dc"], 10)

    def test_reopen_keeps_ratings(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        self.post(admin, "/chips/admin/ceremony/start")
        self.post(admin, "/chips/admin/ceremony/reopen")
        data = self.store.read()
        self.assertEqual(data["phase"], "tasting")
        self.assertEqual(data["ratings"][chips[0]["id"]]["a"]["dc"], 10)


class Rating(Base):
    def test_incomplete_or_invalid_rating_is_rejected(self):
        _, chips = self.add_chips()
        player = self.client("a")
        chip = chips[0]["id"]
        self.assertEqual(self.post(player, f"/chips/schale/{chip}", dc="10").status_code, 422)
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
        self.assertEqual(ratings["a"]["dc"], 15)

    def test_unknown_extras_are_dropped(self):
        _, chips = self.add_chips()
        player = self.client("a")
        self.rate(player, chips[0]["id"], 10, coins="999", guess_flavor="Blut", contract="maybe")
        rating = self.store.read()["ratings"][chips[0]["id"]]["a"]
        self.assertNotIn("npc", rating)
        self.assertIsNone(rating["coins"])
        self.assertIsNone(rating["guess_flavor"])
        self.assertIsNone(rating["contract"])

    def test_admin_cannot_rate(self):
        admin, chips = self.add_chips()
        self.assertEqual(self.rate(admin, chips[0]["id"], 10).status_code, 403)

    def test_bad_price_is_rejected(self):
        admin = self.client("admin")
        for bad in ("abc", "nan", "inf", "-1"):
            self.post(admin, "/chips/chips", name="x", flavor_type="BBQ", price=bad)
        self.assertEqual(self.store.read()["chips"], [])

    def test_bad_weight_is_rejected(self):
        admin = self.client("admin")
        for bad in ("abc", "nan", "0", "-5", "99999"):
            self.post(admin, "/chips/chips", name="x", flavor_type="BBQ", weight=bad)
        self.assertEqual(self.store.read()["chips"], [])
        self.post(admin, "/chips/chips", name="x", flavor_type="BBQ", price="2", weight="175,5")
        self.assertEqual(self.store.read()["chips"][0]["weight"], 175.5)

    def test_removed_categories_are_gone(self):
        self.assertNotIn("fingers", SCALE_KEYS)
        self.assertNotIn("wisdom", SCALE_KEYS)
        self.assertIn("grease", SCALE_KEYS)

    def test_rated_chips_cannot_be_shuffled(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        before = {c["id"]: c["bowl"] for c in self.store.read()["chips"]}
        self.post(admin, "/chips/admin/shuffle")
        self.assertEqual({c["id"]: c["bowl"] for c in self.store.read()["chips"]}, before)


class PlayerChips(Base):
    def add(self, client, name="Meinchip"):
        self.assertEqual(self.post(client, "/chips/chips", name=name, brand="Zauberknusper", flavor_type="BBQ").status_code, 302)
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
        self.assertIn("Meinchip", alice.get("/chips/").get_data(as_text=True))
        self.assertIn("Meinchip", alice.get(f"/chips/schale/{chip['id']}").get_data(as_text=True))
        for url in ("/chips/", f"/chips/?edit={chip['id']}", "/chips/api/progress", f"/chips/schale/{chip['id']}"):
            body = bob.get(url).get_data(as_text=True)
            self.assertNotIn("Meinchip", body, url)
            self.assertNotIn("Zauberknusper", body, url)
        self.assertNotIn('"added_by"', bob.get("/chips/api/progress").get_data(as_text=True))

    def test_others_cannot_change_a_chip(self):
        alice, bob = self.client("a"), self.client("b")
        chip = self.add(alice)
        self.assertEqual(self.post(bob, f"/chips/chips/{chip['id']}", name="Gehackt", flavor_type="BBQ").status_code, 403)
        self.assertEqual(self.post(bob, f"/chips/chips/{chip['id']}/delete").status_code, 403)
        self.assertEqual(self.store.read()["chips"][0]["name"], "Meinchip")

    def test_adder_can_edit_but_keeps_ownership(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.post(alice, f"/chips/chips/{chip['id']}", name="Neu", flavor_type="Käse", added_by="b")
        updated = self.store.read()["chips"][0]
        self.assertEqual((updated["name"], updated["added_by"]), ("Neu", "a"))

    def test_adder_cannot_delete_once_others_rated(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.rate(alice, chip["id"], 10)
        self.rate(self.client("b"), chip["id"], 10)
        self.post(alice, f"/chips/chips/{chip['id']}/delete")
        self.assertEqual(len(self.store.read()["chips"]), 1)

    def test_adder_can_delete_with_only_own_rating(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.rate(alice, chip["id"], 10)
        self.post(alice, f"/chips/chips/{chip['id']}/delete")
        data = self.store.read()
        self.assertEqual(data["chips"], [])
        self.assertEqual(data["ratings"], {})

    def test_players_cannot_add_after_lock(self):
        admin, _ = self.add_chips()
        self.rate(self.client("a"), self.store.read()["chips"][0]["id"], 10)
        self.post(admin, "/chips/admin/ceremony/start")
        before = len(self.store.read()["chips"])
        self.post(self.client("b"), "/chips/chips", name="Spät", flavor_type="BBQ")
        self.assertEqual(len(self.store.read()["chips"]), before)

    def test_own_chip_guesses_are_dropped_and_score_nothing(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.rate(alice, chip["id"], 10, guess_flavor="BBQ", guess_brand="Zauberknusper")
        rating = self.store.read()["ratings"][chip["id"]]["a"]
        self.assertIsNone(rating["guess_flavor"])
        self.assertEqual(rating["guess_brand"], "")

    def test_own_chip_price_guess_is_dropped(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.rate(alice, chip["id"], 10, coins="7")
        self.assertIsNone(self.store.read()["ratings"][chip["id"]]["a"]["coins"])

    def test_weight_stays_private_before_reveal(self):
        alice, bob = self.client("a"), self.client("b")
        self.post(alice, "/chips/chips", name="Schwer", flavor_type="BBQ", price="2,50", weight="4242")
        chip = self.store.read()["chips"][0]
        for url in ("/chips/", "/chips/api/progress", f"/chips/schale/{chip['id']}"):
            self.assertNotIn("4242", bob.get(url).get_data(as_text=True), url)


class Shopping(Base):
    def add(self, client, name="Ungarisch", brand="Funny-Frisch", **extra):
        fields = {"name": name, "brand": brand, "flavor_type": "Paprika", "buyer": "me", **extra}
        return self.post(client, "/chips/einkauf", **fields)

    def items(self):
        return self.store.read()["shopping"]

    def test_everyone_sees_the_list(self):
        self.add(self.client("a"))
        for uid in ("b", "admin"):
            body = self.client(uid).get("/chips/einkauf").get_data(as_text=True)
            self.assertIn("Ungarisch", body)
            self.assertIn("kauft Alice", body)

    def test_exact_duplicate_is_refused(self):
        self.add(self.client("a"))
        self.add(self.client("b"), name=" ungarisch ", brand="funny frisch")
        self.assertEqual(len(self.items()), 1)

    def test_similar_item_is_added_with_a_warning(self):
        self.add(self.client("a"))
        bob = self.client("b")
        self.add(bob, name="Ungarische Art", brand="Funny")
        self.assertEqual(len(self.items()), 2)
        self.assertIn("klingt wie", bob.get("/chips/einkauf").get_data(as_text=True))

    def test_wish_can_be_claimed_once(self):
        self.add(self.client("a"), buyer="open")
        self.post(self.client("b"), f"/chips/einkauf/{self.items()[0]['id']}/claim")
        self.post(self.client("c"), f"/chips/einkauf/{self.items()[0]['id']}/claim")
        self.assertEqual(self.items()[0]["buyer"], "b")

    def test_only_the_buyer_marks_bought_or_releases(self):
        self.add(self.client("a"))
        item = self.items()[0]["id"]
        bob = self.client("b")
        self.assertEqual(self.post(bob, f"/chips/einkauf/{item}/bought").status_code, 403)
        self.assertEqual(self.post(bob, f"/chips/einkauf/{item}/release").status_code, 403)
        self.post(self.client("a"), f"/chips/einkauf/{item}/bought")
        self.assertTrue(self.items()[0]["bought"])

    def test_wisher_cannot_strike_what_someone_else_buys(self):
        alice = self.client("a")
        self.add(alice, buyer="open")
        item = self.items()[0]["id"]
        self.post(self.client("b"), f"/chips/einkauf/{item}/claim")
        self.post(alice, f"/chips/einkauf/{item}/delete")
        self.assertEqual(len(self.items()), 1)
        self.assertEqual(self.post(self.client("c"), f"/chips/einkauf/{item}/delete").status_code, 403)
        self.post(self.client("admin"), f"/chips/einkauf/{item}/delete")
        self.assertEqual(self.items(), [])

    def test_anyone_sets_up_any_item_and_the_buyer_stays_blind(self):
        alice, bob = self.client("a"), self.client("b")
        self.add(alice)
        item = self.items()[0]["id"]
        form = bob.get(f"/chips/?from={item}").get_data(as_text=True)
        self.assertIn('value="Ungarisch"', form)
        self.post(bob, "/chips/chips", name="Ungarisch", brand="Funny-Frisch", flavor_type="Paprika",
                  price="2,49", weight="175", item_id=item)
        chip = self.store.read()["chips"][0]
        self.assertEqual((chip["added_by"], chip["bought_by"], chip["item_id"]), ("b", "a", item))
        # Alice bought the bag but must not learn which bowl it became.
        self.assertNotIn("Schale 1", alice.get("/chips/einkauf").get_data(as_text=True))
        self.assertNotIn("Deine Chips", alice.get("/chips/").get_data(as_text=True))
        self.assertIn("Deine Chips", bob.get("/chips/").get_data(as_text=True))
        self.assertFalse(alice.get("/chips/api/progress").get_json()["bowls"][0]["brought"])
        self.assertTrue(bob.get("/chips/api/progress").get_json()["bowls"][0]["brought"])
        self.assertNotIn("Deine eigenen Chips", alice.get(f"/chips/schale/{chip['id']}").get_data(as_text=True))
        self.assertIn("Deine eigenen Chips", bob.get(f"/chips/schale/{chip['id']}").get_data(as_text=True))
        self.assertIn("Schale 1", self.client("admin").get("/chips/einkauf").get_data(as_text=True))

    def test_one_bag_can_fill_several_bowls(self):
        self.add(self.client("a"))
        item = self.items()[0]["id"]
        self.post(self.client("b"), f"/chips/einkauf/{item}/setup")
        self.post(self.client("c"), f"/chips/einkauf/{item}/setup")
        chips = self.store.read()["chips"]
        self.assertEqual([(c["bowl"], c["added_by"], c["item_id"]) for c in chips], [(1, "b", item), (2, "c", item)])

    def test_buyer_may_guess_on_their_bag_but_the_setter_may_not(self):
        self.add(self.client("a"))
        self.post(self.client("b"), f"/chips/einkauf/{self.items()[0]['id']}/setup")
        data = self.store.read()
        chip = data["chips"][0]
        guess = {"guess_flavor": "Paprika", "guess_brand": "Funny-Frisch", "scores": {}, "dc": 10}
        self.assertEqual(stats.guess_points(guess, chip, "a"), 5)
        self.assertEqual(stats.guess_points(guess, chip, "b"), 0)

    def test_list_locks_with_the_ratings(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        self.post(admin, "/chips/admin/ceremony/start")
        self.add(self.client("b"))
        self.assertEqual(self.items(), [])

    def test_items_from_the_first_list_version_still_show(self):
        path = os.path.join(self.tmp.name, "tasting.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"phase": "tasting", "chips": [], "ratings": {}, "shopping": [{
                "id": "i1", "name": "Ungarisch", "brand": "Funny-Frisch", "flavor_type": "Paprika",
                "own_brand": False, "creator": "a", "buyer": "a", "bought": False, "chip_id": None,
            }]}, f)
        self.app = create_app(self.tmp.name)
        self.store = self.app.extensions["store"]
        alice = self.client("a")
        self.assertEqual(alice.get("/chips/einkauf").status_code, 200)
        self.assertEqual(alice.get("/chips/einkauf?edit=i1").status_code, 200)
        self.assertEqual(alice.get("/chips/?from=i1").status_code, 200)

    def test_old_files_get_a_list(self):
        path = os.path.join(self.tmp.name, "tasting.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"phase": "tasting", "chips": [], "ratings": {}}, f)
        self.assertEqual(Store(self.tmp.name).read()["shopping"], [])


class ListDetails(Base):
    def test_name_is_optional_when_brand_and_flavor_say_enough(self):
        alice = self.client("a")
        self.post(alice, "/chips/chips", brand="Pringles", flavor_type="Paprika")
        chip = self.store.read()["chips"][0]
        self.assertEqual(stats.chip_label(chip), "Pringles Paprika")
        self.post(alice, "/chips/chips", flavor_type="BBQ")
        self.assertEqual(len(self.store.read()["chips"]), 1)

    def test_complete_item_becomes_a_bowl_in_one_step(self):
        alice = self.client("a")
        self.post(alice, "/chips/einkauf", brand="Pringles", flavor_type="Paprika", price="2,99", weight="165", buyer="me")
        item = self.store.read()["shopping"][0]
        self.post(alice, f"/chips/einkauf/{item['id']}/setup")
        chip = self.store.read()["chips"][0]
        self.assertEqual((chip["brand"], chip["flavor_type"], chip["price"], chip["weight"]), ("Pringles", "Paprika", 2.99, 165))
        self.assertEqual(chip["item_id"], item["id"])

    def test_nutrition_travels_from_the_list_into_the_bowl(self):
        alice = self.client("a")
        self.post(alice, "/chips/einkauf", brand="Pringles", flavor_type="Paprika", buyer="me")
        with self.store.edit() as data:
            data["shopping"][0].update(nutrition={"kcal": 528, "salt": 1.0}, ingredients="Kartoffeln, Öl, Salz")
        self.assertIn("528", alice.get("/chips/einkauf").get_data(as_text=True))
        self.post(self.client("b"), f"/chips/einkauf/{self.store.read()['shopping'][0]['id']}/setup")
        chip = self.store.read()["chips"][0]
        self.assertEqual((chip["nutrition"]["kcal"], chip["ingredients"]), (528, "Kartoffeln, Öl, Salz"))

    def test_incomplete_item_opens_the_filled_form(self):
        alice = self.client("a")
        self.post(alice, "/chips/einkauf", name="Irgendwas mit Trüffel", buyer="me")
        item = self.store.read()["shopping"][0]
        response = self.post(alice, f"/chips/einkauf/{item['id']}/setup")
        self.assertIn(f"from={item['id']}", response.headers["Location"])
        self.assertEqual(self.store.read()["chips"], [])

    def test_price_on_the_list_stays_with_the_buyer(self):
        alice = self.client("a")
        self.post(alice, "/chips/einkauf", brand="Pringles", flavor_type="Paprika", price="4,27", buyer="me")
        self.assertIn("4,27", alice.get("/chips/einkauf").get_data(as_text=True))
        self.assertNotIn("4,27", self.client("b").get("/chips/einkauf").get_data(as_text=True))

    def test_different_flavors_of_one_brand_are_no_duplicates(self):
        self.post(self.client("a"), "/chips/einkauf", brand="Pringles", flavor_type="Paprika")
        self.post(self.client("b"), "/chips/einkauf", brand="Pringles", flavor_type="Sour Cream & Zwiebel")
        self.post(self.client("c"), "/chips/einkauf", brand="pringles", flavor_type="Paprika")
        self.assertEqual(len(self.store.read()["shopping"]), 2)

    def test_item_stays_editable_after_it_became_a_bowl(self):
        alice = self.client("a")
        self.post(alice, "/chips/einkauf", brand="Pringles", buyer="me")
        item = self.store.read()["shopping"][0]["id"]
        self.post(alice, f"/chips/einkauf/{item}", brand="Pringles", flavor_type="Paprika", weight="165")
        self.assertEqual(self.store.read()["shopping"][0]["flavor_type"], "Paprika")
        self.assertEqual(self.post(self.client("b"), f"/chips/einkauf/{item}", brand="Gehackt").status_code, 403)
        self.post(alice, f"/chips/einkauf/{item}/setup")
        self.post(alice, f"/chips/einkauf/{item}", brand="Pringles", flavor_type="Käse")
        data = self.store.read()
        self.assertEqual((data["shopping"][0]["flavor_type"], data["chips"][0]["flavor_type"]), ("Käse", "Paprika"))


class Import(Base):
    def send(self, client, payload, confirm="on"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return client.post("/chips/admin/import", data={"csrf_token": self.token(client), "confirm": confirm,
                                                  "file": (io.BytesIO(body), "export.json")},
                           content_type="multipart/form-data")

    def exported(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 12)
        return admin, json.loads(admin.get("/chips/admin/export.json").get_data(as_text=True))

    def test_export_can_be_edited_and_imported_again(self):
        admin, data = self.exported()
        data["chips"][0]["name"] = "Umbenannt"
        self.post(admin, "/chips/admin/reset", confirm="ASCHE")
        self.assertEqual(self.send(admin, data).status_code, 302)
        now = self.store.read()
        self.assertEqual(now["chips"][0]["name"], "Umbenannt")
        self.assertEqual(now["ratings"][data["chips"][0]["id"]]["a"]["dc"], 12)
        self.assertIn("a", self.store.users())

    def test_import_needs_confirmation_and_valid_data(self):
        admin, data = self.exported()
        before = self.store.read()
        for payload, confirm in ((data, ""), (b"{kaputt", "on"), ({"phase": "wild"}, "on"),
                                 ({**data, "chips": [{"id": 5}]}, "on"),
                                 ({**data, "ratings": {"x": {"a": {"scores": {}}}}}, "on")):
            self.send(admin, payload, confirm)
        self.assertEqual(self.store.read(), before)

    def test_only_the_admin_imports(self):
        _, data = self.exported()
        self.assertEqual(self.send(self.client("a"), data).status_code, 403)

    def test_old_exports_are_upgraded(self):
        admin = self.client("admin")
        old = {"version": 1, "phase": "tasting", "ceremony_order": [], "reveal_count": 0,
               "chips": [{"id": "c1", "bowl": 1, "name": "X", "brand": "", "flavor_type": "BBQ", "added_by": "a"}],
               "ratings": {}, "shopping": [{"id": "i1", "name": "X", "brand": "", "flavor_type": "BBQ",
                                            "creator": "a", "buyer": "a", "bought": True, "chip_id": "c1"}]}
        self.send(admin, old)
        data = self.store.read()
        self.assertEqual((data["chips"][0]["item_id"], data["chips"][0]["bought_by"]), ("i1", "a"))
        self.assertNotIn("chip_id", data["shopping"][0])
        self.assertEqual(self.client("a").get("/chips/einkauf").status_code, 200)


class Photos(Base):
    def images(self):
        return sorted(os.listdir(os.path.join(self.tmp.name, "images")))

    def test_photo_is_reencoded_without_exif(self):
        alice = self.client("a")
        exif = Image.Exif()
        exif[0x010F] = "Spionagekamera"  # Make
        response = self.upload(alice, "/chips/chips", data=photo_bytes("JPEG", exif=exif), flavor_type="BBQ", brand="Chio")
        self.assertEqual(response.status_code, 302)
        chip = self.store.read()["chips"][0]
        self.assertEqual(self.images(), [chip["image"]])
        served = alice.get(f"/chips/bild/{chip['image']}")
        self.assertEqual(served.mimetype, "image/jpeg")
        self.assertNotIn(b"Spionagekamera", served.data)
        self.assertFalse(Image.open(io.BytesIO(served.data)).getexif())

    def test_non_images_are_refused(self):
        alice = self.client("a")
        for data in (b"<svg onload=alert(1)>", b"GIF89a" + b"x" * 50, b""):
            self.upload(alice, "/chips/chips", data=data, flavor_type="BBQ", brand="Chio")
        gif = io.BytesIO()
        Image.new("RGB", (5, 5)).save(gif, "GIF")
        self.upload(alice, "/chips/chips", data=gif.getvalue(), flavor_type="BBQ", brand="Chio")
        self.assertEqual(self.store.read()["chips"], [])
        self.assertEqual(self.images(), [])
        # A form sent without choosing a file is fine and just has no photo.
        alice.post("/chips/chips", data={"csrf_token": self.token(alice), "flavor_type": "BBQ", "brand": "Chio",
                                   "image": (io.BytesIO(b""), "")}, content_type="multipart/form-data")
        self.assertEqual([c.get("image") for c in self.store.read()["chips"]], [None])

    def test_oversized_upload_is_rejected_but_photos_pass_the_small_limit(self):
        alice = self.client("a")
        big = photo_bytes("PNG", size=(400, 300))
        self.assertGreater(len(big) + 70000, 64 * 1024)
        response = self.upload(alice, "/chips/chips", data=big + b"\0" * 70000, flavor_type="BBQ", brand="Chio")
        self.assertEqual(response.status_code, 302)
        too_big = b"\0" * (13 * 1024 * 1024)
        self.assertEqual(self.upload(alice, "/chips/chips", data=too_big, flavor_type="BBQ").status_code, 413)

    def test_bowl_photo_is_blind_until_the_reveal(self):
        admin = self.client("admin")
        alice, bob = self.client("a"), self.client("b")
        self.upload(alice, "/chips/chips", flavor_type="BBQ", brand="Chio")
        name = self.store.read()["chips"][0]["image"]
        self.assertEqual(bob.get(f"/chips/bild/{name}").status_code, 404)
        self.assertEqual(admin.get(f"/chips/bild/{name}").status_code, 200)
        self.rate(bob, self.store.read()["chips"][0]["id"], 10)
        self.post(admin, "/chips/admin/ceremony/start")
        self.assertEqual(bob.get(f"/chips/bild/{name}").status_code, 404)
        admin.post("/chips/api/ceremony/next", headers={"X-CSRF-Token": self.token(admin)})
        self.assertEqual(bob.get(f"/chips/bild/{name}").status_code, 200)

    def test_list_photo_is_public_and_moves_to_the_bowl(self):
        alice = self.client("a")
        self.upload(alice, "/chips/einkauf", brand="Pringles", flavor_type="Paprika", buyer="me")
        item = self.store.read()["shopping"][0]
        self.assertEqual(self.client("b").get(f"/chips/bild/{item['image']}").status_code, 200)
        self.post(self.client("c"), f"/chips/einkauf/{item['id']}/setup")
        self.assertEqual(self.store.read()["chips"][0]["image"], item["image"])
        # Striking the item keeps the photo, the bowl still uses it.
        self.post(alice, f"/chips/einkauf/{item['id']}/delete")
        self.assertEqual(self.images(), [item["image"]])
        self.assertEqual(self.client("b").get(f"/chips/bild/{item['image']}").status_code, 404)

    def test_replaced_and_deleted_photos_are_removed(self):
        alice = self.client("a")
        self.upload(alice, "/chips/chips", flavor_type="BBQ", brand="Chio")
        chip = self.store.read()["chips"][0]
        self.upload(alice, f"/chips/chips/{chip['id']}", flavor_type="BBQ", brand="Chio")
        new = self.store.read()["chips"][0]["image"]
        self.assertEqual(self.images(), [new])
        self.post(alice, f"/chips/chips/{chip['id']}", flavor_type="BBQ", brand="Chio", remove_image="on")
        self.assertEqual(self.images(), [])

    def test_camera_and_file_buttons_both_work(self):
        alice = self.client("a")
        for files in ([(io.BytesIO(b""), ""), (io.BytesIO(photo_bytes()), "kamera.jpg")],
                      [(io.BytesIO(photo_bytes()), "datei.png"), (io.BytesIO(b""), "")]):
            alice.post("/chips/chips", data={"csrf_token": self.token(alice), "flavor_type": "BBQ", "brand": "Chio",
                                       "image": files}, content_type="multipart/form-data")
        self.assertTrue(all(c["image"] for c in self.store.read()["chips"]))
        self.assertEqual(len(self.images()), 2)

    def test_bad_names_are_not_served(self):
        alice = self.client("a")
        for name in ("../users.json", "secret.key", "abc.jpg"):
            self.assertEqual(alice.get(f"/chips/bild/{name}").status_code, 404)

    def test_failed_upload_leaves_no_file(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        self.post(admin, "/chips/admin/ceremony/start")
        self.upload(self.client("b"), "/chips/chips", flavor_type="BBQ", brand="Chio")
        self.assertEqual(self.images(), [])


def small_archive(**changes):
    """Three colas, two people, one question block. Enough for every statistic."""
    scores = {("A", "1"): 5, ("A", "2"): 3, ("A", "3"): 1, ("B", "1"): 4, ("B", "2"): 2, ("B", "3"): 2}
    base = {
        "format": archive.FORMAT, "id": "cola", "number": 1, "title": "Cola-Verkostung",
        "scale": {"min": 1, "max": 5}, "ranking": "genuss", "tiebreak": "suesse",
        "sections": [{"title": "Gaumen", "criteria": [
            {"key": "suesse", "label": "Süße", "low": "herb", "high": "klebrig"},
            {"key": "genuss", "label": "Genuss", "low": "nein", "high": "ja"}]}],
        "items": [{"id": "1", "name": "Cherry", "group": "Zucker"}, {"id": "2", "name": "Zero", "group": "Zero"},
                  {"id": "3", "name": "Fanta", "group": "Zucker"}],
        "flags": [{"key": "served", "label": "Selbst eingeschenkt"}],
        "awards": [{"title": "Süßeste Bombe", "terms": [{"key": "suesse"}], "best": "max"}],
        "ratings": [{"person": person, "item": item, "scores": {"genuss": value, "suesse": 6 - value},
                     "flags": {"served": person == "A" and item == "1"}, **({"notes": "Lecker"} if value == 5 else {})}
                    for (person, item), value in scores.items()],
    }
    return {**base, **changes}


class Tastings(Base):
    def upload(self, client, entry, slug="cola"):
        body = json.dumps(entry).encode() if isinstance(entry, dict) else entry
        return client.post(f"/{slug}/einspielen", data={"csrf_token": self.token(client), "file": (io.BytesIO(body), "a.json")},
                           content_type="multipart/form-data")

    def test_landing_has_a_tile_for_every_tasting(self):
        body = self.client("a").get("/").get_data(as_text=True)
        for title, href in (("Blutkrieg der Chips", 'href="/chips/"'), ("Cola-Verkostung", 'href="/cola/"'),
                            ("Wasser-Verkostung", 'href="/wasser/"')):
            self.assertIn(title, body)
            self.assertIn(href, body)
        self.assertIn("Noch keine Daten", body)

    def test_landing_keeps_the_live_tasting_blind(self):
        self.add_chips()
        body = self.client("a").get("/").get_data(as_text=True)
        self.assertIn("3 Schalen", body)
        for secret in ("Geheimchip", "Funny"):
            self.assertNotIn(secret, body)

    def test_login_lands_on_the_tiles(self):
        response = self.post(self.client(), "/login", user="a", passphrase=PASS)
        self.assertEqual(response.headers["Location"], "/")

    def test_upload_writes_its_own_file_and_everyone_reads(self):
        admin = self.client("admin")
        self.assertEqual(self.upload(admin, small_archive(id="egal")).status_code, 302)
        with open(os.path.join(self.tmp.name, "cola.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["id"], "cola")
        player = self.client("a")
        self.assertIn("♛ Cherry", player.get("/").get_data(as_text=True))
        page = player.get("/cola/").get_data(as_text=True)
        self.assertIn("theme-cola.css", page)
        self.assertNotIn("Daten verwalten", page)
        result = player.get("/cola/api/ergebnisse").get_json()
        self.assertEqual([r["name"] for r in result["ranking"]], ["Cherry", "Zero", "Fanta"])
        self.assertIn("Daten verwalten", admin.get("/cola/").get_data(as_text=True))
        self.assertIn('"title": "Cola-Verkostung"', admin.get("/cola/export.json").get_data(as_text=True))

    def test_replacing_keeps_a_backup(self):
        admin = self.client("admin")
        self.upload(admin, small_archive())
        self.upload(admin, small_archive(title="Neu"))
        backups = os.listdir(os.path.join(self.tmp.name, "backups"))
        self.assertTrue(any(name.startswith("cola-") for name in backups))
        self.assertEqual(self.store.document("cola").read()["title"], "Neu")

    def test_bad_uploads_are_refused(self):
        admin = self.client("admin")
        for entry in (b"{kaputt", {"format": "x"}, small_archive(ranking="nichts"),
                      small_archive(ratings=[{"person": "A", "item": "9", "scores": {"genuss": 3}}]),
                      small_archive(ratings=[{"person": "A", "item": "1", "scores": {"genuss": 9}}])):
            self.upload(admin, entry)
        self.assertFalse(self.store.document("cola").exists())

    def test_only_the_admin_uploads_or_downloads(self):
        player = self.client("a")
        self.assertEqual(self.upload(player, small_archive()).status_code, 403)
        self.upload(self.client("admin"), small_archive())
        self.assertEqual(player.get("/cola/export.json").status_code, 403)

    def test_empty_tasting_page_and_unknown_slugs(self):
        player = self.client("a")
        self.assertIn("noch keine Ergebnisse", player.get("/wasser/").get_data(as_text=True))
        self.assertEqual(player.get("/wasser/api/ergebnisse").status_code, 404)
        for slug in ("nope", "chips-x", "..", "Cola"):
            self.assertEqual(player.get(f"/{slug}/").status_code, 404, slug)
        self.assertEqual(self.upload(self.client("admin"), small_archive(), slug="nope").status_code, 404)

    def test_old_addresses_lead_to_the_new_ones(self):
        player = self.client("a")
        for old, new in (("/einkauf", "/chips/einkauf"), ("/ergebnisse", "/chips/ergebnisse"), ("/schale/abc", "/chips/schale/abc"),
                         ("/verkostungen", "/"), ("/archiv/cola", "/cola/"), ("/water", "/wasser/")):
            response = player.get(old, follow_redirects=False)
            while response.status_code in (301, 308) and not response.headers["Location"].endswith(new):
                response = player.get(response.headers["Location"], follow_redirects=False)
            self.assertTrue(response.headers.get("Location", "").endswith(new), old)
        self.assertEqual(player.get("/schale/..%2fx").status_code, 404)

    def test_files_from_the_old_archive_folder_are_taken_over(self):
        os.makedirs(os.path.join(self.tmp.name, "archive"))
        with open(os.path.join(self.tmp.name, "archive", "wasser.json"), "w", encoding="utf-8") as f:
            json.dump(small_archive(id="wasser"), f)
        app = create_app(self.tmp.name)
        self.assertTrue(app.extensions["store"].document("wasser").exists())
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "wasser.json")))

    def start_photo(self, client, caption="Die Tafel"):
        return client.post("/start/fotos", data={"csrf_token": self.token(client), "caption": caption,
                                                 "image": (io.BytesIO(photo_bytes()), "foto.png")},
                           content_type="multipart/form-data")

    def test_admin_photos_become_gallery_and_background(self):
        admin, player = self.client("admin"), self.client("a")
        self.start_photo(admin, "Erste")
        self.start_photo(admin, "Zweite")
        start = self.store.document("start").read()
        first, second = (p["name"] for p in start["photos"])
        self.assertEqual(start["background"], first)
        page = player.get("/").get_data(as_text=True)
        self.assertIn("Aus dem Gildenbuch", page)
        self.assertIn(f'class="m-backdrop" src="/fotos/{first}"', page)
        self.assertNotIn("Gildenhalle schmücken", page)
        self.assertEqual(player.get(f"/fotos/{second}").mimetype, "image/jpeg")
        self.post(admin, f"/start/fotos/{second}/hintergrund")
        self.assertEqual(self.store.document("start").read()["background"], second)
        self.post(admin, f"/start/fotos/{second}/loeschen")
        start = self.store.document("start").read()
        self.assertEqual((len(start["photos"]), start["background"]), (1, first))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "images", second)))
        self.assertEqual(player.get(f"/fotos/{second}").status_code, 404)

    def test_only_the_admin_decorates_and_strangers_see_nothing(self):
        player = self.client("a")
        self.assertEqual(self.start_photo(player).status_code, 403)
        self.start_photo(self.client("admin"))
        name = self.store.document("start").read()["photos"][0]["name"]
        self.assertEqual(self.post(player, f"/start/fotos/{name}/loeschen").status_code, 403)
        self.assertEqual(self.client().get(f"/fotos/{name}").status_code, 302)
        self.assertNotIn(name, self.client().get("/login").get_data(as_text=True))

    def test_photos_of_bowls_are_not_served_as_start_photos(self):
        alice = self.client("a")
        alice.post("/chips/chips", data={"csrf_token": self.token(alice), "brand": "Chio", "flavor_type": "BBQ",
                                         "image": (io.BytesIO(photo_bytes()), "t.png")}, content_type="multipart/form-data")
        name = self.store.read()["chips"][0]["image"]
        self.assertEqual(self.client("b").get(f"/fotos/{name}").status_code, 404)

    def test_admin_sets_dates_for_the_tiles(self):
        admin, player = self.client("admin"), self.client("a")
        self.upload(admin, small_archive(date="2026-03-01"))
        self.assertIn("1. März 2026", player.get("/").get_data(as_text=True))
        self.post(admin, "/start/daten", date_chips="2026-11-21", date_cola="2026-02-14", date_wasser="")
        page = player.get("/").get_data(as_text=True)
        self.assertIn('<time datetime="2026-11-21">21. November 2026</time>', page)
        self.assertIn("14. Februar 2026", page)
        self.assertNotIn("1. März 2026", page)
        self.assertIn("Abgeschlossen am 14. Februar 2026", player.get("/cola/").get_data(as_text=True))
        self.assertEqual(self.store.document("start").read()["dates"], {"chips": "2026-11-21", "cola": "2026-02-14"})

    def test_bad_dates_and_players_change_nothing(self):
        admin = self.client("admin")
        self.post(admin, "/start/daten", date_chips="2026-11-21")
        self.post(admin, "/start/daten", date_chips="morgen", date_cola="2026-02-14")
        self.assertEqual(self.store.document("start").read()["dates"], {"chips": "2026-11-21"})
        self.assertEqual(self.post(self.client("a"), "/start/daten", date_chips="2000-01-01").status_code, 403)

    def table(self, client, size=(400, 200)):
        return client.post("/start/tafel", data={"csrf_token": self.token(client),
                                                 "image": (io.BytesIO(photo_bytes(size=size)), "tafel.png")},
                           content_type="multipart/form-data")

    def test_table_picture_with_clickable_dishes(self):
        admin, player = self.client("admin"), self.client("a")
        self.assertNotIn("m-table-spots", player.get("/").get_data(as_text=True))
        self.table(admin)
        table = self.store.document("start").read()["table"]
        self.assertEqual((table["aspect"], table["spots"]), (0.5, {}))
        self.post(admin, "/start/tafel/punkte", spot_chips_x="25", spot_chips_y="60", spot_chips_r="8",
                  spot_cola_x="", spot_cola_y="", spot_cola_r="8", spot_wasser_x="70.5", spot_wasser_y="40", spot_wasser_r="6")
        self.assertEqual(self.store.document("start").read()["table"]["spots"],
                         {"chips": {"x": 25, "y": 60, "r": 8}, "wasser": {"x": 70.5, "y": 40, "r": 6}})
        page = player.get("/").get_data(as_text=True)
        self.assertIn('viewBox="0 0 100 50.0"', page)
        self.assertIn('<a href="/chips/" class="m-spot">', page)
        self.assertIn('cx="25.0" cy="30.0" r="8.0"', page)
        # The dish itself is the button: no label drawn over the picture, only the link title.
        spots = page[page.index('class="m-table-spots"'):page.index("</svg>")]
        self.assertNotIn("<text", spots)
        self.assertIn("<title>Blutkrieg der Chips</title>", spots)
        self.assertNotIn('<a href="/cola/" class="m-spot">', page)
        self.assertNotIn("spot-editor", page)
        self.assertEqual(player.get(f"/fotos/{table['image']}").status_code, 200)
        self.assertEqual(self.client().get(f"/fotos/{table['image']}").status_code, 302)

    def test_switch_between_table_and_tiles(self):
        admin, player = self.client("admin"), self.client("a")
        page = player.get("/").get_data(as_text=True)
        self.assertNotIn("view-switch", page)  # without a picture there is nothing to switch
        self.assertNotIn('id="view-kacheln" aria-label="Verkostungen" hidden', page)
        self.table(admin)
        page = player.get("/").get_data(as_text=True)
        # The table comes first; the tiles wait, and every tasting is still linked below the picture.
        self.assertIn('id="view-tafel" >', page)
        self.assertIn('id="view-kacheln" aria-label="Verkostungen" hidden', page)
        for href in ("/chips/", "/cola/", "/wasser/"):
            self.assertIn(f'href="{href}" class="m-table-link', page)
        response = self.post(player, "/start/ansicht", view="kacheln")
        self.assertEqual(response.status_code, 302)
        self.assertIn("ansicht=kacheln", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        page = player.get("/").get_data(as_text=True)
        self.assertIn('id="view-tafel" hidden', page)
        self.assertIn('id="view-kacheln" aria-label="Verkostungen" >', page)
        self.assertIn('value="kacheln" aria-pressed="true"', page)
        # The page script saves in the background and gets no redirect.
        response = player.post("/start/ansicht", data={"view": "tafel"}, headers={"X-CSRF-Token": self.token(player)})
        self.assertEqual(response.status_code, 204)
        self.assertIn('id="view-tafel" >', player.get("/").get_data(as_text=True))
        self.assertEqual(self.post(player, "/start/ansicht", view="<script>").status_code, 400)
        self.assertEqual(player.post("/start/ansicht", data={"view": "tafel"}).status_code, 403)  # no CSRF token
        self.assertNotIn("ansicht=", player.post("/start/ansicht", data={"view": "tafel"}).headers.get("Set-Cookie", ""))

    def test_bad_spots_change_nothing(self):
        admin = self.client("admin")
        self.table(admin)
        self.post(admin, "/start/tafel/punkte", spot_chips_x="25", spot_chips_y="60", spot_chips_r="8")
        for bad in ({"spot_chips_x": "120", "spot_chips_y": "60", "spot_chips_r": "8"},
                    {"spot_chips_x": "nan", "spot_chips_y": "60", "spot_chips_r": "8"},
                    {"spot_chips_x": "25", "spot_chips_y": "60", "spot_chips_r": "90"}):
            self.post(admin, "/start/tafel/punkte", **bad)
        self.post(admin, "/start/tafel/punkte", spot_nope_x="10", spot_nope_y="10", spot_nope_r="5")
        self.assertEqual(self.store.document("start").read()["table"]["spots"], {})
        self.post(admin, "/start/tafel/punkte", spot_chips_x="25", spot_chips_y="60", spot_chips_r="8")
        self.assertEqual(list(self.store.document("start").read()["table"]["spots"]), ["chips"])

    def test_replacing_and_removing_the_table(self):
        admin = self.client("admin")
        self.table(admin)
        self.post(admin, "/start/tafel/punkte", spot_chips_x="25", spot_chips_y="60", spot_chips_r="8")
        first = self.store.document("start").read()["table"]["image"]
        self.table(admin, size=(300, 300))
        table = self.store.document("start").read()["table"]
        self.assertEqual((table["aspect"], list(table["spots"])), (1.0, ["chips"]))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "images", first)))
        self.post(admin, "/start/tafel/loeschen")
        self.assertIsNone(self.store.document("start").read()["table"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "images", table["image"])))

    def test_only_the_admin_sets_the_table(self):
        player = self.client("a")
        self.assertEqual(self.table(player).status_code, 403)
        self.assertEqual(self.post(player, "/start/tafel/punkte", spot_chips_x="1", spot_chips_y="1", spot_chips_r="5").status_code, 403)
        self.assertEqual(self.post(player, "/start/tafel/loeschen").status_code, 403)

    def ideas(self):
        return {i["name"]: i for i in self.store.document("ideas").read()["ideas"]}

    def test_idea_list_with_stars(self):
        alice, bob, admin = self.client("a"), self.client("b"), self.client("admin")
        self.post(alice, "/ideen", name="  Saure Gurken ")
        self.post(bob, "/ideen", name="saure gurken")  # the same idea, only written differently
        self.post(bob, "/ideen", name="Energydrinks")
        self.post(bob, "/ideen", name="   ")
        ideas = self.ideas()
        self.assertEqual(sorted(ideas), ["Energydrinks", "Saure Gurken"])
        self.assertEqual((ideas["Saure Gurken"]["by"], ideas["Energydrinks"]["by"]), ("a", "b"))
        gurken, drinks = ideas["Saure Gurken"]["id"], ideas["Energydrinks"]["id"]
        self.post(alice, f"/ideen/{gurken}/sterne", stars="3")
        self.post(bob, f"/ideen/{gurken}/sterne", stars="2")
        self.post(alice, f"/ideen/{drinks}/sterne", stars="5")
        self.post(alice, f"/ideen/{drinks}/sterne", stars="4")  # changed her mind
        self.assertEqual(self.ideas()["Energydrinks"]["ratings"], {"a": 4})
        for bad in ("0", "6", "viel"):
            self.assertEqual(self.post(alice, f"/ideen/{gurken}/sterne", stars=bad).status_code, 400)
        self.assertEqual(self.post(alice, "/ideen/nope/sterne", stars="3").status_code, 404)
        page = alice.get("/ideen").get_data(as_text=True)
        # Best average first: Energydrinks (4) above Saure Gurken (2.5).
        self.assertLess(page.index('"m-idea-name">Energydrinks'), page.index('"m-idea-name">Saure Gurken'))
        self.assertIn("★ 2,5 aus 2 Wertungen", page)
        self.assertIn("Deine Wertung: 4.", page)
        landing = bob.get("/").get_data(as_text=True)
        self.assertIn("2 Ideen", landing)
        self.assertIn("★ Energydrinks", landing)
        # Tapping your own rating again takes it back.
        self.post(alice, f"/ideen/{drinks}/sterne", stars="4")
        self.assertEqual(self.ideas()["Energydrinks"]["ratings"], {})
        # Only whoever added an idea, or the admin, takes it off the list.
        self.assertEqual(self.post(bob, f"/ideen/{gurken}/loeschen").status_code, 403)
        self.post(alice, f"/ideen/{gurken}/loeschen")
        self.post(admin, f"/ideen/{drinks}/loeschen")
        self.assertEqual(self.ideas(), {})
        self.assertEqual(self.client().get("/ideen").status_code, 302)

    def plans(self):
        return {p["slug"]: p for p in self.store.document("plans").read()["plans"]}

    def test_plan_a_tasting_and_its_questions(self):
        admin, player = self.client("admin"), self.client("a")
        self.assertNotIn("/plaene/neu", player.get("/").get_data(as_text=True))
        self.assertEqual(player.get("/plaene/neu").status_code, 403)
        self.assertEqual(self.post(player, "/plaene/neu", title="Heimlich").status_code, 403)
        self.assertIn("/plaene/neu", admin.get("/").get_data(as_text=True))
        response = self.post(admin, "/plaene/neu", title="Kaffee-Verkostung", short="Kaffee", icon="☕", tagline="Von Discounter bis Rösterei")
        self.assertEqual(response.headers["Location"], "/plaene/kaffee-verkostung")
        base = "/plaene/kaffee-verkostung"
        self.post(admin, f"{base}/abschnitt", title="Die Nase")
        self.post(admin, f"{base}/abschnitt/0/frage", label="Duft", type="scale", low="kaum", high="betörend")
        self.post(admin, f"{base}/abschnitt/0/frage", label="Was riechst du?", type="text", low="ignored")
        self.post(admin, f"{base}/abschnitt/0/frage", label="Duft", type="scale")
        self.post(admin, f"{base}/abschnitt/0/frage", label="Kaputt", type="quiz")
        self.post(admin, f"{base}/abschnitt/0/frage/1/hoch")
        criteria = self.plans()["kaffee-verkostung"]["sections"][0]["criteria"]
        self.assertEqual([(c["key"], c["type"]) for c in criteria],
                         [("was_riechst_du", "text"), ("duft", "scale"), ("duft_2", "scale")])
        self.assertEqual((criteria[1]["low"], criteria[1]["high"]), ("kaum", "betörend"))
        self.assertNotIn("low", criteria[0])
        self.post(admin, f"{base}/abschnitt/0/frage/2/loeschen")
        self.assertEqual(self.post(admin, f"{base}/abschnitt/5/frage/0/loeschen").status_code, 404)
        # Everyone sees it as coming soon, only the admin can edit it.
        landing = player.get("/").get_data(as_text=True)
        self.assertIn(f'class="app-tile app-tile-plan" href="{base}"', landing)
        self.assertIn("Bald", landing)
        self.assertIn("2 Fragen · 1 Abschnitt", landing)
        page = player.get(base).get_data(as_text=True)
        self.assertIn("Was riechst du?", page)
        self.assertNotIn("Frage hinzufügen", page)
        self.assertIn("Frage hinzufügen", admin.get(base).get_data(as_text=True))
        self.assertEqual(self.post(player, f"{base}/abschnitt/0/frage", label="X", type="text").status_code, 403)
        self.assertEqual(player.get(f"{base}/vorlage.json").status_code, 403)
        # The template goes out and comes back in as a new plan with the same questions.
        template = json.loads(admin.get(f"{base}/vorlage.json").get_data(as_text=True))
        self.assertEqual(template["format"], "tasting-template/1")
        self.assertNotIn("slug", template)
        response = admin.post("/plaene/import", data={"csrf_token": self.token(admin), "file": (io.BytesIO(json.dumps(template).encode()), "v.json")},
                              content_type="multipart/form-data")
        self.assertEqual(response.headers["Location"], "/plaene/kaffee-verkostung-2")
        self.assertEqual(self.plans()["kaffee-verkostung-2"]["sections"], self.plans()["kaffee-verkostung"]["sections"])
        for bad in (b"{nope", json.dumps({"format": "other", "title": "x"}).encode(),
                    json.dumps({"format": "tasting-template/1", "title": "x", "sections": [{"criteria": [{"label": "x", "type": "quiz"}]}]}).encode()):
            admin.post("/plaene/import", data={"csrf_token": self.token(admin), "file": (io.BytesIO(bad), "v.json")},
                       content_type="multipart/form-data")
        self.assertEqual(len(self.plans()), 2)
        # A name that matches an existing address gets its own.
        self.post(admin, "/plaene/neu", title="Chips")
        self.assertIn("chips-2", self.plans())
        self.post(admin, "/plaene/kaffee-verkostung/loeschen")
        self.assertEqual(sorted(self.plans()), ["chips-2", "kaffee-verkostung-2"])
        self.assertEqual(player.get("/plaene/kaffee-verkostung").status_code, 404)

    def test_every_page_renders(self):
        admin, chips = self.add_chips()
        self.post(admin, "/plaene/neu", title="Kaffee")
        self.post(admin, "/plaene/kaffee/abschnitt", title="Die Nase")
        self.post(admin, "/plaene/kaffee/abschnitt/0/frage", label="Duft", type="scale")
        self.post(admin, "/ideen", name="Gurken")
        for client, urls in ((admin, ("/", "/chips/admin", "/chips/admin/daten", "/chips/einkauf", "/cola/", "/wasser/",
                                      "/plaene/neu", "/plaene/kaffee", "/ideen")),
                             (self.client("a"), ("/", "/chips/", "/chips/einkauf", f"/chips/schale/{chips[0]['id']}",
                                                 "/chips/enthuellung", "/chips/ergebnisse", "/cola/", "/wasser/",
                                                 "/plaene/kaffee", "/ideen"))):
            for url in urls:
                self.assertEqual(client.get(url).status_code, 200, url)

    def test_every_page_of_a_tasting_uses_its_look(self):
        player = self.client("a")
        self.assertIn("css/master.css", player.get("/").get_data(as_text=True))
        self.assertIn("css/master.css", self.client().get("/login").get_data(as_text=True))
        chips = player.get("/chips/einkauf").get_data(as_text=True)
        self.assertIn("css/style.css", chips)
        self.assertIn('content="/chips/"', chips)


class Verwaltung(Base):
    def login(self, uid, passphrase):
        client = self.app.test_client()
        response = client.post("/login", data={"csrf_token": self.token(client), "user": uid, "passphrase": passphrase})
        return client, response.status_code

    def passphrase(self, response):
        return re.search(r'class="m-passphrase" aria-label="Passphrase">([^<]+)<', response.get_data(as_text=True)).group(1)

    def test_only_the_admin_reaches_the_panel(self):
        player = self.client("a")
        self.assertEqual(player.get("/verwaltung").status_code, 403)
        self.assertNotIn("/verwaltung", player.get("/").get_data(as_text=True))
        for url, fields in (("/verwaltung/nutzer", {"name": "X"}), ("/verwaltung/nutzer/b/passphrase", {}),
                            ("/verwaltung/nutzer/b/name", {"name": "Y"}), ("/verwaltung/nutzer/b/rolle", {"role": "admin"}),
                            ("/verwaltung/nutzer/b/aktiv", {"active": "0"}), ("/verwaltung/nutzer/b/loeschen", {}),
                            ("/verwaltung/tastings", {}), ("/verwaltung/teilnahme/x", {})):
            self.assertEqual(self.post(player, url, **fields).status_code, 403, url)
        admin = self.client("admin")
        self.assertIn("/verwaltung", admin.get("/").get_data(as_text=True))
        self.assertEqual(admin.get("/verwaltung").status_code, 200)

    def test_new_login_shows_its_passphrase_once(self):
        admin = self.client("admin")
        response = self.post(admin, "/verwaltung/nutzer", name="Gandalf der Graue", role="player")
        self.assertEqual(response.status_code, 200)
        passphrase = self.passphrase(response)
        user = self.store.users()["gandalf-der-graue"]
        self.assertEqual((user["name"], user["role"]), ("Gandalf der Graue", "player"))
        self.assertNotIn(passphrase, json.dumps(self.store.users()))
        self.assertNotIn(passphrase, admin.get("/verwaltung").get_data(as_text=True))
        self.assertEqual(self.login("gandalf-der-graue", passphrase)[1], 302)
        # The same name again is refused and changes nothing.
        self.post(admin, "/verwaltung/nutzer", name="Gandalf  der graue")
        self.assertEqual(self.store.users()["gandalf-der-graue"]["hash"], user["hash"])
        self.post(admin, "/verwaltung/nutzer", name="Saruman", role="admin")
        self.assertEqual(self.store.users()["saruman"]["role"], "admin")

    def test_reset_rename_and_role(self):
        admin, bob = self.client("admin"), self.client("b")
        passphrase = self.passphrase(self.post(admin, "/verwaltung/nutzer/b/passphrase"))
        self.assertEqual(bob.get("/").status_code, 302)  # the old session is over
        self.assertEqual(self.login("b", PASS)[1], 401)
        bob, status = self.login("b", passphrase)
        self.assertEqual(status, 302)
        self.post(admin, "/verwaltung/nutzer/b/name", name="Bob der Baumeister")
        self.assertEqual(self.store.users()["b"]["name"], "Bob der Baumeister")
        self.assertEqual(bob.get("/").status_code, 200)  # renaming keeps the login
        self.post(admin, "/verwaltung/nutzer/b/rolle", role="admin")
        self.assertEqual(bob.get("/verwaltung").status_code, 200)
        self.assertEqual(self.post(admin, "/verwaltung/nutzer/b/rolle", role="king").status_code, 400)

    def test_deactivated_logins_cannot_enter_but_keep_their_name(self):
        admin, chips = self.add_chips()
        alice = self.client("a")
        self.rate(alice, chips[0]["id"], 12)
        self.post(admin, "/verwaltung/nutzer/a/aktiv", active="0")
        self.assertFalse(self.store.users()["a"]["active"])
        self.assertEqual(alice.get("/").status_code, 302)
        self.assertEqual(self.login("a", PASS)[1], 401)
        self.assertNotIn('value="a"', self.client().get("/login").get_data(as_text=True))
        self.assertIn("Alice", json.dumps(stats.compute(self.store.read(), self.store.users()), ensure_ascii=False))
        progress = self.client("b").get("/chips/api/progress").get_data(as_text=True)
        self.assertNotIn("Alice", progress)
        self.post(admin, "/verwaltung/nutzer/a/aktiv", active="1")
        self.assertNotIn("active", self.store.users()["a"])
        self.assertEqual(self.login("a", PASS)[1], 302)

    def test_guards_for_admins_and_data(self):
        admin, chips = self.add_chips()
        for url, fields in (("/verwaltung/nutzer/admin/aktiv", {"active": "0"}), ("/verwaltung/nutzer/admin/rolle", {"role": "player"}),
                            ("/verwaltung/nutzer/admin/loeschen", {})):
            self.post(admin, url, **fields)
        self.assertEqual(self.store.users()["admin"]["role"], "admin")
        self.assertNotIn("active", self.store.users()["admin"])
        # A second admin can't take away the last active admin either.
        self.post(admin, "/verwaltung/nutzer/b/rolle", role="admin")
        bob = self.client("b")
        self.post(bob, "/verwaltung/nutzer/b/aktiv", active="0")  # own login
        self.post(admin, "/verwaltung/nutzer/b/rolle", role="player")
        self.post(bob, "/verwaltung/nutzer/admin/aktiv", active="1")
        self.assertEqual(self.store.users()["b"]["role"], "player")
        # Someone with a rating stays; someone without any data can go.
        self.rate(self.client("a"), chips[0]["id"], 12)
        self.post(admin, "/verwaltung/nutzer/a/loeschen")
        self.assertIn("a", self.store.users())
        self.post(admin, "/verwaltung/nutzer/c/loeschen")
        self.assertNotIn("c", self.store.users())
        self.assertEqual(self.post(admin, "/verwaltung/nutzer/nope/loeschen").status_code, 404)

    def test_participants_per_planned_tasting(self):
        admin = self.client("admin")
        self.post(admin, "/plaene/neu", title="Kaffee")
        self.assertEqual(self.store.document("plans").read()["plans"][0]["participants"], [])
        self.post(admin, "/verwaltung/teilnahme/kaffee", uid=["a", "admin", "nope", "a"])
        self.assertEqual(self.store.document("plans").read()["plans"][0]["participants"], ["a", "admin"])
        self.assertIn("Dabei: Alice, Admin", self.client("b").get("/plaene/kaffee").get_data(as_text=True))
        self.assertEqual(self.post(admin, "/verwaltung/teilnahme/nope", uid="a").status_code, 404)
        # Taking part counts as data: Alice can't be deleted, only deactivated.
        self.post(admin, "/verwaltung/nutzer/a/loeschen")
        self.assertIn("a", self.store.users())

    def test_hidden_tastings_leave_the_start_page(self):
        admin, player = self.client("admin"), self.client("a")
        self.post(admin, "/start/daten", date_cola="2026-02-14", date_chips="2026-11-21")
        admin.post("/start/tafel", data={"csrf_token": self.token(admin), "image": (io.BytesIO(photo_bytes(size=(400, 200))), "t.png")},
                   content_type="multipart/form-data")
        self.post(admin, "/start/tafel/punkte", spot_cola_x="40", spot_cola_y="50", spot_cola_r="5",
                  spot_chips_x="20", spot_chips_y="50", spot_chips_r="5")
        self.post(admin, "/verwaltung/tastings", shown=["wasser"])
        self.assertEqual(self.store.document("start").read()["hidden"], ["chips", "cola"])
        page = player.get("/").get_data(as_text=True)
        self.assertNotIn('href="/cola/"', page)
        self.assertNotIn('href="/chips/"', page)
        self.assertIn('href="/wasser/"', page)
        for url in ("/cola/", "/chips/", "/chips/einkauf", "/cola/api/ergebnisse"):
            self.assertEqual(player.get(url).status_code, 404, url)
        # Removed means removed, for the admin too; /verwaltung lists them to bring back.
        self.assertEqual(admin.get("/cola/").status_code, 404)
        self.assertEqual(admin.get("/chips/admin").status_code, 404)
        self.assertNotIn('href="/cola/"', admin.get("/").get_data(as_text=True))
        self.assertIn("Zurückholen", admin.get("/verwaltung").get_data(as_text=True))
        # Saving dates and spots for what is shown keeps those of the hidden tastings.
        self.post(admin, "/start/daten", date_wasser="2026-08-16")
        self.post(admin, "/start/tafel/punkte", spot_wasser_x="60", spot_wasser_y="50", spot_wasser_r="5")
        start = self.store.document("start").read()
        self.assertEqual(start["dates"], {"cola": "2026-02-14", "chips": "2026-11-21", "wasser": "2026-08-16"})
        self.assertEqual(sorted(start["table"]["spots"]), ["chips", "cola", "wasser"])
        self.post(admin, "/verwaltung/tastings", shown=["chips", "cola", "wasser"])
        self.assertEqual(player.get("/cola/").status_code, 200)
        self.assertIn('href="/chips/" class="m-spot"', player.get("/").get_data(as_text=True))

    def test_samples_are_removed_and_brought_back_one_by_one(self):
        admin, player = self.client("admin"), self.client("a")
        self.post(admin, "/verwaltung/tastings/cola/entfernen")
        self.post(admin, "/verwaltung/tastings/chips/entfernen")
        self.assertEqual(self.store.document("start").read()["hidden"], ["cola", "chips"])
        self.assertEqual(player.get("/cola/").status_code, 404)
        self.post(admin, "/verwaltung/tastings/cola/zurueckholen")
        self.assertEqual(self.store.document("start").read()["hidden"], ["chips"])
        self.assertEqual(player.get("/cola/").status_code, 200)
        self.assertEqual(self.post(admin, "/verwaltung/tastings/nope/entfernen").status_code, 404)
        self.assertEqual(self.post(admin, "/verwaltung/tastings/cola/verbrennen").status_code, 404)
        self.assertEqual(self.post(player, "/verwaltung/tastings/wasser/entfernen").status_code, 403)

    def test_container_word_at_creation_start_and_afterwards(self):
        admin = self.client("admin")
        self.post(admin, "/plaene/neu", title="Saft", vessel_one="Glas", vessel_many="")
        plan = self.store.document("plans").read()["plans"][0]
        self.assertEqual(plan["vessel"], {"one": "Glas", "many": "Gläser"})  # plural from the suggestions
        self.post(admin, "/plaene/saft/abschnitt", title="A")
        self.post(admin, "/plaene/saft/abschnitt/0/frage", label="Gut?", type="scale")
        self.post(admin, "/plaene/saft/starten", vessel_one="Becher", vessel_many="")
        plan = self.store.document("plans").read()["plans"][0]
        self.assertEqual((plan["state"], plan["vessel"]), ("live", {"one": "Becher", "many": "Becher"}))
        response = self.post(admin, "/plaene/saft/angaben", title="Saft", vessel_one="Kelch", vessel_many="Kelche")
        self.assertEqual(response.headers["Location"], "/live/saft/admin")
        self.assertIn("Die Kelche", admin.get("/live/saft/").get_data(as_text=True))
        self.assertIn('list="vessel-list"', admin.get("/plaene/neu").get_data(as_text=True))

    def test_one_list_of_every_tasting(self):
        admin = self.client("admin")
        self.post(admin, "/plaene/neu", title="Kaffee")
        self.post(admin, "/plaene/neu/muster/cola")
        self.post(admin, "/plaene/neue-cola-verkostung/starten")
        page = admin.get("/verwaltung").get_data(as_text=True)
        for text in ("Blutkrieg der Chips", "Cola-Verkostung", "Wasser-Verkostung", "Kaffee", "Geplant", "Läuft", "mitgeliefert"):
            self.assertIn(text, page)
        self.assertIn('href="/live/neue-cola-verkostung/admin"', page)
        self.assertEqual(self.client("a").get("/verwaltung").status_code, 403)
        self.assertEqual(self.post(self.client("a"), "/verwaltung/tastings/kaffee/loeschen").status_code, 403)

    def test_deleting_planned_and_running_tastings_from_the_list(self):
        admin = self.client("admin")
        self.post(admin, "/plaene/neu", title="Kaffee")
        self.post(admin, "/verwaltung/tastings/kaffee/loeschen")
        self.assertEqual(self.store.document("plans").read()["plans"], [])
        self.assertTrue(any(f.startswith("plans-") for f in os.listdir(os.path.join(self.tmp.name, "backups"))))
        # A running one with purchases asks for its name.
        self.post(admin, "/plaene/neu/muster/wasser")
        self.post(admin, "/verwaltung/teilnahme/neue-wasser-verkostung", uid=["admin"])
        self.post(admin, "/plaene/neue-wasser-verkostung/starten")
        self.post(admin, "/live/neue-wasser-verkostung/einkauf", name="Leitungswasser", buyer="me")
        self.post(admin, "/verwaltung/tastings/neue-wasser-verkostung/loeschen")
        self.post(admin, "/verwaltung/tastings/neue-wasser-verkostung/loeschen", confirm="Kaffee")
        self.assertTrue(self.store.document("live-neue-wasser-verkostung").exists())
        self.post(admin, "/verwaltung/tastings/neue-wasser-verkostung/loeschen", confirm="Neue Wasser-Verkostung")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "live-neue-wasser-verkostung.json")))
        self.assertTrue(any(f.startswith("live-neue-wasser-verkostung-") for f in os.listdir(os.path.join(self.tmp.name, "backups"))))
        self.assertEqual(admin.get("/live/neue-wasser-verkostung/").status_code, 404)
        self.assertEqual(self.post(admin, "/verwaltung/tastings/nope/loeschen").status_code, 404)

    def test_deleting_the_built_in_tastings_for_good(self):
        admin, player = self.client("admin"), self.client("a")
        admin.post("/cola/einspielen", data={"csrf_token": self.token(admin), "file": (io.BytesIO(json.dumps(small_archive()).encode()), "c.json")},
                   content_type="multipart/form-data")
        self.assertTrue(self.store.document("cola").exists())
        self.post(admin, "/start/daten", date_cola="2026-02-14")
        self.post(admin, "/verwaltung/tastings/cola/loeschen")  # has data: needs the name
        self.assertTrue(self.store.document("cola").exists())
        self.post(admin, "/verwaltung/tastings/cola/loeschen", confirm="Cola-Verkostung")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "cola.json")))
        self.assertTrue(any(f.startswith("cola-") for f in os.listdir(os.path.join(self.tmp.name, "backups"))))
        self.assertEqual(self.store.document("start").read()["deleted"], ["cola"])
        for client in (admin, player):
            self.assertEqual(client.get("/cola/").status_code, 404)
            self.assertNotIn('href="/cola/"', client.get("/").get_data(as_text=True))
        verwaltung = admin.get("/verwaltung").get_data(as_text=True)
        self.assertNotIn("Cola-Verkostung", verwaltung.split('id="tastings"')[1])
        self.assertNotIn("date_cola", admin.get("/").get_data(as_text=True))
        # Chips with bowls and photos: emptied, its photos gone, a backup kept.
        self.upload(admin, "/chips/chips", name="Geheimchip", brand="Funny", flavor_type="Paprika")
        photo = self.store.read()["chips"][0]["image"]
        self.post(admin, "/verwaltung/tastings/chips/loeschen", confirm="blutkrieg der chips")
        self.assertEqual((self.store.read()["chips"], self.store.read()["shopping"]), ([], []))
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "images", photo)))
        self.assertEqual(player.get("/chips/").status_code, 404)
        self.assertEqual(admin.get("/chips/admin").status_code, 404)
        # Water without data goes with a simple confirm.
        self.post(admin, "/verwaltung/tastings/wasser/loeschen")
        self.assertEqual(self.store.document("start").read()["deleted"], ["cola", "chips", "wasser"])
        self.assertIn("Was als Nächstes?", player.get("/").get_data(as_text=True))
        # Only the command line brings one back, empty.
        os.environ["DATA_DIR"] = self.tmp.name
        self.addCleanup(os.environ.pop, "DATA_DIR", None)
        with contextlib.redirect_stdout(io.StringIO()):
            manage_main(["muster-zurueckholen", "cola"])
        restarted = create_app(self.tmp.name)
        self.assertEqual(restarted.extensions["store"].document("start").read()["deleted"], ["chips", "wasser"])

    def test_samples_start_new_plans(self):
        admin = self.client("admin")
        self.assertIn("Oder mit einem Muster anfangen", admin.get("/plaene/neu").get_data(as_text=True))
        for name, slug, vessel, ranking in (("chips", "neue-chips-verkostung", "Schale", "persoenlicher_genuss"),
                                           ("cola", "neue-cola-verkostung", "Glas", "persoenlicher_genussfaktor"),
                                           ("wasser", "neue-wasser-verkostung", "Glas", "persoenlicher_genuss")):
            response = self.post(admin, f"/plaene/neu/muster/{name}")
            self.assertEqual(response.headers["Location"], f"/plaene/{slug}")
            plan = next(p for p in self.store.document("plans").read()["plans"] if p["slug"] == slug)
            self.assertEqual((plan["vessel"]["one"], plan["ranking"]), (vessel, ranking))
            self.assertGreater(sum(len(s["criteria"]) for s in plan["sections"]), 10)
            self.assertIsNone(plans.validate(plans.export(plan)))
        self.assertEqual(self.post(admin, "/plaene/neu/muster/bier").status_code, 404)
        self.assertEqual(self.post(self.client("a"), "/plaene/neu/muster/cola").status_code, 403)
        # A sample runs straight away.
        self.post(admin, "/verwaltung/teilnahme/neue-cola-verkostung", uid=["a"])
        self.post(admin, "/plaene/neue-cola-verkostung/starten")
        alice = self.client("a")
        self.post(alice, "/live/neue-cola-verkostung/einkauf", name="Cola", buyer="me")
        item = self.store.document("live-neue-cola-verkostung").read()["items"][0]
        self.post(alice, f"/live/neue-cola-verkostung/einkauf/{item['id']}/aufstellen")
        glass = self.store.document("live-neue-cola-verkostung").read()["vessels"][0]
        keys = [c["key"] for s in self.store.document("live-neue-cola-verkostung").read()["sections"] for c in s["criteria"]]
        self.post(alice, f"/live/neue-cola-verkostung/gefaess/{glass['id']}", **{f"score_{k}": "3" for k in keys})
        self.assertEqual(len(self.store.document("live-neue-cola-verkostung").read()["ratings"][glass["id"]]["a"]["scores"]), len(keys))

    def test_manage_list_shows_deactivated(self):
        users = self.store.users()
        users["c"]["active"] = False
        self.store.save_users(users)
        os.environ["DATA_DIR"] = self.tmp.name
        self.addCleanup(os.environ.pop, "DATA_DIR", None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            manage_main(["list"])
        self.assertIn("Cleo (player, deaktiviert)", out.getvalue())
        self.assertIn("Bob (player)\n", out.getvalue())


class Live(Base):
    """Tastings started from a plan: /live/<slug>/."""

    BASE = "/live/cola-runde"

    def start(self, participants=("a", "b", "admin")):
        admin = self.client("admin")
        self.post(admin, "/plaene/neu", title="Cola-Runde")
        self.post(admin, "/plaene/cola-runde/abschnitt", title="Der Gaumen")
        self.post(admin, "/plaene/cola-runde/abschnitt/0/frage", label="Geschmack", type="scale", low="bäh", high="hmm")
        self.post(admin, "/plaene/cola-runde/abschnitt/0/frage", label="Was schmeckst du?", type="text")
        self.post(admin, "/plaene/cola-runde/angaben", title="Cola-Runde", vessel_one="Glas", vessel_many="Gläser")
        self.post(admin, "/verwaltung/teilnahme/cola-runde", uid=list(participants))
        response = self.post(admin, "/plaene/cola-runde/starten")
        self.assertEqual(response.headers["Location"], f"{self.BASE}/")
        return admin

    def data(self):
        return self.store.document("live-cola-runde").read()

    def item(self, client, name, **fields):
        return self.post(client, f"{self.BASE}/einkauf", name=name, buyer="me", **fields)

    def set_up(self, client, name):
        item = next(i for i in self.data()["items"] if i["name"] == name)
        self.post(client, f"{self.BASE}/einkauf/{item['id']}/aufstellen")
        return next(v for v in self.data()["vessels"] if v["item_id"] == item["id"])

    def test_starting_freezes_the_questions(self):
        admin = self.client("admin")
        self.post(admin, "/plaene/neu", title="Nur Text")
        self.post(admin, "/plaene/nur-text/abschnitt", title="A")
        self.post(admin, "/plaene/nur-text/abschnitt/0/frage", label="Was?", type="text")
        self.post(admin, "/plaene/nur-text/starten")
        self.assertFalse(self.store.document("live-nur-text").exists())  # no scale question, no ranking
        self.assertEqual(self.post(self.client("a"), "/plaene/nur-text/starten").status_code, 403)
        admin = self.start()
        plan = next(p for p in self.store.document("plans").read()["plans"] if p["slug"] == "cola-runde")
        self.assertEqual((plan["state"], plan["ranking"], plan["vessel"]), ("live", "geschmack", {"one": "Glas", "many": "Gläser"}))
        self.assertEqual([c["key"] for c in self.data()["sections"][0]["criteria"]], ["geschmack", "was_schmeckst_du"])
        self.post(admin, "/plaene/cola-runde/abschnitt/0/frage", label="Noch eine", type="scale")
        self.assertEqual(len(self.data()["sections"][0]["criteria"]), 2)
        self.assertEqual(len(plan["sections"][0]["criteria"]), 2)
        self.assertEqual(admin.get("/plaene/cola-runde").headers["Location"], f"{self.BASE}/")
        landing = self.client("c").get("/").get_data(as_text=True)
        self.assertIn(f'href="{self.BASE}/"', landing)
        self.assertIn("Eigenes Tasting", landing)
        self.assertNotIn('href="/plaene/cola-runde"', landing)  # no longer under "Was als Nächstes?"
        self.assertEqual(self.client("c").get("/live/nope/").status_code, 404)

    def test_only_participants_shop_set_up_and_rate(self):
        self.start()
        alice, bob, cleo = self.client("a"), self.client("b"), self.client("c")
        self.item(alice, "Cola Zero", brand="Discounter", note="ohne Zucker", price="0,49", amount="1500", unit="ml")
        self.item(bob, "cola zero", brand="discounter")  # the same thing again
        self.post(bob, f"{self.BASE}/einkauf", name="Wunsch-Cola", buyer="open")
        items = {i["name"]: i for i in self.data()["items"]}
        self.assertEqual(sorted(items), ["Cola Zero", "Wunsch-Cola"])
        self.assertEqual((items["Cola Zero"]["price"], items["Cola Zero"]["amount"], items["Cola Zero"]["unit"]), (0.49, 1500, "ml"))
        self.assertIsNone(items["Wunsch-Cola"]["buyer"])
        wish = items["Wunsch-Cola"]["id"]
        for url, fields in ((f"{self.BASE}/einkauf", {"name": "X"}), (f"{self.BASE}/einkauf/{wish}/kaufen", {}),
                            (f"{self.BASE}/einkauf/{wish}/aufstellen", {}), (f"{self.BASE}/einkauf/{wish}/streichen", {})):
            self.assertEqual(self.post(cleo, url, **fields).status_code, 403, url)
        for url in (f"{self.BASE}/", f"{self.BASE}/einkauf", f"{self.BASE}/ergebnisse"):
            self.assertEqual(cleo.get(url).status_code, 200, url)
        self.assertIn("nicht eingetragen", cleo.get(f"{self.BASE}/").get_data(as_text=True))
        self.post(alice, f"{self.BASE}/einkauf/{wish}/kaufen")
        self.post(alice, f"{self.BASE}/einkauf/{wish}/gekauft")
        wish_item = next(i for i in self.data()["items"] if i["id"] == wish)
        self.assertEqual((wish_item["buyer"], wish_item["bought"]), ("a", True))
        self.assertEqual(self.post(self.client("admin"), f"{self.BASE}/einkauf/{wish}/kaufen").status_code, 302)  # admin is entered
        # Prices stay with whoever may edit the entry until the reveal.
        self.assertIn("0,49 €", alice.get(f"{self.BASE}/einkauf").get_data(as_text=True))
        self.assertNotIn("0,49 €", bob.get(f"{self.BASE}/einkauf").get_data(as_text=True))
        self.assertIn("0,03 €/100 ml", alice.get(f"{self.BASE}/einkauf").get_data(as_text=True))

    def test_photos_stay_with_the_tasting(self):
        self.start()
        alice = self.client("a")
        alice.post(f"{self.BASE}/einkauf", data={"csrf_token": self.token(alice), "name": "Cola", "buyer": "me",
                                                "image": (io.BytesIO(photo_bytes()), "c.png")}, content_type="multipart/form-data")
        name = self.data()["items"][0]["image"]
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "images", "live-cola-runde", name)))
        self.assertEqual(self.client("c").get(f"{self.BASE}/bild/{name}").status_code, 200)  # the list is open to all
        self.post(alice, f"{self.BASE}/einkauf/{self.data()['items'][0]['id']}/streichen")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "images", "live-cola-runde", name)))

    def test_containers_are_blind_and_rated_by_the_plan(self):
        admin = self.start()
        alice, bob = self.client("a"), self.client("b")
        self.item(alice, "Cola Zero", brand="Discounter")
        self.item(bob, "Classic", brand="Markencola")
        first, second = self.set_up(alice, "Cola Zero"), self.set_up(alice, "Classic")
        self.assertEqual((first["number"], second["number"]), (1, 2))
        progress = bob.get(f"{self.BASE}/api/progress").get_data(as_text=True)
        self.assertNotIn("Cola Zero", progress)
        self.assertNotIn("Markencola", progress)
        self.assertNotIn("Cola Zero", bob.get(f"{self.BASE}/").get_data(as_text=True))
        self.assertIn("Cola Zero", alice.get(f"{self.BASE}/").get_data(as_text=True))  # she set it up
        rate = f"{self.BASE}/gefaess/{first['id']}"
        self.assertIn("Glas 1", bob.get(rate).get_data(as_text=True))
        for bad in ({}, {"score_geschmack": "0"}, {"score_geschmack": "6"}, {"score_geschmack": "drei"}):
            self.assertEqual(self.post(bob, rate, **bad).status_code, 422)
        self.post(bob, rate, score_geschmack="2", text_was_schmeckst_du="Vanille", notes="zu süß")
        self.assertEqual(self.data()["ratings"][first["id"]]["b"],
                         {"scores": {"geschmack": 2}, "texts": {"was_schmeckst_du": "Vanille"}, "notes": "zu süß"})
        self.post(admin, rate, score_geschmack="4")
        self.assertEqual(self.data()["ratings"][first["id"]]["admin"]["scores"], {"geschmack": 4})
        self.assertEqual(self.post(self.client("c"), rate, score_geschmack="3").status_code, 403)
        self.post(admin, f"{self.BASE}/admin/mischen")
        self.assertEqual(sorted(v["number"] for v in self.data()["vessels"]), [1, 2])
        self.assertEqual({v["id"]: v["number"] for v in self.data()["vessels"]}, {first["id"]: 1, second["id"]: 2})
        self.assertIn("Cola Zero", admin.get(f"{self.BASE}/admin").get_data(as_text=True))
        self.assertEqual(alice.get(f"{self.BASE}/admin").status_code, 403)

    def test_admin_rates_only_when_entered(self):
        self.start(participants=("a", "b"))
        alice = self.client("a")
        self.item(alice, "Cola")
        vessel = self.set_up(alice, "Cola")
        self.assertEqual(self.post(self.client("admin"), f"{self.BASE}/gefaess/{vessel['id']}", score_geschmack="3").status_code, 403)

    def test_reveal_and_results(self):
        admin = self.start()
        alice, bob = self.client("a"), self.client("b")
        self.item(alice, "Cola Zero", brand="Discounter", price="0,50", amount="1000", unit="ml")
        self.item(bob, "Classic", brand="Markencola", price="2", amount="1000", unit="ml")
        zero, classic = self.set_up(alice, "Cola Zero"), self.set_up(bob, "Classic")
        self.assertEqual(bob.get(f"{self.BASE}/api/ergebnisse").status_code, 403)
        for client, z, c in ((alice, "4", "2"), (bob, "5", "3")):
            self.post(client, f"{self.BASE}/gefaess/{zero['id']}", score_geschmack=z, text_was_schmeckst_du="Karamell")
            self.post(client, f"{self.BASE}/gefaess/{classic['id']}", score_geschmack=c)
        self.post(admin, f"{self.BASE}/admin/enthuellung")
        self.assertEqual(self.data()["phase"], "ceremony")
        self.assertEqual(self.data()["ceremony_order"], [classic["id"], zero["id"]])  # worst first
        self.assertEqual(self.post(alice, f"{self.BASE}/gefaess/{zero['id']}", score_geschmack="1").status_code, 302)
        self.assertEqual(self.data()["ratings"][zero["id"]]["a"]["scores"]["geschmack"], 4)  # sealed
        ceremony = json.loads(admin.post(f"{self.BASE}/api/ceremony/next", headers={"X-CSRF-Token": self.token(admin)}).get_data(as_text=True))
        self.assertEqual(ceremony["revealed"][0]["label"], "Markencola Classic")
        self.assertEqual(ceremony["revealed"][0]["meta"], "Glas 2")
        self.assertEqual(ceremony["revealed"][0]["score"], "Ø 2,5")
        admin.post(f"{self.BASE}/api/ceremony/next", headers={"X-CSRF-Token": self.token(admin)})
        self.assertEqual(self.data()["phase"], "revealed")
        results = json.loads(bob.get(f"{self.BASE}/api/ergebnisse").get_data(as_text=True))
        self.assertEqual([r["name"] for r in results["ranking"]], ["Discounter Cola Zero", "Markencola Classic"])
        self.assertEqual(results["ranking"][0]["price_per_100"], 0.05)
        self.assertIn("Das Schnäppchen", [a["title"] for a in results["awards"]])
        self.assertIn("Was schmeckst du?: Karamell", [n["text"] for n in results["notes"]])
        self.assertEqual([s["criteria"][0]["key"] for s in results["sections"]], ["geschmack"])  # text questions aren't scales
        export = json.loads(admin.get(f"{self.BASE}/admin/export.json").get_data(as_text=True))
        self.assertIsNone(archive.validate(export))
        self.assertIn("♛ Discounter Cola Zero", bob.get("/").get_data(as_text=True))
        self.assertEqual(bob.get(f"{self.BASE}/").headers["Location"], f"{self.BASE}/ergebnisse")
        self.post(admin, f"{self.BASE}/admin/zurueck")
        self.assertEqual(self.data()["phase"], "tasting")
        self.assertEqual(len(self.data()["ratings"][zero["id"]]), 2)

    def test_nothing_to_reveal_without_ratings(self):
        admin = self.start()
        self.post(admin, f"{self.BASE}/admin/enthuellung")
        self.assertEqual(self.data()["phase"], "tasting")

    def test_start_page_date_and_table_spot(self):
        admin = self.start()
        self.post(admin, "/start/daten", **{"date_cola-runde": "2026-12-05"})
        self.assertEqual(self.store.document("start").read()["dates"]["cola-runde"], "2026-12-05")
        admin.post("/start/tafel", data={"csrf_token": self.token(admin), "image": (io.BytesIO(photo_bytes(size=(400, 200))), "t.png")},
                   content_type="multipart/form-data")
        self.post(admin, "/start/tafel/punkte", **{"spot_cola-runde_x": "30", "spot_cola-runde_y": "40", "spot_cola-runde_r": "5"})
        self.assertIn("cola-runde", self.store.document("start").read()["table"]["spots"])
        self.assertIn(f'href="{self.BASE}/" class="m-spot"', self.client("a").get("/").get_data(as_text=True))

    def test_deleting_a_running_tasting(self):
        admin = self.start()
        self.post(admin, f"{self.BASE}/admin/loeschen", confirm="falsch")
        self.assertTrue(self.store.document("live-cola-runde").exists())
        self.post(admin, f"{self.BASE}/admin/loeschen", confirm="cola-runde")
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "live-cola-runde.json")))
        self.assertEqual(self.store.document("plans").read()["plans"], [])
        self.assertEqual(admin.get(f"{self.BASE}/").status_code, 404)


class ArchiveStats(unittest.TestCase):
    def test_ranking_groups_flags_and_awards(self):
        result = archive.compute(small_archive())
        self.assertEqual(result["ranking"][0]["value"], 4.5)
        groups = {g["name"]: g["averages"]["genuss"] for g in result["groups"]}
        self.assertEqual(groups, {"Zero": 2.5, "Zucker": 3})
        self.assertEqual((result["flags"][0]["with"], result["flags"][0]["count"]), (5, 1))
        awards = {a["title"]: a["winner"] for a in result["awards"]}
        self.assertEqual(awards["Süßeste Bombe"], "Fanta")
        self.assertEqual((awards["Großzügigster Gaumen"], awards["Härteste Kritik"]), ("A", "B"))
        self.assertEqual([n["item"] for n in result["notes"]], ["Cherry"])

    def test_inverted_award_terms(self):
        entry = small_archive(awards=[{"title": "Am wenigsten süß", "terms": [{"key": "suesse", "invert": True}], "best": "max"}])
        self.assertEqual(archive.compute(entry)["awards"][0]["winner"], "Cherry")

    def test_twins_need_three_shared_items(self):
        result = archive.compute(small_archive())
        self.assertAlmostEqual(result["twins"]["closest"]["r"], 0.866, places=2)
        entry = small_archive(items=small_archive()["items"][:2])
        entry["ratings"] = [r for r in entry["ratings"] if r["item"] != "3"]
        self.assertIsNone(archive.compute(entry)["twins"]["closest"])

    def test_missing_answers_are_skipped(self):
        entry = small_archive()
        entry["ratings"][0]["scores"]["suesse"] = None
        self.assertIsNone(archive.validate(entry))
        self.assertEqual(archive.compute(entry)["ranking"][0]["averages"]["suesse"], 2)


class Cleanup(Base):
    def setUp(self):
        super().setUp()
        self.admin, self.chips = self.add_chips()
        self.chip = self.chips[0]["id"]
        self.alice = self.client("a")
        self.rate(self.alice, self.chip, 10, notes="Peinliche Notiz")
        self.rate(self.client("b"), self.chip, 12)

    def test_data_page_lists_entries(self):
        body = self.admin.get("/chips/admin/daten").get_data(as_text=True)
        self.assertIn("Peinliche Notiz", body)
        self.assertIn("Alice", body)

    def test_delete_note_keeps_rating(self):
        self.post(self.admin, f"/chips/admin/daten/{self.chip}/a/note/delete")
        rating = self.store.read()["ratings"][self.chip]["a"]
        self.assertEqual(rating["notes"], "")
        self.assertEqual(rating["dc"], 10)

    def test_delete_rating(self):
        self.post(self.admin, f"/chips/admin/daten/{self.chip}/a/delete")
        self.assertEqual(list(self.store.read()["ratings"][self.chip]), ["b"])

    def test_delete_unknown_rating_is_404(self):
        self.assertEqual(self.post(self.admin, f"/chips/admin/daten/{self.chip}/nobody/delete").status_code, 404)

    def test_admin_deletes_rated_chip_with_ratings(self):
        self.post(self.admin, f"/chips/chips/{self.chip}/delete")
        data = self.store.read()
        self.assertNotIn(self.chip, data["ratings"])
        self.assertEqual(len(data["chips"]), 2)

    def test_players_cannot_cleanse(self):
        for url in (f"/chips/admin/daten/{self.chip}/b/delete", f"/chips/admin/daten/{self.chip}/b/note/delete"):
            self.assertEqual(self.post(self.alice, url).status_code, 403)
        self.assertIn("b", self.store.read()["ratings"][self.chip])

    def test_reset_needs_the_word_and_keeps_logins(self):
        self.post(self.admin, "/chips/admin/reset", confirm="nein")
        self.assertEqual(len(self.store.read()["chips"]), 3)
        self.post(self.admin, "/chips/admin/reset", confirm="asche")
        data = self.store.read()
        self.assertEqual((data["chips"], data["ratings"], data["phase"]), ([], {}, "tasting"))
        self.assertIn("a", self.store.users())

    def test_delete_makes_a_backup_first(self):
        backups = os.path.join(self.tmp.name, "backups")
        for name in os.listdir(backups):
            os.unlink(os.path.join(backups, name))
        self.post(self.admin, f"/chips/admin/daten/{self.chip}/a/delete")
        contents = [open(os.path.join(backups, n), encoding="utf-8").read() for n in os.listdir(backups)]
        self.assertTrue(any("Peinliche Notiz" in text for text in contents))

    def test_no_deleting_during_ceremony(self):
        self.post(self.admin, "/chips/admin/ceremony/start")
        self.post(self.admin, f"/chips/admin/daten/{self.chip}/a/delete")
        self.post(self.admin, f"/chips/chips/{self.chip}/delete")
        data = self.store.read()
        self.assertIn("a", data["ratings"][self.chip])
        self.assertEqual(len(data["chips"]), 3)

    def test_delete_after_reveal_updates_order(self):
        self.post(self.admin, "/chips/admin/ceremony/start")
        headers = {"X-CSRF-Token": self.token(self.admin)}
        last = self.admin.post("/chips/api/ceremony/next", headers=headers).get_json()
        self.assertEqual(last["phase"], "revealed")
        self.post(self.admin, f"/chips/chips/{self.chip}/delete")
        data = self.store.read()
        self.assertEqual((data["ceremony_order"], data["reveal_count"]), ([], 0))
        self.assertEqual(self.alice.get("/chips/api/results").status_code, 200)
        self.assertEqual(self.alice.get("/chips/api/ceremony").status_code, 200)


class Persistence(Base):
    def test_data_survives_restart(self):
        _, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 13, notes="Ümläute öäü")
        reloaded = Store(self.tmp.name).read()
        self.assertEqual(reloaded["ratings"][chips[0]["id"]]["a"]["dc"], 13)
        with open(os.path.join(self.tmp.name, "tasting.json"), encoding="utf-8") as f:
            self.assertIn("Ümläute", f.read())

    def test_old_d20_ratings_are_upgraded(self):
        path = os.path.join(self.tmp.name, "tasting.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"phase": "tasting", "chips": [], "ratings": {"x": {"a": {"enjoyment": 13, "scores": {}}}}}, f)
        rating = Store(self.tmp.name).read()["ratings"]["x"]["a"]
        self.assertEqual(rating["dc"], 13)
        self.assertNotIn("enjoyment", rating)

    def test_login_survives_restart(self):
        client = self.client("a")
        cookie = client.get_cookie("avernus").value
        restarted = create_app(self.tmp.name).test_client()
        restarted.set_cookie("avernus", cookie)
        self.assertEqual(restarted.get("/chips/").status_code, 200)

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
        def rating(dc, **extra):
            return {"scores": {k: 3 for k in SCALE_KEYS}, "dc": dc, **extra}

        chips = [
            {"id": "x", "bowl": 1, "name": "X", "brand": "Funny-Frisch", "flavor_type": "Paprika", "price": 2.0, "weight": 100, "own_brand": False},
            {"id": "y", "bowl": 2, "name": "Y", "brand": "Lorenz", "flavor_type": "BBQ", "price": 1.0, "weight": 200, "own_brand": True},
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

    def test_price_per_100g_compares_bag_sizes_fairly(self):
        self.assertEqual(stats.price_per_100g({"price": 2.0, "weight": 200}), 1.0)
        self.assertIsNone(stats.price_per_100g({"price": 2.0}))
        self.assertIsNone(stats.price_per_100g({"price": None, "weight": 200}))

    def priced(self, coins_a, coins_b):
        """Three chips at 1, 2 and 3 euros per 100 g, with blind coin guesses."""
        def rating(dc, coins):
            return {"scores": {k: 3 for k in SCALE_KEYS}, "dc": dc, "coins": coins}

        chips = [
            {"id": str(n), "bowl": n, "name": f"C{n}", "flavor_type": "BBQ", "price": float(n), "weight": 100}
            for n in (1, 2, 3)
        ]
        ratings = {
            str(n): {"a": rating(5 * n, coins_a[n - 1]), "b": rating(5 * n, coins_b[n - 1])}
            for n in (1, 2, 3)
        }
        return {"chips": chips, "ratings": ratings}

    def test_price_guess_correlation_names_best_and_worst_reader(self):
        result = stats.compute(self.priced([1, 5, 9], [9, 5, 1]), self.users)
        self.assertEqual(self.award(result, "accountant")["winner"], "A")
        self.assertEqual(self.award(result, "mammon")["winner"], "B")
        self.assertEqual([r["name"] for r in result["pricing"]["readers"]], ["A", "B"])
        self.assertAlmostEqual(result["pricing"]["dc_r"], 1.0)
        self.assertIn("süchtig", result["pricing"]["dc_verdict"])

    def test_good_price_reader_is_not_called_betrayed(self):
        result = stats.compute(self.priced([1, 5, 9], [2, 5, 8]), self.users)
        self.assertIsNone(self.award(result, "mammon"))
        self.assertIsNotNone(self.award(result, "accountant"))

    def test_price_group_verdict_follows_correlation(self):
        result = stats.compute(self.priced([1, 5, 9], [1, 5, 9]), self.users)
        self.assertAlmostEqual(result["pricing"]["guess_r"], 1.0)
        self.assertIn("riecht Preise", result["pricing"]["guess_verdict"])
        result = stats.compute(self.priced([9, 5, 1], [9, 5, 1]), self.users)
        self.assertIn("Marketing", result["pricing"]["guess_verdict"])

    def test_price_stats_stay_quiet_without_enough_data(self):
        result = stats.compute(self.tasting(), self.users)
        self.assertIsNone(result["pricing"]["guess_r"])
        self.assertIsNone(self.award(result, "accountant"))
        self.assertIsNone(self.award(result, "impostor"))

    def test_impostor_looks_expensive_but_is_cheap(self):
        result = stats.compute(self.priced([9, 5, 1], [9, 5, 1]), self.users)
        self.assertEqual(self.award(result, "impostor")["winner"], "C1")
        self.assertEqual(self.award(result, "hidden_gem")["winner"], "C3")

    def test_tiers_cover_the_whole_range(self):
        self.assertEqual(stats.addiction_tier(1)["name"], "Immun")
        self.assertEqual(stats.addiction_tier(14.9)["name"], "Bezaubert")
        self.assertEqual(stats.addiction_tier(15)["name"], "Gepackt")
        self.assertEqual(stats.addiction_tier(20)["name"], "Beherrscht")

    def test_character_sheet_and_conditions(self):
        tasting = self.tasting()
        for rating in tasting["ratings"]["x"].values():
            rating["scores"].update(heat=5, potato=1, hardness=5, crunch=5)
        result = stats.compute(tasting, self.users)
        chip = next(c for c in result["chips"] if c["id"] == "x")
        strength = next(a for a in chip["sheet"] if a["label"] == "STÄ")
        self.assertEqual((strength["score"], strength["modifier"]), (18, 4))
        self.assertLessEqual({"Brennend", "Unsichtbar", "Taub", "Kampfunfähig"}, {c["name"] for c in chip["conditions"]})
        self.assertEqual(self.award(result, "conditions")["winner"], "Funny-Frisch X")
        calm = next(c for c in result["chips"] if c["id"] == "y")
        self.assertEqual(calm["conditions"], [])

    def test_chip_alignment_extremes(self):
        tasting = self.tasting()
        for rating in tasting["ratings"]["y"].values():
            rating["scores"].update(integrity=5, harmony=5, coverage=1, potato=5, artificial=1, heat=1, thirst=1)
        for rating in tasting["ratings"]["x"].values():
            rating["scores"].update(integrity=1, harmony=1, coverage=5, potato=1, artificial=5, heat=5, thirst=5)
        chips = {c["id"]: c for c in stats.compute(tasting, self.users)["chips"]}
        self.assertEqual(chips["y"]["alignment"]["name"], "Rechtschaffen Gut")
        self.assertEqual(chips["x"]["alignment"]["name"], "Chaotisch Böse")

    def test_player_alignment_follows_behaviour(self):
        tasting = self.tasting()
        tasting["ratings"]["x"]["c"]["contract"] = True
        tasting["ratings"]["y"]["c"]["contract"] = True
        tasting["ratings"]["z"]["c"]["contract"] = True
        rows = {r["name"]: r for r in stats.compute(tasting, self.users)["player_alignments"]}
        self.assertEqual(rows["C"]["alignment"]["law"], "chaotic")
        self.assertEqual(rows["C"]["alignment"]["good"], "evil")
        self.assertEqual(rows["A"]["alignment"]["law"], "lawful")

    def bought(self):
        """Chips x and y came from A's shopping, z from B's. C set every bowl up."""
        tasting = self.tasting()
        for chip, buyer in zip(tasting["chips"], ("a", "a", "b")):
            chip.update(bought_by=buyer, added_by="c")
        return tasting

    def test_merchants_rank_buyers_by_their_bags(self):
        result = stats.compute(self.bought(), self.users)
        merchants = {m["name"]: m for m in result["merchants"]}
        self.assertAlmostEqual(merchants["A"]["dc"], (41 / 3 + 10) / 2)
        self.assertEqual(self.award(result, "merchant")["winner"], "A")
        self.assertEqual(self.award(result, "mimic")["winner"], "B")

    def test_blind_self_love_and_betrayal(self):
        result = stats.compute(self.bought(), self.users)
        merchants = {m["name"]: m for m in result["merchants"]}
        # A gave x a 20 where the rest averaged 10.5, and y a 10 like everyone.
        self.assertAlmostEqual(merchants["A"]["self_bias"], (9.5 + 0) / 2)
        self.assertEqual(self.award(result, "self_love")["winner"], "A")
        self.assertEqual(self.award(result, "traitor")["winner"], "B")

    def test_setting_up_your_own_bag_is_not_blind(self):
        tasting = self.bought()
        tasting["chips"][0]["added_by"] = "a"
        merchants = {m["name"]: m for m in stats.compute(tasting, self.users)["merchants"]}
        self.assertAlmostEqual(merchants["A"]["self_bias"], 0)
        self.assertNotIn("added_by_id", stats.compute(tasting, self.users)["chips"][0])

    def test_doubles_reward_a_steady_palate(self):
        tasting = self.tasting()
        tasting["chips"][1]["item_id"] = tasting["chips"][2]["item_id"] = "same"
        result = stats.compute(tasting, self.users)
        self.assertEqual([b["bowl"] for b in result["doubles"][0]["bowls"]], [2, 3])
        # A and B gave 10 then 1, C gave 10 then 20.
        self.assertEqual(self.award(result, "elephant")["winner"], "A & B")
        self.assertEqual(self.award(result, "shapeshifter")["winner"], "C")

    def test_nutrition_checks_and_awards(self):
        tasting = self.tasting()
        facts = [{"kcal": 530, "fat": 33, "salt": 1.5, "protein": 6}, {"kcal": 450, "fat": 18, "salt": 1.0, "protein": 13},
                 {"kcal": 500, "fat": 25, "salt": 2.5, "protein": 7}]
        for chip, nutrition in zip(tasting["chips"], facts):
            chip["nutrition"] = nutrition
        for chip_id, salt in (("x", 2), ("y", 1), ("z", 5)):
            for rating in tasting["ratings"][chip_id].values():
                rating["scores"]["salt"] = salt
        result = stats.compute(tasting, self.users)
        checks = {c["key"]: c for c in result["nutrition"]["checks"]}
        self.assertGreater(checks["salt"]["r"], 0.9)
        self.assertIn("genauer", checks["salt"]["line"])
        self.assertEqual(self.award(result, "calorie_bomb")["winner"], "Funny-Frisch X")
        self.assertEqual(self.award(result, "protein")["winner"], "Lorenz Y")
        self.assertEqual(self.award(result, "salt_mine")["winner"], "Pringles Z")

    def test_ingredient_count_ignores_sub_lists(self):
        self.assertEqual(stats.ingredient_count("Kartoffeln, Öl (Sonnenblume, Raps), Gewürze [Paprika, Salz], Salz."), 4)
        self.assertIsNone(stats.ingredient_count(None))

    def test_house_battle_needs_two_bowls_per_brand(self):
        tasting = self.tasting()
        tasting["chips"][1]["brand"] = "funny frisch"
        tasting["chips"][2]["brand"] = "Funny-Frisch"
        self.assertEqual(stats.compute(tasting, self.users)["battles"]["house"], [])
        tasting["chips"].append({**tasting["chips"][1], "id": "w", "bowl": 4, "brand": "Lorenz"})
        tasting["chips"].append({**tasting["chips"][1], "id": "v", "bowl": 5, "brand": "lorenz"})
        tasting["ratings"]["w"] = tasting["ratings"]["v"] = tasting["ratings"]["y"]
        house = stats.compute(tasting, self.users)["battles"]["house"]
        self.assertEqual({row["label"] for row in house}, {"Funny-Frisch", "Lorenz"})

    def test_brand_matching(self):
        self.assertTrue(stats.brand_matches("funny", "Funny-Frisch"))
        self.assertTrue(stats.brand_matches("Lorentz", "Lorenz"))
        self.assertFalse(stats.brand_matches("xy", "Funny-Frisch"))
        self.assertFalse(stats.brand_matches("Pringles", "Lorenz"))
        self.assertFalse(stats.brand_matches("", "Lorenz"))


if __name__ == "__main__":
    unittest.main()
