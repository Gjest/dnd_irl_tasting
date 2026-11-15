"""Helpers every part of the app shares: the store and the login checks."""

from functools import wraps

from flask import abort, current_app, g, redirect, request, url_for


def store():
    return current_app.extensions["store"]


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
