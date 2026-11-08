"""End-to-end checks of the rules that matter: blindness, security, persistence, stats."""

import io
import json
import os
import re
import tempfile
import unittest

from PIL import Image

from tasting import create_app, security, stats
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
        self.post(admin, "/chips", name="Geheimchip", brand="Funny", flavor_type="Paprika", price="1,99")
        self.post(admin, "/chips", name="Zweitchip", brand="Lorenz", flavor_type="Gesalzen", own_brand="on")
        self.post(admin, "/chips", name="Drittchip", brand="Pringles", flavor_type="BBQ", price="3")
        return admin, self.store.read()["chips"]

    def rate(self, client, chip_id, dc, score=3, **extra):
        fields = {f"score_{k}": str(score) for k in SCALE_KEYS}
        return self.post(client, f"/schale/{chip_id}", dc=str(dc), **fields, **extra)


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
        self.assertEqual(self.store.read()["ratings"][chips[0]["id"]]["a"]["dc"], 10)

    def test_reopen_keeps_ratings(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        self.post(admin, "/admin/ceremony/start")
        self.post(admin, "/admin/ceremony/reopen")
        data = self.store.read()
        self.assertEqual(data["phase"], "tasting")
        self.assertEqual(data["ratings"][chips[0]["id"]]["a"]["dc"], 10)


class Rating(Base):
    def test_incomplete_or_invalid_rating_is_rejected(self):
        _, chips = self.add_chips()
        player = self.client("a")
        chip = chips[0]["id"]
        self.assertEqual(self.post(player, f"/schale/{chip}", dc="10").status_code, 422)
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
            self.post(admin, "/chips", name="x", flavor_type="BBQ", price=bad)
        self.assertEqual(self.store.read()["chips"], [])

    def test_bad_weight_is_rejected(self):
        admin = self.client("admin")
        for bad in ("abc", "nan", "0", "-5", "99999"):
            self.post(admin, "/chips", name="x", flavor_type="BBQ", weight=bad)
        self.assertEqual(self.store.read()["chips"], [])
        self.post(admin, "/chips", name="x", flavor_type="BBQ", price="2", weight="175,5")
        self.assertEqual(self.store.read()["chips"][0]["weight"], 175.5)

    def test_removed_categories_are_gone(self):
        self.assertNotIn("fingers", SCALE_KEYS)
        self.assertNotIn("wisdom", SCALE_KEYS)
        self.assertIn("grease", SCALE_KEYS)

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

    def test_own_chip_price_guess_is_dropped(self):
        alice = self.client("a")
        chip = self.add(alice)
        self.rate(alice, chip["id"], 10, coins="7")
        self.assertIsNone(self.store.read()["ratings"][chip["id"]]["a"]["coins"])

    def test_weight_stays_private_before_reveal(self):
        alice, bob = self.client("a"), self.client("b")
        self.post(alice, "/chips", name="Schwer", flavor_type="BBQ", price="2,50", weight="4242")
        chip = self.store.read()["chips"][0]
        for url in ("/", "/api/progress", f"/schale/{chip['id']}"):
            self.assertNotIn("4242", bob.get(url).get_data(as_text=True), url)


class Shopping(Base):
    def add(self, client, name="Ungarisch", brand="Funny-Frisch", **extra):
        fields = {"name": name, "brand": brand, "flavor_type": "Paprika", "buyer": "me", **extra}
        return self.post(client, "/einkauf", **fields)

    def items(self):
        return self.store.read()["shopping"]

    def test_everyone_sees_the_list(self):
        self.add(self.client("a"))
        for uid in ("b", "admin"):
            body = self.client(uid).get("/einkauf").get_data(as_text=True)
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
        self.assertIn("klingt wie", bob.get("/einkauf").get_data(as_text=True))

    def test_wish_can_be_claimed_once(self):
        self.add(self.client("a"), buyer="open")
        self.post(self.client("b"), f"/einkauf/{self.items()[0]['id']}/claim")
        self.post(self.client("c"), f"/einkauf/{self.items()[0]['id']}/claim")
        self.assertEqual(self.items()[0]["buyer"], "b")

    def test_only_the_buyer_marks_bought_or_releases(self):
        self.add(self.client("a"))
        item = self.items()[0]["id"]
        bob = self.client("b")
        self.assertEqual(self.post(bob, f"/einkauf/{item}/bought").status_code, 403)
        self.assertEqual(self.post(bob, f"/einkauf/{item}/release").status_code, 403)
        self.post(self.client("a"), f"/einkauf/{item}/bought")
        self.assertTrue(self.items()[0]["bought"])

    def test_wisher_cannot_strike_what_someone_else_buys(self):
        alice = self.client("a")
        self.add(alice, buyer="open")
        item = self.items()[0]["id"]
        self.post(self.client("b"), f"/einkauf/{item}/claim")
        self.post(alice, f"/einkauf/{item}/delete")
        self.assertEqual(len(self.items()), 1)
        self.assertEqual(self.post(self.client("c"), f"/einkauf/{item}/delete").status_code, 403)
        self.post(self.client("admin"), f"/einkauf/{item}/delete")
        self.assertEqual(self.items(), [])

    def test_item_becomes_a_bowl_and_stays_blind(self):
        alice, bob = self.client("a"), self.client("b")
        self.add(alice)
        item = self.items()[0]["id"]
        form = alice.get(f"/?from={item}").get_data(as_text=True)
        self.assertIn('value="Ungarisch"', form)
        self.post(alice, "/chips", name="Ungarisch", brand="Funny-Frisch", flavor_type="Paprika",
                  price="2,49", weight="175", item_id=item)
        data = self.store.read()
        chip = data["chips"][0]
        self.assertEqual((chip["added_by"], chip["weight"]), ("a", 175))
        self.assertEqual((data["shopping"][0]["chip_id"], data["shopping"][0]["bought"]), (chip["id"], True))
        self.assertIn("Schale 1", alice.get("/einkauf").get_data(as_text=True))
        self.assertNotIn("Schale 1", bob.get("/einkauf").get_data(as_text=True))
        # A second bowl from the same item is not possible.
        self.assertEqual(self.post(alice, "/chips", name="x", flavor_type="BBQ", item_id=item).status_code, 403)

    def test_others_cannot_set_up_my_item(self):
        self.add(self.client("a"))
        item = self.items()[0]["id"]
        self.assertEqual(self.post(self.client("b"), "/chips", name="x", flavor_type="BBQ", item_id=item).status_code, 403)
        self.assertEqual(self.store.read()["chips"], [])

    def test_deleted_bowl_frees_the_item_again(self):
        alice = self.client("a")
        self.add(alice)
        item = self.items()[0]["id"]
        self.post(alice, "/chips", name="Ungarisch", flavor_type="Paprika", item_id=item)
        self.post(alice, f"/chips/{self.store.read()['chips'][0]['id']}/delete")
        self.assertIn(f"from={item}", alice.get("/").get_data(as_text=True))

    def test_list_locks_with_the_ratings(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        self.post(admin, "/admin/ceremony/start")
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
        self.assertEqual(alice.get("/einkauf").status_code, 200)
        self.assertEqual(alice.get("/einkauf?edit=i1").status_code, 200)
        self.assertEqual(alice.get("/?from=i1").status_code, 200)

    def test_old_files_get_a_list(self):
        path = os.path.join(self.tmp.name, "tasting.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"phase": "tasting", "chips": [], "ratings": {}}, f)
        self.assertEqual(Store(self.tmp.name).read()["shopping"], [])


class ListDetails(Base):
    def test_name_is_optional_when_brand_and_flavor_say_enough(self):
        alice = self.client("a")
        self.post(alice, "/chips", brand="Pringles", flavor_type="Paprika")
        chip = self.store.read()["chips"][0]
        self.assertEqual(stats.chip_label(chip), "Pringles Paprika")
        self.post(alice, "/chips", flavor_type="BBQ")
        self.assertEqual(len(self.store.read()["chips"]), 1)

    def test_complete_item_becomes_a_bowl_in_one_step(self):
        alice = self.client("a")
        self.post(alice, "/einkauf", brand="Pringles", flavor_type="Paprika", price="2,99", weight="165", buyer="me")
        item = self.store.read()["shopping"][0]
        self.post(alice, f"/einkauf/{item['id']}/setup")
        data = self.store.read()
        chip = data["chips"][0]
        self.assertEqual((chip["brand"], chip["flavor_type"], chip["price"], chip["weight"]), ("Pringles", "Paprika", 2.99, 165))
        self.assertEqual(data["shopping"][0]["chip_id"], chip["id"])

    def test_incomplete_item_opens_the_filled_form(self):
        alice = self.client("a")
        self.post(alice, "/einkauf", name="Irgendwas mit Trüffel", buyer="me")
        item = self.store.read()["shopping"][0]
        response = self.post(alice, f"/einkauf/{item['id']}/setup")
        self.assertIn(f"from={item['id']}", response.headers["Location"])
        self.assertEqual(self.store.read()["chips"], [])

    def test_price_on_the_list_stays_with_the_buyer(self):
        alice = self.client("a")
        self.post(alice, "/einkauf", brand="Pringles", flavor_type="Paprika", price="4,27", buyer="me")
        self.assertIn("4,27", alice.get("/einkauf").get_data(as_text=True))
        self.assertNotIn("4,27", self.client("b").get("/einkauf").get_data(as_text=True))

    def test_different_flavors_of_one_brand_are_no_duplicates(self):
        self.post(self.client("a"), "/einkauf", brand="Pringles", flavor_type="Paprika")
        self.post(self.client("b"), "/einkauf", brand="Pringles", flavor_type="Sour Cream & Zwiebel")
        self.post(self.client("c"), "/einkauf", brand="pringles", flavor_type="Paprika")
        self.assertEqual(len(self.store.read()["shopping"]), 2)

    def test_item_can_be_edited_until_it_is_a_bowl(self):
        alice = self.client("a")
        self.post(alice, "/einkauf", brand="Pringles", buyer="me")
        item = self.store.read()["shopping"][0]["id"]
        self.post(alice, f"/einkauf/{item}", brand="Pringles", flavor_type="Paprika", weight="165")
        self.assertEqual(self.store.read()["shopping"][0]["flavor_type"], "Paprika")
        self.assertEqual(self.post(self.client("b"), f"/einkauf/{item}", brand="Gehackt").status_code, 403)
        self.post(alice, f"/einkauf/{item}/setup")
        self.post(alice, f"/einkauf/{item}", brand="Später")
        self.assertEqual(self.store.read()["shopping"][0]["brand"], "Pringles")


class Photos(Base):
    def images(self):
        return sorted(os.listdir(os.path.join(self.tmp.name, "images")))

    def test_photo_is_reencoded_without_exif(self):
        alice = self.client("a")
        exif = Image.Exif()
        exif[0x010F] = "Spionagekamera"  # Make
        response = self.upload(alice, "/chips", data=photo_bytes("JPEG", exif=exif), flavor_type="BBQ", brand="Chio")
        self.assertEqual(response.status_code, 302)
        chip = self.store.read()["chips"][0]
        self.assertEqual(self.images(), [chip["image"]])
        served = alice.get(f"/bild/{chip['image']}")
        self.assertEqual(served.mimetype, "image/jpeg")
        self.assertNotIn(b"Spionagekamera", served.data)
        self.assertFalse(Image.open(io.BytesIO(served.data)).getexif())

    def test_non_images_are_refused(self):
        alice = self.client("a")
        for data in (b"<svg onload=alert(1)>", b"GIF89a" + b"x" * 50, b""):
            self.upload(alice, "/chips", data=data, flavor_type="BBQ", brand="Chio")
        gif = io.BytesIO()
        Image.new("RGB", (5, 5)).save(gif, "GIF")
        self.upload(alice, "/chips", data=gif.getvalue(), flavor_type="BBQ", brand="Chio")
        self.assertEqual(self.store.read()["chips"], [])
        self.assertEqual(self.images(), [])
        # A form sent without choosing a file is fine and just has no photo.
        alice.post("/chips", data={"csrf_token": self.token(alice), "flavor_type": "BBQ", "brand": "Chio",
                                   "image": (io.BytesIO(b""), "")}, content_type="multipart/form-data")
        self.assertEqual([c.get("image") for c in self.store.read()["chips"]], [None])

    def test_oversized_upload_is_rejected_but_photos_pass_the_small_limit(self):
        alice = self.client("a")
        big = photo_bytes("PNG", size=(400, 300))
        self.assertGreater(len(big) + 70000, 64 * 1024)
        response = self.upload(alice, "/chips", data=big + b"\0" * 70000, flavor_type="BBQ", brand="Chio")
        self.assertEqual(response.status_code, 302)
        too_big = b"\0" * (13 * 1024 * 1024)
        self.assertEqual(self.upload(alice, "/chips", data=too_big, flavor_type="BBQ").status_code, 413)

    def test_bowl_photo_is_blind_until_the_reveal(self):
        admin = self.client("admin")
        alice, bob = self.client("a"), self.client("b")
        self.upload(alice, "/chips", flavor_type="BBQ", brand="Chio")
        name = self.store.read()["chips"][0]["image"]
        self.assertEqual(bob.get(f"/bild/{name}").status_code, 404)
        self.assertEqual(admin.get(f"/bild/{name}").status_code, 200)
        self.rate(bob, self.store.read()["chips"][0]["id"], 10)
        self.post(admin, "/admin/ceremony/start")
        self.assertEqual(bob.get(f"/bild/{name}").status_code, 404)
        admin.post("/api/ceremony/next", headers={"X-CSRF-Token": self.token(admin)})
        self.assertEqual(bob.get(f"/bild/{name}").status_code, 200)

    def test_list_photo_is_public_and_moves_to_the_bowl(self):
        alice = self.client("a")
        self.upload(alice, "/einkauf", brand="Pringles", flavor_type="Paprika", buyer="me")
        item = self.store.read()["shopping"][0]
        self.assertEqual(self.client("b").get(f"/bild/{item['image']}").status_code, 200)
        self.post(alice, f"/einkauf/{item['id']}/setup")
        self.assertEqual(self.store.read()["chips"][0]["image"], item["image"])
        # Striking the item keeps the photo, the bowl still uses it.
        self.post(alice, f"/einkauf/{item['id']}/delete")
        self.assertEqual(self.images(), [item["image"]])
        self.assertEqual(self.client("b").get(f"/bild/{item['image']}").status_code, 404)

    def test_replaced_and_deleted_photos_are_removed(self):
        alice = self.client("a")
        self.upload(alice, "/chips", flavor_type="BBQ", brand="Chio")
        chip = self.store.read()["chips"][0]
        self.upload(alice, f"/chips/{chip['id']}", flavor_type="BBQ", brand="Chio")
        new = self.store.read()["chips"][0]["image"]
        self.assertEqual(self.images(), [new])
        self.post(alice, f"/chips/{chip['id']}", flavor_type="BBQ", brand="Chio", remove_image="on")
        self.assertEqual(self.images(), [])

    def test_camera_and_file_buttons_both_work(self):
        alice = self.client("a")
        for files in ([(io.BytesIO(b""), ""), (io.BytesIO(photo_bytes()), "kamera.jpg")],
                      [(io.BytesIO(photo_bytes()), "datei.png"), (io.BytesIO(b""), "")]):
            alice.post("/chips", data={"csrf_token": self.token(alice), "flavor_type": "BBQ", "brand": "Chio",
                                       "image": files}, content_type="multipart/form-data")
        self.assertTrue(all(c["image"] for c in self.store.read()["chips"]))
        self.assertEqual(len(self.images()), 2)

    def test_bad_names_are_not_served(self):
        alice = self.client("a")
        for name in ("../users.json", "secret.key", "abc.jpg"):
            self.assertEqual(alice.get(f"/bild/{name}").status_code, 404)

    def test_failed_upload_leaves_no_file(self):
        admin, chips = self.add_chips()
        self.rate(self.client("a"), chips[0]["id"], 10)
        self.post(admin, "/admin/ceremony/start")
        self.upload(self.client("b"), "/chips", flavor_type="BBQ", brand="Chio")
        self.assertEqual(self.images(), [])


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
        self.assertEqual(rating["dc"], 10)

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

    def test_brand_matching(self):
        self.assertTrue(stats.brand_matches("funny", "Funny-Frisch"))
        self.assertTrue(stats.brand_matches("Lorentz", "Lorenz"))
        self.assertFalse(stats.brand_matches("xy", "Funny-Frisch"))
        self.assertFalse(stats.brand_matches("Pringles", "Lorenz"))
        self.assertFalse(stats.brand_matches("", "Lorenz"))


if __name__ == "__main__":
    unittest.main()
