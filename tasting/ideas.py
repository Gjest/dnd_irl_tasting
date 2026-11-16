"""The idea list: what the guild could taste next, with stars from everyone.

Anyone logged in adds an idea (just a name) and gives every idea one to five
stars. The list is sorted by average stars, so the favorite is on top.
Whoever added an idea, and the admin, can remove it. Kept in data/ideas.json.
"""

import secrets
from datetime import date
from statistics import mean

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .web import login_required, store

bp = Blueprint("ideas", __name__)

MAX_IDEAS = 300
MAX_NAME = 80
STARS = range(1, 6)


def document():
    return store().document("ideas", empty=lambda: {"ideas": []})


def ranked():
    """All ideas, best first: average stars, then how many rated, then the oldest."""
    users = store().users()
    shown = []
    for idea in document().read()["ideas"]:
        stars = list(idea["ratings"].values())
        shown.append({
            **idea,
            "by_name": users.get(idea["by"], {}).get("name", "Unbekannt"),
            "average": mean(stars) if stars else None,
            "votes": len(stars),
        })
    return sorted(shown, key=lambda i: (-(i["average"] or 0), -i["votes"], i["created"]))


def tile():
    ideas = ranked()
    return {"count": len(ideas), "top": ideas[0]["name"] if ideas and ideas[0]["votes"] else None}


def _back(idea_id=None):
    return redirect(url_for("ideas.page") + (f"#idee-{idea_id}" if idea_id else ""))


@bp.get("/ideen")
@login_required
def page():
    return render_template("ideas.html", ideas=ranked(), stars=STARS, max_name=MAX_NAME)


@bp.post("/ideen")
@login_required
def add():
    name = request.form.get("name", "").strip()[:MAX_NAME]
    if not name:
        flash("Schreib auf, was man probieren könnte.")
        return _back()
    with document().edit() as data:
        same = next((i for i in data["ideas"] if i["name"].casefold() == name.casefold()), None)
        if same:
            flash(f"„{same['name']}“ steht schon auf der Liste. Gib ihr lieber Sterne.")
            idea_id = same["id"]
        elif len(data["ideas"]) >= MAX_IDEAS:
            flash(f"Mehr als {MAX_IDEAS} Ideen passen nicht auf die Liste.")
            idea_id = None
        else:
            idea_id = secrets.token_hex(6)
            data["ideas"].append({"id": idea_id, "name": name, "by": g.user["id"],
                                  "created": date.today().isoformat(), "ratings": {}})
    return _back(idea_id)


@bp.post("/ideen/<idea_id>/sterne")
@login_required
def rate(idea_id):
    try:
        stars = int(request.form.get("stars", ""))
    except ValueError:
        abort(400)
    if stars not in STARS:
        abort(400)
    with document().edit() as data:
        idea = next((i for i in data["ideas"] if i["id"] == idea_id), None)
        if idea is None:
            abort(404)
        # Tapping your own rating again takes it back.
        if idea["ratings"].get(g.user["id"]) == stars:
            del idea["ratings"][g.user["id"]]
        else:
            idea["ratings"][g.user["id"]] = stars
    return _back(idea_id)


@bp.post("/ideen/<idea_id>/loeschen")
@login_required
def delete(idea_id):
    idea = next((i for i in document().read()["ideas"] if i["id"] == idea_id), None)
    if idea is None:
        abort(404)
    if idea["by"] != g.user["id"] and g.user.get("role") != "admin":
        abort(403)
    document().snapshot()
    with document().edit() as data:
        data["ideas"] = [i for i in data["ideas"] if i["id"] != idea_id]
    flash(f"„{idea['name']}“ ist von der Liste.")
    return _back()
