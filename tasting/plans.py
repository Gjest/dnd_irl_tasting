"""Planned tastings: a name and a first set of questions, before any code exists.

The admin starts one with the + tile on the start page. It shows there as
"Bald" until it becomes a real tasting. Its questions are kept as a template
(format below) that can be downloaded and uploaded again, and that uses the
same "sections" and "criteria" as a results file (archive.py), so the
questions carry over when the tasting is built, e.g. as a copy of the chips
tasting.

    {
      "format": "tasting-template/1",
      "title": "Kaffee-Verkostung", "short": "Kaffee", "icon": "☕", "tagline": "…",
      "scale": {"min": 1, "max": 5},
      "sections": [
        {"title": "Die Nase", "criteria": [
          {"key": "duft", "label": "Duft", "type": "scale", "low": "kaum", "high": "betörend"},
          {"key": "notizen", "label": "Was riechst du?", "type": "text"}
        ]}
      ]
    }

Plans live in data/plans.json, next to the other tastings.
"""

import json
import re
from contextlib import contextmanager
from datetime import date

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for

from .registry import TASTINGS
from .web import admin_required, login_required, store

bp = Blueprint("plans", __name__)

FORMAT = "tasting-template/1"
TYPES = {"scale": "Skala", "text": "Freitext"}
MAX_PLANS = 30
MAX_SECTIONS = 15
MAX_QUESTIONS = 80
LIMITS = {"title": 80, "short": 24, "icon": 8, "tagline": 140, "section": 80, "label": 140, "end": 60}
SLUG_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
# Addresses that already mean something, so a plan can never shadow them.
RESERVED = {t["slug"] for t in TASTINGS} | {
    "start", "login", "logout", "fotos", "plaene", "ideen", "static", "healthz", "neu", "import",
}
UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def document():
    return store().document("plans", empty=lambda: {"plans": []})


def _text(value, limit):
    return value.strip()[:limit] if isinstance(value, str) else ""


def slugify(title, taken):
    base = re.sub(r"[^a-z0-9]+", "-", title.lower().translate(UMLAUTS)).strip("-")[:36] or "tasting"
    slug, n = base, 2
    while slug in taken or slug in RESERVED:
        slug, n = f"{base}-{n}", n + 1
    return slug


def _keyed(sections):
    """Gives every question a key from its label, unique within the plan."""
    used = set()
    for section in sections:
        for criterion in section["criteria"]:
            base = re.sub(r"[^a-z0-9]+", "_", criterion["label"].lower().translate(UMLAUTS)).strip("_")[:30] or "frage"
            key, n = base, 2
            while key in used:
                key, n = f"{base}_{n}", n + 1
            used.add(key)
            criterion["key"] = key
    return sections


def validate(template):
    """Returns what is wrong with an uploaded template, or None if it can be used."""
    if not isinstance(template, dict) or template.get("format") != FORMAT:
        return f"Das ist keine Vorlage (format muss „{FORMAT}“ sein)."
    if not _text(template.get("title"), LIMITS["title"]):
        return "Der Name fehlt."
    scale = template.get("scale", {"min": 1, "max": 5})
    if not (isinstance(scale, dict) and isinstance(scale.get("min"), int) and isinstance(scale.get("max"), int)
            and 0 <= scale["min"] < scale["max"] <= 10):
        return "Die Skala (scale.min, scale.max) muss zwischen 0 und 10 liegen."
    sections = template.get("sections", [])
    if not isinstance(sections, list) or len(sections) > MAX_SECTIONS:
        return f"Die Abschnitte fehlen oder sind mehr als {MAX_SECTIONS}."
    count = 0
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("criteria", []), list):
            return "Ein Abschnitt ist kaputt."
        for criterion in section.get("criteria", []):
            if not isinstance(criterion, dict) or not _text(criterion.get("label"), LIMITS["label"]):
                return "Eine Frage hat keinen Text."
            if criterion.get("type", "scale") not in TYPES:
                return "Eine Frage hat eine unbekannte Art (erlaubt sind scale und text)."
            count += 1
    if count > MAX_QUESTIONS:
        return f"Mehr als {MAX_QUESTIONS} Fragen passen nicht in eine Vorlage."
    return None


def clean(template, slug):
    """A plan from a checked template: only known fields, trimmed, with fresh keys."""
    sections = []
    for section in template.get("sections", []):
        criteria = []
        for criterion in section.get("criteria", []):
            kind = criterion.get("type", "scale")
            entry = {"key": "", "label": _text(criterion["label"], LIMITS["label"]), "type": kind}
            if kind == "scale":
                entry["low"] = _text(criterion.get("low"), LIMITS["end"])
                entry["high"] = _text(criterion.get("high"), LIMITS["end"])
            criteria.append(entry)
        sections.append({"title": _text(section.get("title"), LIMITS["section"]) or "Ohne Titel", "criteria": criteria})
    scale = template.get("scale", {"min": 1, "max": 5})
    return {
        "slug": slug,
        "title": _text(template["title"], LIMITS["title"]),
        "short": _text(template.get("short"), LIMITS["short"]),
        "icon": _text(template.get("icon"), LIMITS["icon"]) or "✨",
        "tagline": _text(template.get("tagline"), LIMITS["tagline"]),
        "scale": {"min": scale["min"], "max": scale["max"]},
        "sections": _keyed(sections),
        "created": date.today().isoformat(),
        # Who takes part, set in /verwaltung. Not part of the template: a template is only the questions.
        "participants": [],
    }


def export(plan):
    return {"format": FORMAT, **{k: plan[k] for k in ("title", "short", "icon", "tagline", "scale", "sections")}}


def question_count(plan):
    return sum(len(section["criteria"]) for section in plan["sections"])


def tiles():
    """What the start page shows for each plan."""
    shown = []
    for plan in document().read()["plans"]:
        questions = question_count(plan)
        shown.append({**plan, "href": url_for("plans.page", slug=plan["slug"]),
                      "facts": [f"{questions} Frage{'' if questions == 1 else 'n'}" if questions else "Noch keine Fragen",
                                f"{len(plan['sections'])} Abschnitt{'' if len(plan['sections']) == 1 else 'e'}"]})
    return shown


def _plan_or_404(slug):
    for plan in document().read()["plans"]:
        if plan["slug"] == slug:
            return plan
    abort(404)


def _add(template):
    """Stores a checked template as a new plan and returns its slug, or None if full."""
    with document().edit() as data:
        if len(data["plans"]) >= MAX_PLANS:
            return None
        slug = slugify(_text(template["title"], LIMITS["title"]), {p["slug"] for p in data["plans"]})
        data["plans"].append(clean(template, slug))
    return slug


@contextmanager
def _edit(slug):
    """The live plan inside an edit. A 404 (or any error) inside discards the edit."""
    with document().edit() as data:
        plan = next((p for p in data["plans"] if p["slug"] == slug), None)
        if plan is None:
            abort(404)
        yield plan


def _back(slug, anchor=""):
    return redirect(url_for("plans.page", slug=slug) + anchor)


@bp.get("/plaene/neu")
@admin_required
def new():
    return render_template("plan_new.html", limits=LIMITS)


@bp.post("/plaene/neu")
@admin_required
def create():
    title = _text(request.form.get("title"), LIMITS["title"])
    if not title:
        flash("Gib dem Tasting einen Namen.")
        return redirect(url_for("plans.new"))
    slug = _add({"title": title, "short": request.form.get("short"), "icon": request.form.get("icon"),
                 "tagline": request.form.get("tagline"), "sections": []})
    if slug is None:
        flash(f"Mehr als {MAX_PLANS} geplante Tastings passen nicht auf die Seite.")
        return redirect(url_for("core.landing"))
    flash(f"„{title}“ ist angelegt. Jetzt kommen die Fragen.")
    return _back(slug)


@bp.post("/plaene/import")
@admin_required
def upload():
    file = request.files.get("file")
    try:
        template = json.loads(file.read().decode("utf-8")) if file and file.filename else None
    except (UnicodeDecodeError, json.JSONDecodeError):
        template = None
    problem = "Das ist keine lesbare JSON-Datei." if template is None else validate(template)
    if problem:
        flash(f"Nichts angelegt. {problem}")
        return redirect(url_for("plans.new"))
    slug = _add(template)
    if slug is None:
        flash(f"Mehr als {MAX_PLANS} geplante Tastings passen nicht auf die Seite.")
        return redirect(url_for("core.landing"))
    flash("Vorlage eingespielt.")
    return _back(slug)


@bp.get("/plaene/<slug>")
@login_required
def page(slug):
    plan = _plan_or_404(slug)
    users = store().users()
    people = [users[uid]["name"] for uid in plan.get("participants", []) if uid in users]
    return render_template("plan.html", plan=plan, types=TYPES, limits=LIMITS, count=question_count(plan), people=people)


@bp.get("/plaene/<slug>/vorlage.json")
@admin_required
def download(slug):
    plan = _plan_or_404(slug)
    return Response(json.dumps(export(plan), ensure_ascii=False, indent=2), mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename={slug}-vorlage.json"})


@bp.post("/plaene/<slug>/angaben")
@admin_required
def update(slug):
    title = _text(request.form.get("title"), LIMITS["title"])
    if not title:
        flash("Der Name darf nicht leer sein.")
        return _back(slug)
    with _edit(slug) as plan:
        plan["title"] = title
        plan["short"] = _text(request.form.get("short"), LIMITS["short"])
        plan["icon"] = _text(request.form.get("icon"), LIMITS["icon"]) or "✨"
        plan["tagline"] = _text(request.form.get("tagline"), LIMITS["tagline"])
    flash("Gespeichert.")
    return _back(slug)


@bp.post("/plaene/<slug>/abschnitt")
@admin_required
def add_section(slug):
    title = _text(request.form.get("title"), LIMITS["section"])
    if not title:
        flash("Der Abschnitt braucht einen Titel.")
        return _back(slug)
    with _edit(slug) as plan:
        if len(plan["sections"]) >= MAX_SECTIONS:
            flash(f"Mehr als {MAX_SECTIONS} Abschnitte gehen nicht.")
        else:
            plan["sections"].append({"title": title, "criteria": []})
        index = len(plan["sections"]) - 1
    return _back(slug, f"#abschnitt-{index}")


@bp.post("/plaene/<slug>/abschnitt/<int:index>/loeschen")
@admin_required
def delete_section(slug, index):
    with _edit(slug) as plan:
        if not 0 <= index < len(plan["sections"]):
            abort(404)
        plan["sections"].pop(index)
        _keyed(plan["sections"])
    flash("Abschnitt entfernt.")
    return _back(slug)


@bp.post("/plaene/<slug>/abschnitt/<int:index>/frage")
@admin_required
def add_question(slug, index):
    label = _text(request.form.get("label"), LIMITS["label"])
    kind = request.form.get("type", "scale")
    if not label or kind not in TYPES:
        flash("Die Frage braucht einen Text.")
        return _back(slug, f"#abschnitt-{index}")
    with _edit(slug) as plan:
        if not 0 <= index < len(plan["sections"]):
            abort(404)
        if question_count(plan) >= MAX_QUESTIONS:
            flash(f"Mehr als {MAX_QUESTIONS} Fragen gehen nicht.")
        else:
            entry = {"key": "", "label": label, "type": kind}
            if kind == "scale":
                entry["low"] = _text(request.form.get("low"), LIMITS["end"])
                entry["high"] = _text(request.form.get("high"), LIMITS["end"])
            plan["sections"][index]["criteria"].append(entry)
            _keyed(plan["sections"])
    return _back(slug, f"#abschnitt-{index}")


def _question(plan, index, number):
    if not 0 <= index < len(plan["sections"]) or not 0 <= number < len(plan["sections"][index]["criteria"]):
        abort(404)
    return plan["sections"][index]["criteria"]


@bp.post("/plaene/<slug>/abschnitt/<int:index>/frage/<int:number>/hoch")
@admin_required
def move_question(slug, index, number):
    with _edit(slug) as plan:
        criteria = _question(plan, index, number)
        if number > 0:
            criteria[number - 1], criteria[number] = criteria[number], criteria[number - 1]
    return _back(slug, f"#abschnitt-{index}")


@bp.post("/plaene/<slug>/abschnitt/<int:index>/frage/<int:number>/loeschen")
@admin_required
def delete_question(slug, index, number):
    with _edit(slug) as plan:
        _question(plan, index, number).pop(number)
        _keyed(plan["sections"])
    return _back(slug, f"#abschnitt-{index}")


@bp.post("/plaene/<slug>/loeschen")
@admin_required
def delete(slug):
    _plan_or_404(slug)
    document().snapshot()
    with document().edit() as data:
        data["plans"] = [plan for plan in data["plans"] if plan["slug"] != slug]
    flash("Geplantes Tasting entfernt. Eine Sicherung liegt unter data/backups.")
    return redirect(url_for("core.landing"))
