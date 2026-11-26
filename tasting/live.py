"""Running tastings started from a plan: shopping, blind containers, rating, reveal, results.

The flow is the one the chips tasting proved (views.py), without its chips
content: items are free text, the containers are whatever the plan calls
them (Schale, Glas, Becher …), the questions come from the plan, and the
results page is the data-driven one of the finished tastings (archive.py).

The plan entry in data/plans.json keeps the name, look, container word and
participants, so the admin can still change those. Everything the tasting
collects lives in data/live-<slug>.json, together with a frozen copy of the
questions: ratings are keyed by them, so they never change once it runs.

    {"format": "live-tasting/1", "slug", "started", "phase": "tasting" | "ceremony" | "revealed",
     "ceremony_order": [vessel ids, worst first], "reveal_count",
     "scale", "sections", "ranking",
     "items":   [{id, name, brand, note, price, amount, unit, image, creator, buyer, bought}],
     "vessels": [{id, number, item_id, added_by, bought_by, image}],
     "ratings": {vessel_id: {uid: {"scores": {key: int}, "texts": {key: str}, "notes": str}}}}

Only participants (set in /verwaltung, the admin too if entered) shop, set
up and rate. Everyone logged in can read.
"""

import json
import random
import re
import secrets
import shutil
from datetime import date

from flask import (Blueprint, Response, abort, flash, g, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)

from . import archive, images, plans
from .web import admin_required, login_required, store

bp = Blueprint("live", __name__, url_prefix="/live/<slug>")

FORMAT = "live-tasting/1"
MAX_ITEMS = 120
MAX_VESSELS = 120
MAX_FIELD = 80
MAX_NOTE = 120
MAX_TEXT_ANSWER = 500
MAX_NOTES = 1000
MAX_AMOUNT = 100_000
UNITS = ("g", "ml")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")


# --- Data ------------------------------------------------------------------


def _document(slug):
    return store().document(f"live-{slug}")


def images_dir(slug):
    # Each tasting keeps its photos apart, so no other tasting's cleanup can touch them.
    return store().images_dir / f"live-{slug}"


def create(plan):
    """The running tasting's own file, with the plan's questions frozen in."""
    _document(plan["slug"]).replace({
        "format": FORMAT,
        "slug": plan["slug"],
        "started": date.today().isoformat(),
        "phase": "tasting",
        "ceremony_order": [],
        "reveal_count": 0,
        "scale": dict(plan["scale"]),
        "sections": json.loads(json.dumps(plan["sections"])),
        "ranking": plans.ranking_key(plan),
        "items": [],
        "vessels": [],
        "ratings": {},
    })


def remove(slug):
    """Deletes a running tasting with its data and photos. A backup stays in data/backups."""
    document = _document(slug)
    if document.exists():
        document.snapshot()
        document.path.unlink(missing_ok=True)
    store().forget(f"live-{slug}")
    shutil.rmtree(images_dir(slug), ignore_errors=True)


def _load(slug):
    """(plan, data) of a running tasting, or 404."""
    if not NAME.fullmatch(slug):
        abort(404)
    plan = next((p for p in plans.document().read()["plans"] if p["slug"] == slug), None)
    if plan is None or plans.state(plan) == "planned" or not _document(slug).exists():
        abort(404)
    return plan, _document(slug).read()


def running():
    """Every running or finished tasting, for the start page."""
    shown = []
    for plan in plans.document().read()["plans"]:
        if plans.state(plan) != "planned" and _document(plan["slug"]).exists():
            shown.append((plan, _document(plan["slug"]).read()))
    return shown


def item_label(item):
    return " ".join(part for part in (item.get("brand"), item.get("name")) if part) or "Ohne Namen"


def price_per_100(item):
    if item.get("price") is None or not item.get("amount"):
        return None
    return round(item["price"] / item["amount"] * 100, 2)


def _questions(data):
    return [c for section in data["sections"] for c in section["criteria"]]


def _participants(plan):
    users = store().users()
    return [{"id": uid, "name": users[uid]["name"]} for uid in plan.get("participants", [])
            if uid in users and users[uid].get("active", True)]


def _takes_part(plan):
    return g.user["id"] in plan.get("participants", [])


def _is_admin():
    return g.user["role"] == "admin"


def _names():
    return {uid: u["name"] for uid, u in store().users().items()}


# --- Tiles and archive -----------------------------------------------------


STATUS = {"tasting": "Läuft", "ceremony": "Enthüllung", "revealed": "Enthüllt"}


def _ranked_ids(data, users):
    """Vessel ids, best first, from the same numbers the results page shows."""
    entry = to_archive(data, users)
    if archive.validate(entry) is not None:
        return []
    return [row["id"] for row in archive.compute(entry)["ranking"]]


def tiles():
    users = store().users()
    shown = []
    for plan, data in running():
        word = plans.vessel(plan)
        winner = None
        if data["phase"] == "revealed":
            ranked = _ranked_ids(data, users)
            winner = next((_vessel_name(data, v) for v in data["vessels"] if ranked and v["id"] == ranked[0]), None)
        facts = [f"{len(data['vessels'])} {word['many'] if len(data['vessels']) != 1 else word['one']}",
                 f"{len(data['items'])} auf der Einkaufsliste"]
        shown.append({
            "slug": plan["slug"], "kind": "custom", "title": plan["title"], "short": plan.get("short") or plan["title"],
            "tagline": plan.get("tagline", ""), "icon": plan.get("icon", "✨"), "number": None,
            "status": STATUS[data["phase"]], "live": data["phase"] != "revealed", "facts": facts,
            "winner": winner, "date": data.get("started"), "href": url_for("live.home", slug=plan["slug"]),
        })
    return shown


def _vessel_name(data, vessel):
    item = next((i for i in data["items"] if i["id"] == vessel.get("item_id")), None)
    return item_label(vessel.get("snapshot") or item or {})


def to_archive(data, users, plan=None):
    """The tasting as a results file (tasting-archive/1), as cola and water have one."""
    scale_sections = []
    for section in data["sections"]:
        criteria = [{k: c[k] for k in ("key", "label", "low", "high") if k in c}
                    for c in section["criteria"] if c.get("type", "scale") == "scale"]
        if criteria:
            scale_sections.append({"title": section["title"], "criteria": criteria})
    text_labels = {c["key"]: c["label"] for c in _questions(data) if c.get("type") == "text"}
    names = {uid: u["name"] for uid, u in users.items()}
    items, ratings = [], []
    for vessel in sorted(data["vessels"], key=lambda v: v["number"]):
        source = vessel.get("snapshot", {})
        name = item_label(source)
        if source.get("note"):
            name = f"{name} ({source['note']})"
        entry = {"id": vessel["id"], "name": name, "number": vessel["number"]}
        if price_per_100(source) is not None:
            entry["price_per_100"] = price_per_100(source)
            entry["unit"] = source.get("unit", "g")
        items.append(entry)
        for uid, rating in data["ratings"].get(vessel["id"], {}).items():
            texts = [f"{text_labels[k]}: {v}" for k, v in rating.get("texts", {}).items() if v and k in text_labels]
            notes = " · ".join(texts + ([rating["notes"]] if rating.get("notes") else []))
            ratings.append({"person": names.get(uid, "Unbekannt"), "item": vessel["id"],
                            "scores": dict(rating["scores"]), **({"notes": notes} if notes else {})})
    entry = {
        "format": archive.FORMAT,
        "id": data["slug"],
        "title": plan["title"] if plan else data["slug"],
        "date": data.get("started"),
        "scale": data["scale"],
        "ranking": data["ranking"],
        "sections": scale_sections,
        "items": items,
        "ratings": ratings,
    }
    if plan and plan.get("tagline"):
        entry["subtitle"] = plan["tagline"]
    return entry


# --- Page helpers ----------------------------------------------------------


@bp.url_value_preprocessor
def _pull_slug(endpoint, values):
    g.live_slug = values.pop("slug")


@bp.url_defaults
def _add_slug(endpoint, values):
    if "slug" not in values and g.get("live_slug"):
        values["slug"] = g.live_slug


def _page(template, plan, data, **context):
    return render_template(template, plan=plan, data=data, word=plans.vessel(plan),
                           takes_part=_takes_part(plan), **context)


def _require_tasting(data):
    if data["phase"] != "tasting":
        flash("Die Wertung ist versiegelt. Es gibt kein Zurück.")
        return False
    return True


def _require_participant(plan):
    if not _takes_part(plan):
        abort(403)


def _edit():
    """The tasting's data inside an edit (404 if it is gone)."""
    _load(g.live_slug)
    return _document(g.live_slug).edit()


def _find(entries, entry_id):
    entry = next((e for e in entries if e["id"] == entry_id), None)
    if entry is None:
        abort(404)
    return entry


# --- The table during the tasting ----------------------------------------------


@bp.get("/")
@login_required
def home():
    plan, data = _load(g.live_slug)
    if data["phase"] == "ceremony":
        return _page("live_ceremony.html", plan, data)
    if data["phase"] == "revealed":
        return redirect(url_for("live.results"))
    me = g.user["id"]
    mine = sorted((v for v in data["vessels"] if v.get("added_by") == me), key=lambda v: v["number"])
    return _page("live_home.html", plan, data, mine=[{**v, "label": _vessel_name(data, v)} for v in mine])


@bp.get("/api/progress")
@login_required
def api_progress():
    plan, data = _load(g.live_slug)
    vessels = sorted(data["vessels"], key=lambda v: v["number"])
    me = g.user["id"]
    return jsonify({
        "phase": data["phase"],
        "bowls": [{"id": v["id"], "bowl": v["number"], "mine": me in data["ratings"].get(v["id"], {}),
                   "brought": v.get("added_by") == me, "rated": len(data["ratings"].get(v["id"], {}))}
                  for v in vessels],
        "players": [{"name": p["name"], "missing": [v["number"] for v in vessels
                                                    if p["id"] not in data["ratings"].get(v["id"], {})]}
                    for p in _participants(plan)],
    })


def _parse_rating(data, form):
    """(rating, errors). Every scale question is required; text answers and notes are optional."""
    low, high = data["scale"]["min"], data["scale"]["max"]
    scores, texts, errors = {}, {}, []
    for question in _questions(data):
        key = question["key"]
        if question.get("type") == "text":
            answer = form.get(f"text_{key}", "").strip()[:MAX_TEXT_ANSWER]
            if answer:
                texts[key] = answer
            continue
        value = form.get(f"score_{key}", "")
        if value.lstrip("-").isdigit() and low <= int(value) <= high:
            scores[key] = int(value)
        else:
            errors.append(f"„{question['label']}“ fehlt.")
    return {"scores": scores, "texts": texts, "notes": form.get("notes", "").strip()[:MAX_NOTES]}, errors


@bp.route("/gefaess/<vessel_id>", methods=["GET", "POST"])
@login_required
def rate(vessel_id):
    plan, data = _load(g.live_slug)
    _require_participant(plan)
    vessel = _find(data["vessels"], vessel_id)
    word = plans.vessel(plan)
    if not _require_tasting(data):
        return redirect(url_for("live.home"))
    me = g.user["id"]
    rating = data["ratings"].get(vessel_id, {}).get(me)
    errors = []
    if request.method == "POST":
        submitted, errors = _parse_rating(data, request.form)
        if not errors:
            with _edit() as live:
                if live["phase"] != "tasting":
                    flash("Die Wertung wurde gerade versiegelt.")
                    return redirect(url_for("live.home"))
                _find(live["vessels"], vessel_id)
                live["ratings"].setdefault(vessel_id, {})[me] = submitted
            flash(f"{word['one']} {vessel['number']} ist bewertet.")
            return redirect(url_for("live.home"))
        rating = submitted
    own = vessel.get("added_by") == me
    return _page("live_rate.html", plan, data, vessel=vessel, own_label=_vessel_name(data, vessel) if own else None,
                 rating=rating or {"scores": {}, "texts": {}}, errors=errors,
                 scale=range(data["scale"]["min"], data["scale"]["max"] + 1),
                 max_text=MAX_TEXT_ANSWER, max_notes=MAX_NOTES), (422 if errors else 200)


@bp.post("/gefaess/<vessel_id>/loeschen")
@login_required
def delete_vessel(vessel_id):
    plan, data = _load(g.live_slug)
    word = plans.vessel(plan)
    with _edit() as live:
        vessel = _find(live["vessels"], vessel_id)
        if not _is_admin() and vessel.get("added_by") != g.user["id"]:
            abort(403)
        if _require_tasting(live):
            live["vessels"].remove(vessel)
            live["ratings"].pop(vessel_id, None)
            flash(f"{word['one']} {vessel['number']} ist abgeräumt, mit ihren Wertungen.")
    return redirect(url_for("live.home"))


# --- Shopping list -----------------------------------------------------------


def _number(raw, low, high, what):
    raw = (raw or "").strip().replace(",", ".")
    if not raw:
        return None, None
    try:
        value = float(raw)
    except ValueError:
        value = None
    # `not (a <= x <= b)` also rejects NaN, which float() happily parses.
    if value is None or not (low <= value <= high):
        return None, f"{what} ergibt keinen Sinn."
    return value, None


def _parse_item(form):
    errors = []
    name = form.get("name", "").strip()[:MAX_FIELD]
    if not name:
        errors.append("Der Name fehlt.")
    price, error = _number(form.get("price"), 0, 1000, "Der Preis")
    errors += [error] if error else []
    amount, error = _number(form.get("amount"), 1, MAX_AMOUNT, "Die Menge")
    errors += [error] if error else []
    unit = form.get("unit") if form.get("unit") in UNITS else "g"
    return {
        "name": name,
        "brand": form.get("brand", "").strip()[:MAX_FIELD],
        "note": form.get("note", "").strip()[:MAX_NOTE],
        "price": price,
        "amount": amount,
        "unit": unit,
    }, errors


def _key(item):
    return (item["name"].casefold(), item.get("brand", "").casefold())


def _may_edit_item(item):
    me = g.user["id"]
    return _is_admin() or item.get("buyer") == me or (not item.get("buyer") and item.get("creator") == me)


def _upload(slug):
    directory = images_dir(slug)
    directory.mkdir(parents=True, exist_ok=True)
    return images.save_from_form(request.files, directory)


def _discard(names):
    """Deletes photos nobody in this tasting points to any more."""
    data = _document(g.live_slug).read()
    used = {e.get("image") for e in data["items"] + data["vessels"]}
    for name in names:
        if name and name not in used and images.NAME_PATTERN.fullmatch(name):
            (images_dir(g.live_slug) / name).unlink(missing_ok=True)


@bp.get("/einkauf")
@login_required
def shopping():
    plan, data = _load(g.live_slug)
    names = _names()
    me = g.user["id"]
    revealed = data["phase"] == "revealed"
    shown = []
    for item in data["items"]:
        numbers = sorted(v["number"] for v in data["vessels"] if v.get("item_id") == item["id"])
        shown.append({
            **item,
            "label": item_label(item),
            "creator_name": names.get(item.get("creator"), "unbekannt"),
            "buyer_name": names.get(item.get("buyer")) if item.get("buyer") else None,
            # Not even the buyer learns which containers came out of their purchase.
            "numbers": numbers if revealed or _is_admin() else [],
            "mine": item.get("buyer") == me,
            "may_edit": _may_edit_item(item),
            "may_see_price": revealed or _may_edit_item(item),
            "per_100": price_per_100(item),
            "may_delete": _is_admin() or me in (item.get("creator"), item.get("buyer")),
        })
    groups = [
        ("Sucht noch jemanden", [i for i in shown if not i.get("buyer")]),
        ("Wird gekauft", [i for i in shown if i.get("buyer") and not i.get("bought")]),
        ("Ist da", [i for i in shown if i.get("buyer") and i.get("bought")]),
    ]
    editing = next((i for i in shown if i["id"] == request.args.get("edit") and i["may_edit"]), None)
    return _page("live_shopping.html", plan, data, groups=groups, count=len(shown), editing=editing,
                 open_phase=data["phase"] == "tasting", units=UNITS, max_field=MAX_FIELD, max_note=MAX_NOTE)


@bp.post("/einkauf")
@login_required
def add_item():
    plan, _ = _load(g.live_slug)
    _require_participant(plan)
    fields, errors = _parse_item(request.form)
    uploaded, photo_error = (None, None) if errors else _upload(g.live_slug)
    if errors or photo_error:
        for error in errors or [photo_error]:
            flash(error)
        return redirect(url_for("live.shopping"))
    added = False
    with _edit() as data:
        if not _require_tasting(data):
            pass
        elif len(data["items"]) >= MAX_ITEMS:
            flash(f"Mehr als {MAX_ITEMS} Einträge passen nicht auf die Liste.")
        elif any(_key(i) == _key(fields) for i in data["items"]):
            flash(f"{item_label(fields)} steht schon auf der Liste.")
        else:
            data["items"].append({
                "id": secrets.token_hex(4), **fields, "image": uploaded, "creator": g.user["id"],
                "buyer": g.user["id"] if request.form.get("buyer") == "me" else None, "bought": False,
            })
            added = True
            flash("Eingetragen.")
    if not added:
        _discard([uploaded])
    return redirect(url_for("live.shopping"))


@bp.post("/einkauf/<item_id>")
@login_required
def update_item(item_id):
    plan, _ = _load(g.live_slug)
    _require_participant(plan)
    fields, errors = _parse_item(request.form)
    uploaded, photo_error = (None, None) if errors else _upload(g.live_slug)
    if errors or photo_error:
        for error in errors or [photo_error]:
            flash(error)
        return redirect(url_for("live.shopping", edit=item_id))
    old = uploaded
    with _edit() as data:
        item = _find(data["items"], item_id)
        if not _may_edit_item(item):
            abort(403)
        if _require_tasting(data):
            if any(_key(i) == _key(fields) for i in data["items"] if i is not item):
                flash(f"{item_label(fields)} steht schon auf der Liste.")
            else:
                old = item.get("image")
                photo = uploaded or (None if request.form.get("remove_image") == "on" else item.get("image"))
                item.update(fields, image=photo)
                flash("Gespeichert.")
    _discard([old])
    return redirect(url_for("live.shopping"))


def _change_item(item_id, change):
    """Runs `change(data, item)` on one list entry during the tasting, then back to the list."""
    plan, _ = _load(g.live_slug)
    _require_participant(plan)
    removed = []
    with _edit() as data:
        item = _find(data["items"], item_id)
        if _require_tasting(data):
            change(data, item)
            if item not in data["items"]:
                removed.append(item.get("image"))
    _discard(removed)
    return redirect(url_for("live.shopping"))


def _claim(data, item):
    if item.get("buyer"):
        flash("Das kauft schon jemand.")
    else:
        item["buyer"] = g.user["id"]
        flash(f"Du kaufst {item_label(item)}.")


def _release(data, item):
    if item.get("buyer") != g.user["id"]:
        abort(403)
    item.update(buyer=None, bought=False)
    flash("Freigegeben. Jetzt darf jemand anderes.")


def _toggle_bought(data, item):
    if item.get("buyer") != g.user["id"]:
        abort(403)
    item["bought"] = not item.get("bought")


def _delete(data, item):
    if not _is_admin() and g.user["id"] not in (item.get("creator"), item.get("buyer")):
        abort(403)
    if not _is_admin() and item.get("buyer") not in (None, g.user["id"]):
        flash("Das kauft schon jemand anderes. Nur diese Person oder der Admin kann es streichen.")
        return
    data["items"].remove(item)
    flash(f"{item_label(item)} ist gestrichen. Aufgestelltes bleibt stehen.")


@bp.post("/einkauf/<item_id>/kaufen")
@login_required
def claim_item(item_id):
    return _change_item(item_id, _claim)


@bp.post("/einkauf/<item_id>/abgeben")
@login_required
def release_item(item_id):
    return _change_item(item_id, _release)


@bp.post("/einkauf/<item_id>/gekauft")
@login_required
def toggle_bought(item_id):
    return _change_item(item_id, _toggle_bought)


@bp.post("/einkauf/<item_id>/streichen")
@login_required
def delete_item(item_id):
    return _change_item(item_id, _delete)


@bp.post("/einkauf/<item_id>/aufstellen")
@login_required
def set_up(item_id):
    """Turns a list entry into a numbered container. Anyone taking part may, as often as they like."""
    plan, _ = _load(g.live_slug)
    _require_participant(plan)
    word = plans.vessel(plan)
    number = None
    with _edit() as data:
        item = _find(data["items"], item_id)
        if not _require_tasting(data):
            return redirect(url_for("live.shopping"))
        if len(data["vessels"]) >= MAX_VESSELS:
            flash(f"Mehr als {MAX_VESSELS} {word['many']} passen nicht auf den Tisch.")
            return redirect(url_for("live.shopping"))
        number = max((v["number"] for v in data["vessels"]), default=0) + 1
        data["vessels"].append({
            "id": secrets.token_hex(4),
            "number": number,
            "item_id": item["id"],
            # What was in it when it was set up, so editing or striking the entry later changes nothing.
            "snapshot": {k: item.get(k) for k in ("name", "brand", "note", "price", "amount", "unit")},
            "image": item.get("image"),
            "added_by": g.user["id"],  # knows what is in it
            "bought_by": item.get("buyer") or item.get("creator"),  # stays as blind as everyone else
        })
    flash(f"{item_label(item)} steht jetzt als {word['one']} {number} auf dem Tisch.")
    return redirect(url_for("live.home"))


# --- Photos ------------------------------------------------------------------------


def _photo_visible(data, name):
    if any(item.get("image") == name for item in data["items"]):
        return True  # the list is open to everyone anyway
    revealed = set(data["ceremony_order"][: data["reveal_count"]])
    for vessel in data["vessels"]:
        if vessel.get("image") == name and (
                _is_admin() or vessel.get("added_by") == g.user["id"] or data["phase"] == "revealed"
                or vessel["id"] in revealed):
            return True
    return False


@bp.get("/bild/<name>")
@login_required
def photo(name):
    _, data = _load(g.live_slug)
    if not images.NAME_PATTERN.fullmatch(name) or not _photo_visible(data, name):
        abort(404)
    response = send_from_directory(images_dir(g.live_slug), name, mimetype="image/jpeg")
    response.headers["Cache-Control"] = "private, no-store"
    return response


# --- Reveal and results --------------------------------------------------------------


def _ceremony(plan, data):
    users = store().users()
    order = data["ceremony_order"]
    revealed = []
    if data["reveal_count"]:
        computed = archive.compute(to_archive(data, users, plan))
        rows = {row["id"]: row for row in computed["ranking"]}
        word = plans.vessel(plan)
        for index, vessel_id in enumerate(order[: data["reveal_count"]]):
            vessel = next((v for v in data["vessels"] if v["id"] == vessel_id), None)
            row = rows.get(vessel_id)
            if vessel and row:
                note = (vessel.get("snapshot") or {}).get("note")
                revealed.append({
                    "bowl": vessel["number"],
                    "label": item_label(vessel.get("snapshot") or {}),
                    "meta": " · ".join(filter(None, [f"{word['one']} {vessel['number']}", note])),
                    "score": f"Ø {archive.de(row['value'])}",
                    "image": vessel.get("image"),
                    "place": len(order) - index,
                })
    return {"phase": data["phase"], "total": len(order), "reveal_count": data["reveal_count"], "revealed": revealed}


@bp.get("/api/ceremony")
@login_required
def api_ceremony():
    plan, data = _load(g.live_slug)
    return jsonify(_ceremony(plan, data))


@bp.post("/api/ceremony/next")
@admin_required
def api_ceremony_next():
    plan, _ = _load(g.live_slug)
    with _edit() as data:
        if data["phase"] == "ceremony":
            data["reveal_count"] = min(data["reveal_count"] + 1, len(data["ceremony_order"]))
            if data["reveal_count"] == len(data["ceremony_order"]):
                data["phase"] = "revealed"
    return jsonify(_ceremony(plan, _document(g.live_slug).read()))


@bp.get("/ergebnisse")
@login_required
def results():
    plan, data = _load(g.live_slug)
    if data["phase"] != "revealed":
        return _page("live_sealed.html", plan, data)
    return _page("live_results.html", plan, data)


@bp.get("/api/ergebnisse")
@login_required
def api_results():
    plan, data = _load(g.live_slug)
    if data["phase"] != "revealed":
        abort(403)
    return jsonify(archive.compute(to_archive(data, store().users(), plan)))


# --- Admin -----------------------------------------------------------------------------


@bp.get("/admin")
@admin_required
def admin():
    plan, data = _load(g.live_slug)
    names = _names()
    vessels = [{**v, "label": _vessel_name(data, v), "added_name": names.get(v.get("added_by"), "unbekannt"),
                "ratings": len(data["ratings"].get(v["id"], {}))}
               for v in sorted(data["vessels"], key=lambda v: v["number"])]
    ratings = sum(len(r) for r in data["ratings"].values())
    return _page("live_admin.html", plan, data, vessels=vessels, ratings=ratings, vessel_words=plans.VESSELS,
                 participants=_participants(plan), status=STATUS[data["phase"]])


@bp.post("/admin/mischen")
@admin_required
def shuffle():
    word = plans.vessel(_load(g.live_slug)[0])
    with _edit() as data:
        if _require_tasting(data):
            if any(data["ratings"].values()):
                flash(f"Es gibt schon Wertungen, Mischen würde sie den falschen {word['many']} zuordnen.")
            else:
                numbers = list(range(1, len(data["vessels"]) + 1))
                random.SystemRandom().shuffle(numbers)
                for vessel, number in zip(data["vessels"], numbers):
                    vessel["number"] = number
                flash(f"Die {word['many']} sind gemischt.")
    return redirect(url_for("live.admin"))


@bp.post("/admin/enthuellung")
@admin_required
def start_ceremony():
    plan, data = _load(g.live_slug)
    ranked = _ranked_ids(data, store().users())
    if data["phase"] != "tasting":
        return redirect(url_for("live.home"))
    if not ranked:
        flash("Es gibt noch nichts zu enthüllen: Erst muss etwas bewertet sein.")
        return redirect(url_for("live.admin"))
    with _edit() as live:
        live.update(phase="ceremony", reveal_count=0, ceremony_order=list(reversed(ranked)))
    return redirect(url_for("live.home"))


@bp.post("/admin/zurueck")
@admin_required
def reopen():
    with _edit() as data:
        data.update(phase="tasting", reveal_count=0, ceremony_order=[])
    flash("Zurück am Tisch. Alle Wertungen sind noch da.")
    return redirect(url_for("live.admin"))


@bp.get("/admin/export.json")
@admin_required
def export():
    plan, data = _load(g.live_slug)
    entry = to_archive(data, store().users(), plan)
    return Response(json.dumps(entry, ensure_ascii=False, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename={plan['slug']}-ergebnisse.json"})


@bp.post("/admin/loeschen")
@admin_required
def delete():
    plan, _ = _load(g.live_slug)
    if request.form.get("confirm", "").strip().casefold() != plan["title"].casefold():
        flash("Zum Löschen den Namen des Tastings genau eintippen.")
        return redirect(url_for("live.admin"))
    plans.remove(plan["slug"])
    flash(f"„{plan['title']}“ ist gelöscht. Eine Sicherung liegt unter data/backups.")
    return redirect(url_for("core.landing"))
