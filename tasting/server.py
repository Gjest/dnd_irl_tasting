"""Production entry point: python -m tasting.server"""

import os

from waitress import serve

from . import create_app


def main():
    app = create_app()
    if not app.extensions["store"].users():
        print("Noch keine Logins vorhanden. Führe ./setup.sh aus oder:", flush=True)
        print("  docker compose exec app python -m tasting.manage init", flush=True)
    serve(app, host="0.0.0.0", port=int(os.environ.get("APP_PORT", "8000")), threads=8, ident=None)


if __name__ == "__main__":
    main()
