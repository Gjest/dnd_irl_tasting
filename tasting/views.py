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
    session,
    url_for,
)

from . import security, stats
from .catalog import (
    FLAVOR_TYPES,
    MAX_NOTES_LENGTH,
    MAX_SOUL_COINS,
    NPCS,
    POINTS_BRAND,
    POINTS_FLAVOR,
    SCALE_KEYS,
    SCALE_LABELS,
    SECTIONS,
)

bp = Blueprint("main", __name__)

MAX_FIELD_LENGTH = 80
MAX_CHIPS = 60
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
    return render_template("bowls.html", my_chips=my_chips, editing=editing, flavors=FLAVOR_TYPES)


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
    enjoyment = form.get("enjoyment", "")
    if enjoyment.isdigit() and 1 <= int(enjoyment) <= 20:
        enjoyment = int(enjoyment)
    else:
        enjoyment = None
        errors.append("Der Genuss-Wurf fehlt.")

    npc = form.get("npc", "")
    npc = npc if npc in NPCS else None
    flavor = form.get("guess_flavor", "")
    flavor = flavor if flavor in FLAVOR_TYPES else None
    coins = form.get("coins", "")
    coins = int(coins) if coins.isdigit() and int(coins) <= MAX_SOUL_COINS else None
    contract = {"yes": True, "no": False}.get(form.get("contract", ""))

    rating = {
        "scores": scores,
        "enjoyment": enjoyment,
        "npc": npc,
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
        npcs=NPCS,
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
                    "enjoyment": chip["enjoyment"],
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


def _parse_chip(form):
    errors = []
    name = form.get("name", "").strip()[:MAX_FIELD_LENGTH]
    if not name:
        errors.append("Ein Name fehlt.")
    brand = form.get("brand", "").strip()[:MAX_FIELD_LENGTH]
    flavor = form.get("flavor_type", "")
    if flavor not in FLAVOR_TYPES:
        errors.append("Die Geschmacksrichtung fehlt.")
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
    return {
        "name": name,
        "brand": brand,
        "flavor_type": flavor,
        "price": price,
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


@bp.post("/chips")
@login_required
def add_chip():
    fields, errors = _parse_chip(request.form)
    if errors:
        for error in errors:
            flash(error)
        return redirect(_home_for_user())
    with store().edit() as data:
        if _require_tasting_phase(data):
            if len(data["chips"]) >= MAX_CHIPS:
                flash(f"Mehr als {MAX_CHIPS} Schalen überlebt niemand.")
            else:
                bowl = max((c["bowl"] for c in data["chips"]), default=0) + 1
                data["chips"].append(
                    {"id": secrets.token_hex(4), "bowl": bowl, "added_by": g.user["id"], **fields}
                )
                flash(f"Deine Chips stehen jetzt in Schale {bowl}.")
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
    if errors:
        for error in errors:
            flash(error)
        return redirect(url_for(target, edit=chip_id))
    with store().edit() as data:
        chip = _chip_for_change(data, chip_id)
        if _may_change_chips(data):
            chip.update(fields)
            flash("Gespeichert.")
    return redirect(_home_for_user())


@bp.post("/chips/<chip_id>/delete")
@login_required
def delete_chip(chip_id):
    if _is_admin():
        store().snapshot()
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
                flash(f"Schale {chip['bowl']} wurde den Flammen übergeben.")
    return redirect(request.form.get("next") == "data" and url_for("main.admin_data") or _home_for_user())


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
        data.update(chips=[], ratings={}, phase="tasting", ceremony_order=[], reveal_count=0)
    flash("Alles liegt in Asche. Eine Sicherung ist in data/backups.")
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
        ["schale", "chips", "marke", "geschmack", "eigenmarke", "preis", "mitgebracht_von", "wer", "genuss_d20"]
        + SCALE_KEYS
        + ["npc", "seelenmuenzen", "vertrag", "tipp_geschmack", "tipp_marke", "orakelpunkte", "notizen"]
    )
    for chip in sorted(tasting["chips"], key=lambda c: c["bowl"]):
        for pid, r in tasting["ratings"].get(chip["id"], {}).items():
            row = [
                chip["bowl"], chip["name"], chip.get("brand"), chip.get("flavor_type"),
                bool(chip.get("own_brand")), chip.get("price"),
                users.get(chip.get("added_by"), {}).get("name", ""),
                users.get(pid, {}).get("name", pid), r["enjoyment"],
            ]
            row += [r["scores"].get(k) for k in SCALE_KEYS]
            row += [
                r.get("npc"), r.get("coins"), r.get("contract"), r.get("guess_flavor"),
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
