"""Finished tastings: one themed results page each, built from data/<slug>.json.

The data comes in once as an upload (see archive.py for the format) and is
then written out as its own file, like tasting.json for the chips. Every
"results" tasting in registry.py gets these pages without further code.
"""

import json
from pathlib import Path

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for

from . import archive
from .registry import TASTINGS, results_tasting
from .web import admin_required, check_not_hidden, login_required, store, tasting_date

bp = Blueprint("results", __name__)


def _tasting_or_404(slug):
    tasting = results_tasting(slug)
    if tasting is None:
        abort(404)
    check_not_hidden(slug)
    return tasting


def _data(slug):
    entry = store().document(slug).read()
    return entry if entry is not None and archive.validate(entry) is None else None


def tile(tasting):
    """What the start page shows on this tasting's tile."""
    entry = _data(tasting["slug"])
    if entry is None:
        return {"status": "Noch leer", "live": False, "facts": ["Noch keine Daten eingespielt"], "winner": None, "date": None}
    summary = archive.summary(entry)
    return {
        "status": "Archiv",
        "live": False,
        "facts": [f"{summary['items']} Sorten", f"{summary['people']} Leute", f"{summary['ratings']} Wertungen"],
        "winner": summary["winner"],
        "date": summary["date"],
    }


@bp.get("/<slug>/")
@login_required
def page(slug):
    tasting = _tasting_or_404(slug)
    entry = _data(slug)
    when = tasting_date(slug, entry.get("date") if entry else None)
    return render_template("results_page.html", tasting=tasting, entry=entry, when=when)


@bp.get("/<slug>/api/ergebnisse")
@login_required
def api(slug):
    _tasting_or_404(slug)
    entry = _data(slug)
    if entry is None:
        abort(404)
    return jsonify(archive.compute(entry))


@bp.post("/<slug>/einspielen")
@admin_required
def upload(slug):
    """Writes an uploaded results file out as data/<slug>.json, replacing what was there."""
    tasting = _tasting_or_404(slug)
    file = request.files.get("file")
    try:
        entry = json.loads(file.read().decode("utf-8")) if file and file.filename else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        entry = None
    problem = "Das ist keine lesbare JSON-Datei." if entry is None else archive.validate(entry)
    if problem:
        flash(f"Nichts eingespielt. {problem}")
    else:
        entry["id"] = slug  # the file name and the address decide, not the upload
        store().document(slug).replace(entry)
        flash(f"Eingespielt: {len(entry['items'])} Sorten und {len(entry['ratings'])} Wertungen für {tasting['title']}.")
    return redirect(url_for("results.page", slug=slug))


@bp.get("/<slug>/export.json")
@admin_required
def export(slug):
    _tasting_or_404(slug)
    entry = store().document(slug).read()
    if entry is None:
        abort(404)
    return Response(
        json.dumps(entry, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={slug}.json"},
    )


def adopt_old_archive(data_dir, store):
    """Takes over files uploaded under data/archive/ by the previous version."""
    for tasting in TASTINGS:
        if tasting["kind"] != "results":
            continue
        document = store.document(tasting["slug"])
        old = Path(data_dir) / "archive" / f"{tasting['slug']}.json"
        if not document.exists() and old.is_file():
            try:
                entry = json.loads(old.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if archive.validate(entry) is None:
                document.replace(entry)
