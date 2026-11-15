"""The neutral part around all tastings: login, the start page with its
tiles, old addresses and error pages."""

from flask import (
    Blueprint,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import results, security, views
from .registry import TASTINGS
from .web import login_required, store, wants_json

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
    return render_template("landing.html", tiles=tiles)


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
