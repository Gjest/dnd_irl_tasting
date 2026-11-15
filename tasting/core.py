"""The neutral part around all tastings: login, the start page with its
tiles, old addresses and error pages."""

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

from . import images, results, security, views
from .registry import TASTINGS
from .web import admin_required, login_required, store, wants_json

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
        tiles.append({**tasting, **info, "href": href})
    return render_template("landing.html", tiles=tiles, start=_start().read())


# --- Photos on the start page ------------------------------------------------
# The admin uploads them; one is the background, all of them form the gallery.
# They live in data/images like bowl photos, listed in data/start.json.

MAX_PHOTOS = 40
MAX_CAPTION = 120


def _start():
    return store().document("start", empty=lambda: {"photos": [], "background": None})


def _photo_names():
    return {photo["name"] for photo in _start().read()["photos"]}


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
    if len(_start().read()["photos"]) >= MAX_PHOTOS:
        flash(f"Mehr als {MAX_PHOTOS} Fotos passen nicht an die Wand.")
        return redirect(url_for("core.landing"))
    name, error = images.save_from_form(request.files, store().images_dir)
    if error or not name:
        flash(error or "Kein Foto ausgewählt.")
        return redirect(url_for("core.landing"))
    with _start().edit() as data:
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
    with _start().edit() as data:
        data["background"] = name
    flash("Neuer Hintergrund.")
    return redirect(url_for("core.landing"))


@bp.post("/start/fotos/<name>/loeschen")
@admin_required
def delete_photo(name):
    if not images.NAME_PATTERN.fullmatch(name) or name not in _photo_names():
        abort(404)
    with _start().edit() as data:
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
