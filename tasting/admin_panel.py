"""The admin panel at /verwaltung: logins, who takes part where, which tastings show.

Everything here is for the admin only. A new or reset passphrase is shown
once, on the page that answers the form, and is never stored, flashed or logged.
"""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import accounts, ideas, images, live, plans, results, views
from .registry import TASTINGS
from .store import _empty_tasting
from .web import admin_required, hidden_slugs, installed_tastings, start_document, store

bp = Blueprint("admin_panel", __name__)


def _back(anchor=""):
    return redirect(url_for("admin_panel.page") + anchor)


def _user_or_404(users, uid):
    if uid not in users:
        abort(404)
    return users[uid]


def _has_data(uid):
    """True if anything in a tasting, the idea list or a plan points to this login."""
    tasting = store().read()
    if any(uid in (chip.get("added_by"), chip.get("bought_by")) for chip in tasting["chips"]):
        return True
    if any(uid in by_user for by_user in tasting["ratings"].values()):
        return True
    if any(uid in (item.get("creator"), item.get("buyer")) for item in tasting["shopping"]):
        return True
    if any(idea["by"] == uid or uid in idea["ratings"] for idea in ideas.document().read()["ideas"]):
        return True
    return any(uid in plan.get("participants", []) for plan in plans.document().read()["plans"])


def _show_passphrase(name, uid, passphrase, new):
    return render_template("passphrase.html", name=name, uid=uid, passphrase=passphrase, new=new)


@bp.get("/verwaltung")
@admin_required
def page():
    users = store().users()
    people = sorted(
        ({"id": uid, "name": u["name"], "role": u.get("role"), "active": accounts.is_active(u), "me": uid == g.user["id"]}
         for uid, u in users.items()),
        key=lambda p: (not p["active"], p["role"] != "admin", p["name"].lower()),
    )
    return render_template(
        "verwaltung.html",
        people=people,
        roles=accounts.ROLES,
        max_name=accounts.MAX_NAME,
        plans=plans.document().read()["plans"],
        tastings=_all_tastings(),
    )


# --- Every tasting of this install -------------------------------------------------


def _builtin_has_data(slug):
    if slug == "chips":
        data = store().read()
        return bool(data["chips"] or data["ratings"] or data["shopping"])
    return store().document(slug).exists()


def _all_tastings():
    """One row per tasting: the built-in ones this install kept, then our own, planned or running."""
    hidden = hidden_slugs()
    rows = []
    for tasting in installed_tastings():
        slug = tasting["slug"]
        info = views.tile() if tasting["kind"] == "live" else results.tile(tasting)
        rows.append({
            "slug": slug, "title": tasting["title"], "icon": tasting["icon"], "kind": "builtin",
            "status": "ausgeblendet" if slug in hidden else info["status"],
            "hidden": slug in hidden, "has_data": _builtin_has_data(slug),
            "href": None if slug in hidden else (url_for(tasting["endpoint"]) if tasting["kind"] == "live"
                                                 else url_for("results.page", slug=slug)),
        })
    running = {plan["slug"]: data for plan, data in live.running()}
    for plan in plans.document().read()["plans"]:
        slug = plan["slug"]
        data = running.get(slug)
        rows.append({
            "slug": slug, "title": plan["title"], "icon": plan.get("icon", "✨"),
            "kind": "live" if data else "planned",
            "status": live.STATUS[data["phase"]] if data else "Geplant",
            "people": len(plan.get("participants", [])),
            "has_data": bool(data and (data["items"] or data["vessels"] or data["ratings"])),
            "href": url_for("live.home", slug=slug) if data else url_for("plans.page", slug=slug),
            "admin_href": url_for("live.admin", slug=slug) if data else None,
        })
    return rows


def _delete_builtin(tasting):
    """Deletes a built-in tasting for good: its data (backed up first) and its place in the app."""
    slug = tasting["slug"]
    if slug == "chips":
        old = store().read()
        store().snapshot()
        store().replace(_empty_tasting())
        photos = [e.get("image") for e in old["chips"] + old["shopping"]]
        images.discard(store().images_dir, photos, store().read())
    else:
        document = store().document(slug)
        if document.exists():
            document.snapshot()
            document.path.unlink(missing_ok=True)
        store().forget(slug)
    with start_document().edit() as data:
        data["hidden"] = [h for h in data.get("hidden", []) if h != slug]
        data["deleted"] = [d for d in data.get("deleted", []) if d != slug] + [slug]


@bp.post("/verwaltung/tastings/<slug>/loeschen")
@admin_required
def delete_tasting(slug):
    """Deletes any tasting from the list. One with data asks for its name to be typed."""
    row = next((r for r in _all_tastings() if r["slug"] == slug), None)
    if row is None:
        abort(404)
    if row["has_data"] and request.form.get("confirm", "").strip().casefold() != row["title"].casefold():
        flash(f"Zum Löschen von „{row['title']}“ den Namen genau eintippen. Nichts gelöscht.")
        return _back("#tastings")
    if row["kind"] == "builtin":
        _delete_builtin(next(t for t in TASTINGS if t["slug"] == slug))
    else:
        plans.remove(slug)
    flash(f"„{row['title']}“ ist gelöscht. Eine Sicherung der Daten liegt unter data/backups.")
    return _back("#tastings")


@bp.post("/verwaltung/nutzer")
@admin_required
def add_user():
    users = store().users()
    try:
        uid, passphrase = accounts.create(users, request.form.get("name"), request.form.get("role", "player"))
    except accounts.AccountError as error:
        flash(str(error))
        return _back("#nutzer")
    store().save_users(users)
    return _show_passphrase(users[uid]["name"], uid, passphrase, new=True)


@bp.post("/verwaltung/nutzer/<uid>/passphrase")
@admin_required
def reset_user(uid):
    users = store().users()
    user = _user_or_404(users, uid)
    passphrase = accounts.reset(users, uid)
    store().save_users(users)
    return _show_passphrase(user["name"], uid, passphrase, new=False)


@bp.post("/verwaltung/nutzer/<uid>/name")
@admin_required
def rename_user(uid):
    users = store().users()
    user = _user_or_404(users, uid)
    name = request.form.get("name", "").strip()[:accounts.MAX_NAME]
    if not name:
        flash("Der Name darf nicht leer sein.")
        return _back("#nutzer")
    # The uid stays, so ratings, bowls and the login keep belonging to the same person.
    user["name"] = name
    store().save_users(users)
    flash(f"Heißt jetzt „{name}“.")
    return _back("#nutzer")


@bp.post("/verwaltung/nutzer/<uid>/rolle")
@admin_required
def set_role(uid):
    users = store().users()
    user = _user_or_404(users, uid)
    role = request.form.get("role")
    if role not in accounts.ROLES:
        abort(400)
    if role != "admin":
        try:
            accounts.check_can_lose_admin(users, uid, g.user["id"])
        except accounts.AccountError as error:
            flash(str(error))
            return _back("#nutzer")
    user["role"] = role
    store().save_users(users)
    flash(f"{user['name']} ist jetzt {accounts.ROLES[role]}.")
    return _back("#nutzer")


@bp.post("/verwaltung/nutzer/<uid>/aktiv")
@admin_required
def set_active(uid):
    users = store().users()
    user = _user_or_404(users, uid)
    active = request.form.get("active") == "1"
    if not active:
        try:
            accounts.check_can_lose_admin(users, uid, g.user["id"])
        except accounts.AccountError as error:
            flash(str(error))
            return _back("#nutzer")
        user["active"] = False  # their running sessions end on the next request
    else:
        user.pop("active", None)
    store().save_users(users)
    flash(f"{user['name']} ist {'wieder dabei' if active else 'deaktiviert und kann sich nicht mehr anmelden'}.")
    return _back("#nutzer")


@bp.post("/verwaltung/nutzer/<uid>/loeschen")
@admin_required
def delete_user(uid):
    users = store().users()
    user = _user_or_404(users, uid)
    try:
        accounts.check_can_lose_admin(users, uid, g.user["id"])
    except accounts.AccountError as error:
        flash(str(error))
        return _back("#nutzer")
    if _has_data(uid):
        flash(f"{user['name']} hat schon Wertungen, Schalen, Einkäufe, Ideen oder ist für ein Tasting eingetragen. "
              "Deaktivieren statt löschen, dann bleibt der Name in den Ergebnissen.")
        return _back("#nutzer")
    del users[uid]
    store().save_users(users)
    flash(f"Login von {user['name']} gelöscht.")
    return _back("#nutzer")


@bp.post("/verwaltung/teilnahme/<slug>")
@admin_required
def set_participants(slug):
    users = store().users()
    chosen = [uid for uid in dict.fromkeys(request.form.getlist("uid")) if uid in users]
    with plans.document().edit() as data:
        plan = next((p for p in data["plans"] if p["slug"] == slug), None)
        if plan is None:
            abort(404)
        plan["participants"] = chosen
    flash(f"Bei „{plan['title']}“ sind jetzt {len(chosen)} dabei.")
    return _back("#teilnahme")


@bp.post("/verwaltung/tastings/<slug>/<action>")
@admin_required
def sample(slug, action):
    """Hides one of the built-in tastings (chips, cola, water) for a while, or brings it back."""
    tasting = next((t for t in installed_tastings() if t["slug"] == slug), None)
    if tasting is None or action not in ("ausblenden", "entfernen", "zurueckholen"):
        abort(404)
    hide = action != "zurueckholen"
    with start_document().edit() as data:
        hidden = [h for h in data.get("hidden", []) if h != slug]
        if hide:
            hidden.append(slug)
        data["hidden"] = hidden
    flash(f"{tasting['title']} ist ausgeblendet, die Daten bleiben. „Zurückholen“ bringt es wieder."
          if hide else f"{tasting['title']} ist wieder da.")
    return _back("#tastings")


@bp.post("/verwaltung/tastings")
@admin_required
def set_hidden():
    shown = set(request.form.getlist("shown"))
    hidden = [t["slug"] for t in TASTINGS if t["slug"] not in shown]
    with start_document().edit() as data:
        data["hidden"] = hidden
    flash("Die Startseite ist angepasst." if hidden else "Alle Tastings sind wieder auf der Startseite.")
    return _back("#tastings")
