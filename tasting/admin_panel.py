"""The admin panel at /verwaltung: logins, who takes part where, which tastings show.

Everything here is for the admin only. A new or reset passphrase is shown
once, on the page that answers the form, and is never stored, flashed or logged.
"""

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import accounts, ideas, plans
from .registry import TASTINGS
from .web import admin_required, hidden_slugs, start_document, store

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
    hidden = hidden_slugs()
    return render_template(
        "verwaltung.html",
        people=people,
        roles=accounts.ROLES,
        max_name=accounts.MAX_NAME,
        plans=plans.document().read()["plans"],
        tastings=[{**t, "hidden": t["slug"] in hidden} for t in TASTINGS],
    )


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
    """Takes one of the built-in tastings (chips, cola, water) off this install, or brings it back."""
    tasting = next((t for t in TASTINGS if t["slug"] == slug), None)
    if tasting is None or action not in ("entfernen", "zurueckholen"):
        abort(404)
    with start_document().edit() as data:
        hidden = [h for h in data.get("hidden", []) if h != slug]
        if action == "entfernen":
            hidden.append(slug)
        data["hidden"] = hidden
    flash(f"{tasting['title']} ist entfernt. Unter „Muster-Tastings“ holst du es jederzeit zurück."
          if action == "entfernen" else f"{tasting['title']} ist wieder da.")
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
