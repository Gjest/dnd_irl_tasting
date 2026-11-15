"""Helpers every part of the app shares: the store and the login checks."""

from datetime import date
from functools import wraps

from flask import abort, current_app, g, redirect, request, url_for


def store():
    return current_app.extensions["store"]


def start_document():
    """data/start.json: photos and dates for the start page, kept across tastings."""
    return store().document("start", empty=lambda: {"photos": [], "background": None, "dates": {}})


def tasting_date(slug, fallback=None):
    """The date the admin set for a tasting, else the one its data brings along."""
    return start_document().read().get("dates", {}).get(slug) or fallback


MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
          "September", "Oktober", "November", "Dezember"]


def german_date(iso):
    """"2026-08-16" becomes "16. August 2026"; anything unreadable stays as it is."""
    try:
        day = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso
    return f"{day.day}. {MONTHS[day.month - 1]} {day.year}"


def wants_json():
    # Every tasting keeps its data endpoints below …/api/.
    return "/api/" in request.path


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if wants_json():
                abort(401)
            return redirect(url_for("core.login"))
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
