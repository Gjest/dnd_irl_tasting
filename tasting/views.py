"""All routes. Blindness rule: nothing a player can fetch before the reveal may
contain a chip's name, brand, flavor or anyone else's scores."""

import csv
import io
import json
import random
import secrets
from functools import wraps

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from . import images, security, stats
from .catalog import (
    ADDICTION_TIERS,
    FLAVOR_TYPES,
    MAX_DC,
    MAX_NOTES_LENGTH,
    MAX_SOUL_COINS,
    MAX_WEIGHT_GRAMS,
    MIN_DC,
    POINTS_BRAND,
    POINTS_FLAVOR,
    SCALE_KEYS,
    SCALE_LABELS,
    SECTIONS,
)

bp = Blueprint("main", __name__)

MAX_FIELD_LENGTH = 80
MAX_CHIPS = 60
MAX_SHOPPING_ITEMS = 80
RESET_WORD = "ASCHE"


def store():
    return current_app.extensions["store"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if request.path.startswith("/api/"):
                abort(401)
            return redirect(url_for("main.login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def players():
    return [
        {"id": uid, "name": u["name"]}
        for uid, u in store().users().items()
        if u.get("role") == "player"
    ]


# --- Login ---------------------------------------------------------------


@bp.get("/healthz")
def healthz():
    return "ok"


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("main.home"))
    users = store().users()
    limiter = current_app.extensions["limiter"]
    error = None
    if request.method == "POST":
        uid = request.form.get("user", "")
        attempt = request.form.get("passphrase", "")[:200]
        ip = request.remote_addr or "?"
        if limiter.blocked(ip, uid):
            error = "Zu viele Fehlversuche. Die Höllentore bleiben fünf Minuten verschlossen."
        else:
            user = users.get(uid)
            ok = security.verify_passphrase(user["hash"] if user else security.DUMMY_HASH, attempt)
            if user and ok:
                limiter.clear(ip, uid)
                session.clear()
                session.permanent = True
                session["uid"] = uid
                session["fp"] = user["hash"][-16:]
                return redirect(url_for("main.home"))
            limiter.record_failure(ip, uid)
            error = "Falsche Passphrase. Der Vertrag bleibt ungültig."
    options = sorted(
        ({"id": uid, "name": u["name"]} for uid, u in users.items()),
        key=lambda o: (o["id"] == "admin", o["name"].lower()),
    )
    return render_template("login.html", options=options, error=error), (401 if error else 200)


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


# --- Tasting -------------------------------------------------------------


@bp.get("/")
@login_required
def home():
    tasting = store().read()
    if g.user["role"] == "admin" and tasting["phase"] == "tasting":
        return redirect(url_for("main.admin"))
    if tasting["phase"] == "ceremony":
        return redirect(url_for("main.unsealing"))
    if tasting["phase"] == "revealed":
        return redirect(url_for("main.results"))
    me = g.user["id"]
    my_chips = sorted(
        (c for c in tasting["chips"] if c.get("added_by") == me), key=lambda c: c["bowl"]
    )
    editing = next((c for c in my_chips if c["id"] == request.args.get("edit")), None)
    # Bought or planned items of mine that aren't a bowl yet, ready to be set up.
    to_set_up = [
        {**item, "ready": _ready_for_bowl(item)}
        for item in tasting["shopping"]
        if item.get("buyer") == me and _linked_chip(tasting, item) is None
    ]
    from_item = next((i for i in to_set_up if i["id"] == request.args.get("from")), None)
    return render_template(
        "bowls.html", my_chips=my_chips, editing=editing, flavors=FLAVOR_TYPES,
        to_set_up=to_set_up, from_item=from_item,
    )


@bp.app_template_filter("chip_label")
def chip_label_filter(chip):
    return stats.chip_label(chip)


def _progress(tasting):
    chips = sorted(tasting["chips"], key=lambda c: c["bowl"])
    people = players()
    me = g.user["id"]
    return {
        "phase": tasting["phase"],
        "bowls": [
            {
                "id": chip["id"],
                "bowl": chip["bowl"],
                "mine": me in tasting["ratings"].get(chip["id"], {}),
                "brought": chip.get("added_by") == me,
                "rated": len(tasting["ratings"].get(chip["id"], {})),
            }
            for chip in chips
        ],
        "players": [
            {
                "name": p["name"],
                "missing": [
                    chip["bowl"]
                    for chip in chips
                    if p["id"] not in tasting["ratings"].get(chip["id"], {})
                ],
            }
            for p in people
        ],
    }


@bp.get("/api/progress")
@login_required
def api_progress():
    return jsonify(_progress(store().read()))


def _find_chip(tasting, chip_id):
    for chip in tasting["chips"]:
        if chip["id"] == chip_id:
            return chip
    abort(404)


def _parse_rating(form):
    """Returns (rating, errors). Everything from the form is treated as hostile."""
    errors = []
    scores = {}
    for key in SCALE_KEYS:
        value = form.get(f"score_{key}", "")
        if value in ("1", "2", "3", "4", "5"):
            scores[key] = int(value)
        else:
            errors.append(f"{SCALE_LABELS[key]} fehlt.")
    dc = form.get("dc", "")
    if dc.isdigit() and MIN_DC <= int(dc) <= MAX_DC:
        dc = int(dc)
    else:
        dc = None
        errors.append("Der Sucht-Save fehlt.")

    flavor = form.get("guess_flavor", "")
    flavor = flavor if flavor in FLAVOR_TYPES else None
    coins = form.get("coins", "")
    coins = int(coins) if coins.isdigit() and int(coins) <= MAX_SOUL_COINS else None
    contract = {"yes": True, "no": False}.get(form.get("contract", ""))

    rating = {
        "scores": scores,
        "dc": dc,
        "guess_flavor": flavor,
        "guess_brand": form.get("guess_brand", "").strip()[:MAX_FIELD_LENGTH],
        "coins": coins,
        "contract": contract,
        "notes": form.get("notes", "").strip()[:MAX_NOTES_LENGTH],
    }
    return rating, errors


@bp.route("/schale/<chip_id>", methods=["GET", "POST"])
@login_required
def rate(chip_id):
    if g.user["role"] != "player":
        abort(403)
    tasting = store().read()
    chip = _find_chip(tasting, chip_id)
    me = g.user["id"]
    if tasting["phase"] != "tasting":
        flash("Die Wertung ist versiegelt. Es gibt kein Zurück.")
        return redirect(url_for("main.home"))

    rating = tasting["ratings"].get(chip_id, {}).get(me)
    own_chip = chip if chip.get("added_by") == me else None
    errors = []
    if request.method == "POST":
        submitted, errors = _parse_rating(request.form)
        if own_chip:
            submitted["guess_flavor"] = None
            submitted["guess_brand"] = ""
            submitted["coins"] = None
        if not errors:
            with store().edit() as data:
                if data["phase"] != "tasting":
                    flash("Die Wertung wurde gerade versiegelt.")
                    return redirect(url_for("main.home"))
                _find_chip(data, chip_id)
                data["ratings"].setdefault(chip_id, {})[me] = submitted
            flash(f"Schale {chip['bowl']} ist im Höllenbuch verzeichnet.")
            return redirect(url_for("main.home"))
        rating = submitted

    return render_template(
        "rate.html",
        bowl=chip["bowl"],
        chip_id=chip_id,
        own_chip=own_chip,
        rating=rating or {"scores": {}},
        sections=SECTIONS,
        tiers=ADDICTION_TIERS,
        min_dc=MIN_DC,
        max_dc=MAX_DC,
        flavors=FLAVOR_TYPES,
        max_coins=MAX_SOUL_COINS,
        max_notes=MAX_NOTES_LENGTH,
        points_flavor=POINTS_FLAVOR,
        points_brand=POINTS_BRAND,
        errors=errors,
    ), (422 if errors else 200)


# --- Reveal --------------------------------------------------------------


def _ceremony_payload(tasting):
    order = tasting["ceremony_order"]  # worst first
    users = store().users()
    result = stats.compute(tasting, users) if tasting["reveal_count"] else None
    revealed = []
    if result:
        by_id = {c["id"]: c for c in result["chips"]}
        for index, chip_id in enumerate(order[: tasting["reveal_count"]]):
            chip = by_id.get(chip_id)
            if chip:
                revealed.append({
                    "bowl": chip["bowl"],
                    "label": chip["label"],
                    "flavor_type": chip["flavor_type"],
                    "dc": chip["dc"],
                    "image": chip["image"],
                    "place": len(order) - index,
                })
    return {
        "phase": tasting["phase"],
        "total": len(order),
        "reveal_count": tasting["reveal_count"],
        "revealed": revealed,
    }


@bp.get("/enthuellung")
@login_required
def unsealing():
    tasting = store().read()
    if tasting["phase"] == "tasting":
        return render_template("sealed.html")
    return render_template("unsealing.html")


@bp.get("/api/ceremony")
@login_required
def api_ceremony():
    return jsonify(_ceremony_payload(store().read()))


@bp.post("/api/ceremony/next")
@admin_required
def api_ceremony_next():
    with store().edit() as data:
        if data["phase"] == "ceremony":
            data["reveal_count"] = min(data["reveal_count"] + 1, len(data["ceremony_order"]))
            if data["reveal_count"] == len(data["ceremony_order"]):
                data["phase"] = "revealed"
    return jsonify(_ceremony_payload(store().read()))


@bp.get("/ergebnisse")
@login_required
def results():
    if store().read()["phase"] != "revealed":
        return render_template("sealed.html")
    return render_template("results.html")


@bp.get("/api/results")
@login_required
def api_results():
    tasting = store().read()
    if tasting["phase"] != "revealed":
        abort(403)
    return jsonify(stats.compute(tasting, store().users()))


@bp.get("/urkunde/<key>")
@login_required
def certificate(key):
    tasting = store().read()
    if tasting["phase"] != "revealed":
        return render_template("sealed.html")
    for award in stats.compute(tasting, store().users())["awards"]:
        if award["key"] == key:
            return render_template("certificate.html", award=award)
    abort(404)


# --- Admin ---------------------------------------------------------------


@bp.get("/admin")
@admin_required
def admin():
    tasting = store().read()
    chips = sorted(tasting["chips"], key=lambda c: c["bowl"])
    counts = {c["id"]: len(tasting["ratings"].get(c["id"], {})) for c in chips}
    edit_id = request.args.get("edit")
    editing = next((c for c in chips if c["id"] == edit_id), None)
    return render_template(
        "admin.html",
        tasting=tasting,
        chips=chips,
        counts=counts,
        editing=editing,
        flavors=FLAVOR_TYPES,
        people=players(),
        any_ratings=any(counts.values()),
        adders=_display_names(),
        public_url=current_app.config["PUBLIC_URL"],
    )


def _display_names():
    return {uid: u["name"] for uid, u in store().users().items()}


def _parse_chip(form, require_flavor=True):
    """Bowls need a flavor for the statistics. A list item may still be vague."""
    errors = []
    name = form.get("name", "").strip()[:MAX_FIELD_LENGTH]
    brand = form.get("brand", "").strip()[:MAX_FIELD_LENGTH]
    # "Pringles Paprika" needs no name of its own, so either one is enough.
    if not name and not brand:
        errors.append("Name oder Marke fehlt.")
    flavor = form.get("flavor_type", "")
    if flavor not in FLAVOR_TYPES:
        if require_flavor:
            errors.append("Die Geschmacksrichtung fehlt.")
        flavor = ""
    price = None
    raw_price = form.get("price", "").strip().replace(",", ".")
    if raw_price:
        try:
            price = float(raw_price)
        except ValueError:
            price = -1.0
        # `not (a <= x <= b)` also rejects NaN, which float() happily parses.
        if not (0 <= price <= 1000):
            errors.append("Der Preis ergibt keinen Sinn.")
            price = None
    weight = None
    raw_weight = form.get("weight", "").strip().replace(",", ".")
    if raw_weight:
        try:
            weight = float(raw_weight)
        except ValueError:
            weight = -1.0
        if not (1 <= weight <= MAX_WEIGHT_GRAMS):
            errors.append("Das Gewicht ergibt keinen Sinn.")
            weight = None
    return {
        "name": name,
        "brand": brand,
        "flavor_type": flavor,
        "price": price,
        "weight": weight,
        "own_brand": form.get("own_brand") == "on",
    }, errors


def _is_admin():
    return g.user["role"] == "admin"


def _home_for_user():
    return url_for("main.admin") if _is_admin() else url_for("main.home")


def _require_tasting_phase(data):
    if data["phase"] != "tasting":
        flash("Die Wertung ist versiegelt, das geht gerade nicht.")
        return False
    return True


def _may_change_chips(data):
    """Players only during the tasting. The admin can also tidy up after the reveal."""
    if _is_admin() and data["phase"] == "revealed":
        return True
    return _require_tasting_phase(data)


def _refresh_reveal_order(data):
    # Deleting after the reveal can change the ranking, so the ceremony list follows.
    if data["phase"] == "revealed":
        data["ceremony_order"] = list(reversed(stats.ranked_chip_ids(data)))
        data["reveal_count"] = len(data["ceremony_order"])


# --- Photos --------------------------------------------------------------


def _upload_photo():
    """Saves the form's photo. Returns (name, error)."""
    try:
        return images.save_upload(request.files.get("image"), store().images_dir), None
    except images.ImageError as error:
        return None, str(error)


def _new_photo(entry, uploaded):
    """The photo an edited bowl or item ends up with."""
    if uploaded:
        return uploaded
    if request.form.get("remove_image") == "on":
        return None
    return entry.get("image")


def _photo_visible(tasting, name):
    if any(item.get("image") == name for item in tasting["shopping"]):
        return True  # the list is open to everyone anyway
    revealed = set(tasting["ceremony_order"][: tasting["reveal_count"]])
    for chip in tasting["chips"]:
        if chip.get("image") == name:
            if _is_admin() or chip.get("added_by") == g.user["id"] or tasting["phase"] == "revealed" or chip["id"] in revealed:
                return True
    return False


@bp.get("/bild/<name>")
@login_required
def photo(name):
    # A bowl's photo shows the bag, so before the reveal only its owner gets it.
    if not images.NAME_PATTERN.fullmatch(name) or not _photo_visible(store().read(), name):
        abort(404)
    response = send_from_directory(store().images_dir, name, mimetype="image/jpeg")
    response.headers["Cache-Control"] = "private, no-store"
    return response


# --- Chips ---------------------------------------------------------------


def _place_chip(data, fields, owner, item=None):
    """Adds a bowl and returns its number, or None if the table is full."""
    if len(data["chips"]) >= MAX_CHIPS:
        flash(f"Mehr als {MAX_CHIPS} Schalen überlebt niemand.")
        return None
    bowl = max((c["bowl"] for c in data["chips"]), default=0) + 1
    chip_id = secrets.token_hex(4)
    data["chips"].append({"id": chip_id, "bowl": bowl, "added_by": owner, **fields})
    if item:
        item.update(chip_id=chip_id, bought=True)
    return bowl


@bp.post("/chips")
@login_required
def add_chip():
    fields, errors = _parse_chip(request.form)
    item_id = request.form.get("item_id", "")
    back = url_for("main.home", **{"from": item_id}) if item_id and not _is_admin() else _home_for_user()
    uploaded, photo_error = (None, None) if errors else _upload_photo()
    if errors or photo_error:
        for error in errors or [photo_error]:
            flash(error)
        return redirect(back)
    placed = None
    with store().edit() as data:
        if _require_tasting_phase(data):
            item = None
            if item_id:
                item = _find_item(data, item_id)
                if item.get("buyer") != g.user["id"] or _linked_chip(data, item):
                    abort(403)
            fields["image"] = _new_photo(item or {}, uploaded)
            placed = _place_chip(data, fields, g.user["id"], item)
    if placed:
        flash(f"Deine Chips stehen jetzt in Schale {placed}.")
    else:
        images.discard(store().images_dir, [uploaded], store().read())
    return redirect(_home_for_user())


def _chip_for_change(data, chip_id):
    chip = _find_chip(data, chip_id)
    if not _is_admin() and chip.get("added_by") != g.user["id"]:
        abort(403)
    return chip


@bp.post("/chips/<chip_id>")
@login_required
def update_chip(chip_id):
    fields, errors = _parse_chip(request.form)
    target = "main.admin" if _is_admin() else "main.home"
    uploaded, photo_error = (None, None) if errors else _upload_photo()
    if errors or photo_error:
        for error in errors or [photo_error]:
            flash(error)
        return redirect(url_for(target, edit=chip_id))
    old = uploaded
    with store().edit() as data:
        chip = _chip_for_change(data, chip_id)
        if _may_change_chips(data):
            old = chip.get("image")
            chip.update(fields, image=_new_photo(chip, uploaded))
            flash("Gespeichert.")
    images.discard(store().images_dir, [old], store().read())
    return redirect(_home_for_user())


@bp.post("/chips/<chip_id>/delete")
@login_required
def delete_chip(chip_id):
    if _is_admin():
        store().snapshot()
    removed = None
    with store().edit() as data:
        chip = _chip_for_change(data, chip_id)
        if _may_change_chips(data):
            others = set(data["ratings"].get(chip_id, {})) - {g.user["id"]}
            if others and not _is_admin():
                flash("Andere haben diese Schale schon bewertet. Nur der Admin kann sie noch löschen.")
            else:
                data["chips"].remove(chip)
                data["ratings"].pop(chip_id, None)
                _refresh_reveal_order(data)
                removed = chip.get("image")
                flash(f"Schale {chip['bowl']} wurde den Flammen übergeben.")
    images.discard(store().images_dir, [removed], store().read())
    return redirect(request.form.get("next") == "data" and url_for("main.admin_data") or _home_for_user())


# --- Shopping list -------------------------------------------------------
# Everyone sees what's on the list, who buys it and its photo, which is the
# point: no two people bring the same bag. Price, weight and which bowl an item
# became stay with whoever may edit it and the admin until the reveal, so the
# blind price guess still means something.


def _find_item(data, item_id):
    for item in data["shopping"]:
        if item["id"] == item_id:
            return item
    abort(404)


def _linked_chip(data, item):
    # A deleted bowl leaves the item as if it had never been set up.
    return next((c for c in data["chips"] if c["id"] == item.get("chip_id")), None)


def _ready_for_bowl(item):
    return item.get("flavor_type") in FLAVOR_TYPES and bool(item.get("name") or item.get("brand"))


def _item_key(item):
    return "|".join(stats.normalize_text(item.get(k)) for k in ("brand", "name", "flavor_type"))


def _item_text(item):
    return " ".join(stats.normalize_text(item.get(k)) for k in ("brand", "name", "flavor_type"))


def _duplicate_item(data, fields, skip=None):
    """(exact twin, probable twin) among the other items."""
    others = [i for i in data["shopping"] if i is not skip]
    twin = next((i for i in others if _item_key(i) == _item_key(fields)), None)
    similar = next((i for i in others if stats.similar(_item_text(i), _item_text(fields))), None)
    return twin, similar


def _may_edit_item(item):
    me = g.user["id"]
    return _is_admin() or item.get("buyer") == me or (not item.get("buyer") and item.get("creator") == me)


@bp.get("/einkauf")
@login_required
def shopping():
    tasting = store().read()
    names = _display_names()
    me = g.user["id"]
    revealed = tasting["phase"] == "revealed"
    items = []
    for item in tasting["shopping"]:
        chip = _linked_chip(tasting, item)
        may_edit = _may_edit_item(item)
        may_see_details = revealed or may_edit
        items.append({
            **item,
            "label": stats.chip_label(item),
            "creator_name": names.get(item.get("creator"), "unbekannt"),
            "buyer_name": names.get(item.get("buyer")) if item.get("buyer") else None,
            "bowl": chip["bowl"] if chip and may_see_details else None,
            "set_up": bool(chip) and may_see_details,
            "mine": item.get("buyer") == me,
            "ready": _ready_for_bowl(item),
            "may_edit": may_edit and not chip,
            "may_see_details": may_see_details,
            "price_100g": stats.price_per_100g(item),
            "may_delete": _is_admin() or me in (item.get("creator"), item.get("buyer")),
        })
    groups = [
        ("Sucht noch jemanden", [i for i in items if not i.get("buyer")]),
        ("Wird gekauft", [i for i in items if i.get("buyer") and not i.get("bought")]),
        ("Im Rucksack", [i for i in items if i.get("buyer") and i.get("bought")]),
    ]
    editing = next((i for i in items if i["id"] == request.args.get("edit") and i["may_edit"]), None)
    return render_template(
        "shopping.html", groups=groups, count=len(items), flavors=FLAVOR_TYPES, editing=editing,
        open_phase=tasting["phase"] == "tasting", is_player=g.user["role"] == "player",
    )


@bp.post("/einkauf")
@login_required
def add_item():
    fields, errors = _parse_chip(request.form, require_flavor=False)
    uploaded, photo_error = (None, None) if errors else _upload_photo()
    if errors or photo_error:
        for error in errors or [photo_error]:
            flash(error)
        return redirect(url_for("main.shopping"))
    added = False
    with store().edit() as data:
        if not _require_tasting_phase(data):
            pass
        elif len(data["shopping"]) >= MAX_SHOPPING_ITEMS:
            flash(f"Mehr als {MAX_SHOPPING_ITEMS} Tüten trägt kein Packesel.")
        else:
            twin, similar = _duplicate_item(data, fields)
            if twin:
                flash(f"{stats.chip_label(twin)} steht schon auf der Liste. Doppelt kauft nur ein Mimik.")
            else:
                buyer = g.user["id"] if request.form.get("buyer") == "me" and g.user["role"] == "player" else None
                data["shopping"].append({
                    "id": secrets.token_hex(4),
                    **fields,
                    "image": uploaded,
                    "creator": g.user["id"],
                    "buyer": buyer,
                    "bought": False,
                    "chip_id": None,
                })
                added = True
                if similar:
                    flash(f"Eingetragen. Achtung, das klingt wie {stats.chip_label(similar)}, das schon auf der Liste steht.")
                else:
                    flash("Eingetragen.")
    if not added:
        images.discard(store().images_dir, [uploaded], store().read())
    return redirect(url_for("main.shopping"))


@bp.post("/einkauf/<item_id>")
@login_required
def update_item(item_id):
    fields, errors = _parse_chip(request.form, require_flavor=False)
    uploaded, photo_error = (None, None) if errors else _upload_photo()
    if errors or photo_error:
        for error in errors or [photo_error]:
            flash(error)
        return redirect(url_for("main.shopping", edit=item_id))
    old = uploaded
    with store().edit() as data:
        item = _find_item(data, item_id)
        if not _may_edit_item(item):
            abort(403)
        if not _require_tasting_phase(data):
            pass
        elif _linked_chip(data, item):
            flash("Das steht schon als Schale auf dem Tisch. Ändere es dort.")
        else:
            twin, _ = _duplicate_item(data, fields, skip=item)
            if twin:
                flash(f"{stats.chip_label(twin)} steht schon auf der Liste.")
            else:
                old = item.get("image")
                item.update(fields, image=_new_photo(item, uploaded))
                flash("Gespeichert.")
    images.discard(store().images_dir, [old], store().read())
    return redirect(url_for("main.shopping"))


@bp.post("/einkauf/<item_id>/setup")
@login_required
def set_up_item(item_id):
    """Turns a complete list item into a bowl in one step."""
    with store().edit() as data:
        item = _find_item(data, item_id)
        if item.get("buyer") != g.user["id"] or _linked_chip(data, item):
            abort(403)
        if not _require_tasting_phase(data):
            return redirect(url_for("main.shopping"))
        if not _ready_for_bowl(item):
            # Missing pieces go to the bowl form, already filled in.
            return redirect(url_for("main.home", **{"from": item_id}))
        fields = {k: item.get(k) for k in ("name", "brand", "flavor_type", "price", "weight", "own_brand", "image")}
        placed = _place_chip(data, fields, g.user["id"], item)
    if placed:
        missing = " Preis und Gewicht fehlen noch, du kannst sie unter „Ändern“ nachtragen." if stats.price_per_100g(item) is None else ""
        flash(f"{stats.chip_label(item)} steht jetzt in Schale {placed}.{missing}")
    return redirect(url_for("main.home"))


def _change_item(item_id, change):
    """Runs `change(data, item)` on one item during the tasting, then back to the list."""
    if g.user["role"] != "player" and change is not _delete_item:
        abort(403)
    removed = []
    with store().edit() as data:
        item = _find_item(data, item_id)
        if _require_tasting_phase(data):
            change(data, item)
            if item not in data["shopping"]:
                removed.append(item.get("image"))
    images.discard(store().images_dir, removed, store().read())
    return redirect(url_for("main.shopping"))


def _claim_item(data, item):
    if item.get("buyer"):
        flash("Das kauft schon jemand.")
    else:
        item["buyer"] = g.user["id"]
        flash(f"Du kaufst {stats.chip_label(item)}.")


def _release_item(data, item):
    if item.get("buyer") != g.user["id"]:
        abort(403)
    if _linked_chip(data, item):
        flash("Das steht schon als Schale auf dem Tisch.")
        return
    item.update(buyer=None, bought=False)
    flash("Freigegeben. Jetzt darf jemand anderes.")


def _toggle_bought(data, item):
    if item.get("buyer") != g.user["id"]:
        abort(403)
    if _linked_chip(data, item):
        flash("Das steht schon als Schale auf dem Tisch.")
        return
    item["bought"] = not item.get("bought")


def _delete_item(data, item):
    if not _is_admin() and g.user["id"] not in (item.get("creator"), item.get("buyer")):
        abort(403)
    # Somebody else already promised to buy it, so only they or the admin can drop it.
    if not _is_admin() and item.get("buyer") not in (None, g.user["id"]):
        flash("Das kauft schon jemand anderes. Nur diese Person oder der Admin kann es streichen.")
        return
    data["shopping"].remove(item)
    flash(f"{stats.chip_label(item)} ist von der Liste gestrichen. Die Schale bleibt, falls es eine gibt.")


@bp.post("/einkauf/<item_id>/claim")
@login_required
def claim_item(item_id):
    return _change_item(item_id, _claim_item)


@bp.post("/einkauf/<item_id>/release")
@login_required
def release_item(item_id):
    return _change_item(item_id, _release_item)


@bp.post("/einkauf/<item_id>/bought")
@login_required
def toggle_bought(item_id):
    return _change_item(item_id, _toggle_bought)


@bp.post("/einkauf/<item_id>/delete")
@login_required
def delete_item(item_id):
    return _change_item(item_id, _delete_item)


@bp.post("/admin/shuffle")
@admin_required
def admin_shuffle():
    with store().edit() as data:
        if _require_tasting_phase(data):
            if any(data["ratings"].values()):
                flash("Es gibt schon Wertungen, Mischen würde sie den falschen Schalen zuordnen.")
            else:
                numbers = list(range(1, len(data["chips"]) + 1))
                random.SystemRandom().shuffle(numbers)
                for chip, number in zip(data["chips"], numbers):
                    chip["bowl"] = number
                flash("Die Schalen wurden gemischt.")
    return redirect(url_for("main.admin"))


# --- Data cleanup (admin) -------------------------------------------------


@bp.get("/admin/daten")
@admin_required
def admin_data():
    tasting = store().read()
    names = _display_names()
    chips = [
        {
            **chip,
            "label": stats.chip_label(chip),
            "added_by_name": names.get(chip.get("added_by"), "unbekannt"),
            "entries": sorted(
                (
                    {"id": pid, "name": names.get(pid, pid), **rating}
                    for pid, rating in tasting["ratings"].get(chip["id"], {}).items()
                ),
                key=lambda e: e["name"].lower(),
            ),
        }
        for chip in sorted(tasting["chips"], key=lambda c: c["bowl"])
    ]
    return render_template("admin_data.html", chips=chips, tasting=tasting, confirm_word=RESET_WORD)


@bp.post("/admin/daten/<chip_id>/<player_id>/delete")
@admin_required
def admin_delete_rating(chip_id, player_id):
    store().snapshot()
    with store().edit() as data:
        if _may_change_chips(data):
            ratings = data["ratings"].get(chip_id, {})
            if player_id not in ratings:
                abort(404)
            del ratings[player_id]
            _refresh_reveal_order(data)
            flash("Wertung gelöscht.")
    return redirect(url_for("main.admin_data"))


@bp.post("/admin/daten/<chip_id>/<player_id>/note/delete")
@admin_required
def admin_delete_note(chip_id, player_id):
    store().snapshot()
    with store().edit() as data:
        if _may_change_chips(data):
            rating = data["ratings"].get(chip_id, {}).get(player_id)
            if rating is None:
                abort(404)
            rating["notes"] = ""
            flash("Notiz gelöscht.")
    return redirect(url_for("main.admin_data"))


@bp.post("/admin/reset")
@admin_required
def admin_reset():
    if request.form.get("confirm", "").strip().upper() != RESET_WORD:
        flash(f"Nichts gelöscht. Dafür musst du {RESET_WORD} eintippen.")
        return redirect(url_for("main.admin_data"))
    store().snapshot()
    with store().edit() as data:
        photos = [c.get("image") for c in data["chips"]]
        data.update(chips=[], ratings={}, phase="tasting", ceremony_order=[], reveal_count=0)
    images.discard(store().images_dir, photos, store().read())
    flash("Alles liegt in Asche. Die Einkaufsliste bleibt. Eine Sicherung ist in data/backups.")
    return redirect(url_for("main.admin"))


@bp.post("/admin/ceremony/start")
@admin_required
def admin_start_ceremony():
    with store().edit() as data:
        if data["phase"] == "tasting":
            order = stats.ranked_chip_ids(data)
            if order:
                data["phase"] = "ceremony"
                data["ceremony_order"] = list(reversed(order))
                data["reveal_count"] = 0
            else:
                flash("Noch keine Wertungen. Es gibt nichts zu enthüllen.")
                return redirect(url_for("main.admin"))
    return redirect(url_for("main.unsealing"))


@bp.post("/admin/ceremony/reopen")
@admin_required
def admin_reopen():
    with store().edit() as data:
        data["phase"] = "tasting"
        data["ceremony_order"] = []
        data["reveal_count"] = 0
    flash("Die Wertung ist wieder offen.")
    return redirect(url_for("main.admin"))


@bp.get("/admin/qr.svg")
@admin_required
def admin_qr():
    import segno

    url = current_app.config["PUBLIC_URL"]
    if not url:
        abort(404)
    buffer = io.BytesIO()
    segno.make(url, error="m").save(buffer, kind="svg", scale=8, border=2, dark="#000", light="#fff")
    return Response(buffer.getvalue(), mimetype="image/svg+xml")


@bp.get("/admin/export.json")
@admin_required
def admin_export_json():
    body = json.dumps(store().read(), ensure_ascii=False, indent=2)
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=chips-tasting.json"},
    )


def _csv_safe(value):
    # Spreadsheets run cells starting with these as formulas.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


@bp.get("/admin/export.csv")
@admin_required
def admin_export_csv():
    tasting = store().read()
    users = store().users()
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow(
        ["schale", "chips", "marke", "geschmack", "eigenmarke", "preis", "gewicht_g", "preis_100g", "mitgebracht_von", "wer", "sucht_dc"]
        + SCALE_KEYS
        + ["preis_schaetzung_muenzen", "vertrag", "tipp_geschmack", "tipp_marke", "orakelpunkte", "notizen"]
    )
    for chip in sorted(tasting["chips"], key=lambda c: c["bowl"]):
        for pid, r in tasting["ratings"].get(chip["id"], {}).items():
            row = [
                chip["bowl"], chip["name"], chip.get("brand"), chip.get("flavor_type"),
                bool(chip.get("own_brand")), chip.get("price"), chip.get("weight"), stats.price_per_100g(chip),
                users.get(chip.get("added_by"), {}).get("name", ""),
                users.get(pid, {}).get("name", pid), r["dc"],
            ]
            row += [r["scores"].get(k) for k in SCALE_KEYS]
            row += [
                r.get("coins"), r.get("contract"), r.get("guess_flavor"),
                r.get("guess_brand"), stats.guess_points(r, chip, pid), r.get("notes"),
            ]
            writer.writerow([_csv_safe(cell) for cell in row])
    # The BOM makes Excel read umlauts correctly.
    return Response(
        "﻿" + out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=chips-tasting.csv"},
    )


@bp.app_errorhandler(400)
@bp.app_errorhandler(403)
@bp.app_errorhandler(404)
@bp.app_errorhandler(413)
def handle_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": error.code}), error.code
    return render_template("error.html", code=error.code), error.code
