"""The tastings on the start page, one tile each.

A new tasting needs an entry here. "results" tastings only show finished
results and share one page (results.py). Their data is uploaded once and then
lives in data/<slug>.json. A "live" tasting brings its own blueprint, as the
chips tasting does with views.py under /chips.
"""

TASTINGS = [
    {
        "slug": "chips",
        "kind": "live",
        "number": 3,
        "title": "Blutkrieg der Chips",
        "tagline": "Blind verkostet, mit Sucht-Save und Einkaufsliste",
        "icon": "🔥",
        "endpoint": "main.home",
    },
    {
        "slug": "cola",
        "kind": "results",
        "number": 1,
        "title": "Cola-Verkostung",
        "tagline": "Die erste Verkostung, noch per Google-Formular",
        "icon": "🥤",
        "theme": "cola",
    },
    {
        "slug": "wasser",
        "kind": "results",
        "number": 2,
        "title": "Wasser-Verkostung",
        "tagline": "D&D-Wochenende im August 2026",
        "icon": "💧",
        "theme": "wasser",
    },
]

BY_SLUG = {tasting["slug"]: tasting for tasting in TASTINGS}


def results_tasting(slug):
    tasting = BY_SLUG.get(slug)
    return tasting if tasting and tasting["kind"] == "results" else None
