"""The neutral part around all tastings: login, the start page with its
tiles, old addresses and error pages."""

from datetime import date

from flask import (
    Blueprint,
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

from . import ideas, images, plans, results, security, views
from .registry import TASTINGS
from .web import admin_required, german_date, login_required, start_document, store, tasting_date, wants_json

bp = Blueprint("core", __name__)


@bp.get("/healthz")
def healthz():
    return "ok"


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("core.landing"))
    users = store().users()
    limiter = current_app.extensions["limiter"]
    error = None
    if request.method == "POST":
        uid = request.form.get("user", "")
        attempt = request.form.get("passphrase", "")[:200]
        ip = request.remote_addr or "?"
        if limiter.blocked(ip, uid):
            error = "Zu viele Fehlversuche. Versuch es in fünf Minuten noch einmal."
        else:
            user = users.get(uid)
            ok = security.verify_passphrase(user["hash"] if user else security.DUMMY_HASH, attempt)
            if user and ok:
                limiter.clear(ip, uid)
                session.clear()
                session.permanent = True
                session["uid"] = uid
                session["fp"] = user["hash"][-16:]
                return redirect(url_for("core.landing"))
            limiter.record_failure(ip, uid)
            error = "Die Passphrase stimmt nicht."
    options = sorted(
        ({"id": uid, "name": u["name"]} for uid, u in users.items()),
        key=lambda o: (o["id"] == "admin", o["name"].lower()),
    )
    return render_template("login.html", options=options, error=error), (401 if error else 200)


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("core.login"))


@bp.get("/")
@login_required
def landing():
    tiles = []
    for tasting in TASTINGS:
        if tasting["kind"] == "live":
            info = views.tile()
            href = url_for(tasting["endpoint"])
        else:
            info = results.tile(tasting)
            href = url_for("results.page", slug=tasting["slug"])
        info["date"] = tasting_date(tasting["slug"], info.get("date"))
        tiles.append({**tasting, **info, "href": href})
    view = request.cookies.get(VIEW_COOKIE)
    return render_template("landing.html", tiles=tiles, start=start_document().read(),
                           view=view if view in VIEWS else "tafel", plans=plans.tiles(), ideas=ideas.tile())


# The start page shows either the table picture or the tiles. The choice is
# per device, in a small cookie of its own, so it survives logging out.
VIEW_COOKIE = "ansicht"
VIEWS = ("tafel", "kacheln")


@bp.post("/start/ansicht")
@login_required
def set_view():
    view = request.form.get("view")
    if view not in VIEWS:
        abort(400)
    # The page script switches at once and only saves; a plain form goes back to the page.
    response = ("", 204) if request.headers.get("X-CSRF-Token") else redirect(url_for("core.landing"))
    response = current_app.make_response(response)
    response.set_cookie(VIEW_COOKIE, view, max_age=365 * 24 * 3600, httponly=True, samesite="Lax",
                        secure=current_app.config.get("SESSION_COOKIE_SECURE", False))
    return response


@bp.app_template_filter("german_date")
def german_date_filter(iso):
    return german_date(iso)


@bp.post("/start/daten")
@admin_required
def set_dates():
    """Saves the date of each tasting. An empty field falls back to the date its data brings."""
    changes = {}
    for tasting in TASTINGS:
        value = request.form.get(f"date_{tasting['slug']}", "").strip()
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                flash(f"„{value}“ ist kein Datum. Nichts gespeichert.")
                return redirect(url_for("core.landing"))
        changes[tasting["slug"]] = value or None
    with start_document().edit() as data:
        dates = data.setdefault("dates", {})
        for slug, value in changes.items():
            if value:
                dates[slug] = value
            else:
                dates.pop(slug, None)
    flash("Die Daten stehen jetzt im Gildenbuch.")
    return redirect(url_for("core.landing"))


# --- Photos on the start page ------------------------------------------------
# The admin uploads them; one is the background, all of them form the gallery.
# They live in data/images like bowl photos, listed in data/start.json.

MAX_PHOTOS = 40
MAX_CAPTION = 120


def _photo_names():
    start = start_document().read()
    names = {photo["name"] for photo in start["photos"]}
    if start.get("table"):
        names.add(start["table"]["image"])
    return names


@bp.get("/fotos/<name>")
@login_required
def photo(name):
    if not images.NAME_PATTERN.fullmatch(name) or name not in _photo_names():
        abort(404)
    response = send_from_directory(store().images_dir, name, mimetype="image/jpeg")
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@bp.post("/start/fotos")
@admin_required
def add_photo():
    if len(start_document().read()["photos"]) >= MAX_PHOTOS:
        flash(f"Mehr als {MAX_PHOTOS} Fotos passen nicht an die Wand.")
        return redirect(url_for("core.landing"))
    name, error = images.save_from_form(request.files, store().images_dir)
    if error or not name:
        flash(error or "Kein Foto ausgewählt.")
        return redirect(url_for("core.landing"))
    with start_document().edit() as data:
        data["photos"].append({"name": name, "caption": request.form.get("caption", "").strip()[:MAX_CAPTION]})
        if not data["background"]:
            data["background"] = name
    flash("Das Foto hängt jetzt an der Wand.")
    return redirect(url_for("core.landing"))


@bp.post("/start/fotos/<name>/hintergrund")
@admin_required
def set_background(name):
    if name not in _photo_names():
        abort(404)
    with start_document().edit() as data:
        data["background"] = name
    flash("Neuer Hintergrund.")
    return redirect(url_for("core.landing"))


@bp.post("/start/fotos/<name>/loeschen")
@admin_required
def delete_photo(name):
    if not images.NAME_PATTERN.fullmatch(name) or name not in _photo_names():
        abort(404)
    with start_document().edit() as data:
        data["photos"] = [p for p in data["photos"] if p["name"] != name]
        if data["background"] == name:
            data["background"] = data["photos"][0]["name"] if data["photos"] else None
    # Photo names are random, so no bowl or list item shares this file.
    (store().images_dir / name).unlink(missing_ok=True)
    flash("Foto entfernt.")
    return redirect(url_for("core.landing"))


# Addresses from before everything moved below /chips, kept alive for
# bookmarks and the printed QR code.
LEGACY = {
    "/einkauf": "/chips/einkauf",
    "/ergebnisse": "/chips/ergebnisse",
    "/enthuellung": "/chips/enthuellung",
    "/admin": "/chips/admin",
    "/admin/daten": "/chips/admin/daten",
    "/verkostungen": "/",
    "/water": "/wasser/",
}
LEGACY_PREFIXES = {
    "/schale/": "/chips/schale/",
    "/urkunde/": "/chips/urkunde/",
    "/bild/": "/chips/bild/",
    "/archiv/": "/",
}


def _legacy_redirect(path):
    # "/einkauf" arrives as "/einkauf/", because /<slug>/ asks for the slash first.
    path = path.rstrip("/") or "/"
    if path in LEGACY:
        return LEGACY[path]
    for old, new in LEGACY_PREFIXES.items():
        rest = path[len(old):]
        # Only plain names, so this can't be turned into a redirect elsewhere.
        if path.startswith(old) and rest and all(ch.isalnum() or ch in "-_." for ch in rest) and ".." not in rest:
            return new + rest + ("/" if old == "/archiv/" else "")
    return None


@bp.app_errorhandler(400)
@bp.app_errorhandler(403)
@bp.app_errorhandler(404)
@bp.app_errorhandler(413)
def handle_error(error):
    if error.code == 404 and request.method == "GET":
        target = _legacy_redirect(request.path)
        if target:
            return redirect(target, code=301)
    if wants_json():
        return jsonify({"error": error.code}), error.code
    return render_template("error.html", code=error.code), error.code


# --- The table picture --------------------------------------------------------
# A painted tavern table on the start page. Each tasting sits on it as a dish
# the admin marks with a spot; clicking a spot opens that tasting.

TABLE_MAX_SIDE = 2560


def _number(value, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    # `low <= number <= high` is False for NaN, so that is refused too.
    return round(number, 2) if low <= number <= high else None


@bp.post("/start/tafel")
@admin_required
def set_table():
    name, error = images.save_from_form(request.files, store().images_dir, TABLE_MAX_SIDE)
    if error or not name:
        flash(error or "Kein Bild ausgewählt.")
        return redirect(url_for("core.landing"))
    old = None
    with start_document().edit() as data:
        table = data.get("table") or {"spots": {}}
        old = table.get("image")
        table.update(image=name, aspect=round(images.aspect(store().images_dir, name), 4))
        data["table"] = table
    if old and old != name:
        (store().images_dir / old).unlink(missing_ok=True)
    flash("Das Tafelbild hängt. Jetzt noch die Verkostungen auf dem Tisch markieren.")
    return redirect(url_for("core.landing"))


@bp.post("/start/tafel/punkte")
@admin_required
def set_spots():
    spots = {}
    for tasting in TASTINGS:
        slug = tasting["slug"]
        if not request.form.get(f"spot_{slug}_x", "").strip():
            continue  # this tasting has no dish on the table
        x = _number(request.form.get(f"spot_{slug}_x"), 0, 100)
        y = _number(request.form.get(f"spot_{slug}_y"), 0, 100)
        r = _number(request.form.get(f"spot_{slug}_r"), 1, 30)
        if None in (x, y, r):
            flash("Ein Punkt liegt außerhalb des Bildes. Nichts gespeichert.")
            return redirect(url_for("core.landing"))
        spots[slug] = {"x": x, "y": y, "r": r}
    with start_document().edit() as data:
        if not data.get("table"):
            abort(404)
        data["table"]["spots"] = spots
    flash("Die Verkostungen stehen auf dem Tisch.")
    return redirect(url_for("core.landing"))


@bp.post("/start/tafel/loeschen")
@admin_required
def delete_table():
    with start_document().edit() as data:
        table = data.get("table")
        data["table"] = None
    if table:
        (store().images_dir / table["image"]).unlink(missing_ok=True)
    flash("Tafelbild entfernt.")
    return redirect(url_for("core.landing"))
