"""The Blood War of Chips: a blind chips tasting for a Descent into Avernus group."""

import os
from datetime import timedelta
from urllib.parse import urlsplit

from flask import Flask, abort, g, request, session

from . import security
from .store import Store

MAX_REQUEST_BYTES = 64 * 1024


def _allowed_host():
    return (urlsplit(os.environ.get("PUBLIC_URL", "")).hostname or "").lower()


def create_app(data_dir=None):
    app = Flask(__name__)
    data_dir = data_dir or os.environ.get("DATA_DIR", "./data")
    store = Store(data_dir)
    app.extensions["store"] = store
    app.extensions["limiter"] = security.LoginLimiter()
    app.secret_key = security.load_or_create_secret_key(data_dir)
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        SESSION_COOKIE_NAME="avernus",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        # Plain http inside the home network, see the README for why.
        SESSION_COOKIE_SECURE=False,
        PUBLIC_URL=os.environ.get("PUBLIC_URL", ""),
    )
    allowed_host = _allowed_host()

    @app.before_request
    def check_request():
        if request.endpoint == "main.healthz":
            return
        # Host check: stops DNS rebinding from turning a malicious website into
        # a path into this LAN-only app.
        if allowed_host and request.host.rsplit(":", 1)[0].lower() != allowed_host:
            abort(400)
        g.user = None
        uid = session.get("uid")
        if uid:
            user = store.users().get(uid)
            # The fingerprint logs people out when their passphrase is reset.
            if user and session.get("fp") == user["hash"][-16:]:
                g.user = {"id": uid, **{k: v for k, v in user.items() if k != "hash"}}
            else:
                session.clear()
        if request.method == "POST":
            submitted = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
            if not security.csrf_valid(session, submitted):
                abort(403)

    @app.after_request
    def add_headers(response):
        return security.apply_security_headers(response)

    @app.context_processor
    def template_globals():
        return {
            "csrf_token": security.csrf_token_for(session),
            "user": g.get("user"),
        }

    from .views import bp

    app.register_blueprint(bp)
    return app
