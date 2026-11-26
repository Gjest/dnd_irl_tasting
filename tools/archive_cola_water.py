"""Turns the cola analysis page and the water H2 database into archive files.

Run from the project root:
  python3 tools/archive_cola_water.py ../cola-tasting/cola_tasting_analyse_v3-1.html water.json [aliases.json]
where water.json comes from: python3 tools/h2rows.py ../WaterTasting/export/watertasting.mv.db > water.json

aliases.json maps names as they were recorded to the names the group uses
everywhere, e.g. {"Lennart": "Der Lenny"}. It holds real names, so it stays
next to the exports and out of git.
"""
import json
import re
import sys
from pathlib import Path
from statistics import mean

# The questions live in the app, where "Neues Tasting planen" offers them as samples.
# samples.py imports nothing from the app, so it loads here without Flask.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tasting"))
from samples import COLA_SECTIONS, WATER_SECTIONS  # noqa: E402


def cola(path):
    script = re.findall(r"<script[^>]*>(.*?)</script>", open(path, encoding="utf-8").read(), re.S)[1]
    names = {int(k): v for k, v in re.findall(r"(\d+):'([^']+)'", re.search(r"const BEV=\{(.*?)\};", script).group(1))}
    zero = {int(x) for x in re.search(r"const ZERO=\[(.*?)\]", script).group(1).split(",")}
    rows = re.search(r"const raw=`(.*?)`", script, re.S).group(1).strip().split("\n")
    columns = ["farbe", "fenster", "krone", "zitrus", "zimt", "nelke", "kraeuter", "noten", "carb", "suesse", "saeure",
               "zitrone", "limette", "orange", "beere", "bitter", "koerper", "zahn", "nachhall", "harmonie", "genuss"]
    ratings = []
    for row in rows:
        parts = row.split(",")
        values = dict(zip(columns, parts[3:]))
        notes = values.pop("noten").strip()
        ratings.append({
            "person": parts[0],
            "item": parts[2],
            "scores": {k: int(v) if v.strip() else None for k, v in values.items()},
            "flags": {"served": parts[1] == "Ja"},
            **({"notes": notes} if notes else {}),
        })
    return {
        "format": "tasting-archive/1",
        "id": "cola",
        "number": 1,
        "title": "Cola-Verkostung",
        "subtitle": "Die erste Verkostung, noch per Google-Formular",
        "date": None,
        "intro": "Die Fragen stammen aus der gespeicherten Formularseite, die Antworten aus der damaligen Auswertung. "
                 "Wer eingeschenkt hat, wusste, was im Glas war.",
        "scale": {"min": 1, "max": 5},
        "ranking": "genuss",
        "tiebreak": "harmonie",
        "group_label": "Zero gegen Zucker",
        "sections": COLA_SECTIONS,
        "items": [{"id": str(k), "name": v, "group": "Zero" if k in zero else "Zucker"} for k, v in sorted(names.items())],
        "flags": [{"key": "served", "label": "Selbst eingeschenkt", "hint": "Wer eingeschenkt hat, kannte die Cola."}],
        "awards": [
            {"title": "Süßeste Bombe", "line": "Ein Schluck, und die Zähne schreiben ihr Testament.", "terms": [{"key": "suesse"}], "best": "max"},
            {"title": "Sauer macht lustig", "line": "Zieht die Mundwinkel bis nach Avernus.", "terms": [{"key": "saeure"}], "best": "max"},
            {"title": "Kohlensäure-Monster", "line": "Prickelt wie ein Feuerball im Hals.", "terms": [{"key": "carb"}], "best": "max"},
            {"title": "Vollster Körper", "line": "Mehr Substanz als mancher Abenteurer.", "terms": [{"key": "koerper"}], "best": "max"},
            {"title": "Zahnschmelz-Killer", "line": "Danach fühlen sich die Zähne an wie Teppich.", "terms": [{"key": "zahn"}], "best": "max"},
            {"title": "Bitterste Pille", "line": "Schmeckt nach Medizin aus Bels Labor.", "terms": [{"key": "bitter"}], "best": "max"},
        ],
        "ratings": ratings,
    }


def water(path, aliases=None):
    rows = json.load(open(path, encoding="utf-8"))
    keys = ["clarity", "color", "odor", "carbonation", "temperature", "body", "mineral_intensity", "sweetness",
            "bitterness", "salinity", "ph_sensation", "duration", "harmony", "personal_enjoyment"]
    names = sorted({r["water_sample_id"].strip() for r in rows})
    ids = {name: re.sub(r"[^a-z0-9]+", "-", name.lower().replace("ü", "ue").replace("ö", "oe")).strip("-") for name in names}
    # Their "Mineral Battle" split at the average mineral intensity.
    threshold = mean(r["mineral_intensity"] for r in rows)
    mineral = {name: mean(r["mineral_intensity"] for r in rows if r["water_sample_id"].strip() == name) for name in names}
    ratings = []
    for r in sorted(rows, key=lambda r: r["created_at"]):
        notes = (r.get("notes") or "").strip()
        ratings.append({
            "person": (aliases or {}).get(r["adventurer_name"].strip(), r["adventurer_name"].strip()),
            "item": ids[r["water_sample_id"].strip()],
            "scores": {k: r[k] for k in keys},
            "time": r["created_at"],
            **({"notes": notes} if notes else {}),
        })
    return {
        "format": "tasting-archive/1",
        "id": "wasser",
        "number": 2,
        "title": "Wasser-Verkostung",
        "subtitle": "D&D-Wochenende, 14. bis 16. August 2026",
        "date": "2026-08-14",
        "intro": "Die zweite Verkostung lief als eigene App mit Datenbank. Übernommen ist der bereinigte Stand, "
                 "in dem Namen und Sorten schon vereinheitlicht waren."
                 + (" Die Namen sind auf die Spitznamen der Gruppe umgestellt." if aliases else ""),
        "scale": {"min": 1, "max": 5},
        "ranking": "personal_enjoyment",
        "tiebreak": "harmony",
        "group_label": "Mineral-Schlacht",
        "sections": WATER_SECTIONS,
        "items": [{"id": ids[n], "name": n, "group": "Mineralreich" if mineral[n] >= threshold else "Mineralarm"} for n in names],
        "awards": [
            {"title": "Die Salzmine", "line": "Salziger als der Wortschatz eines Seemanns.", "terms": [{"key": "salinity"}], "best": "max"},
            {"title": "Bewölkt mit Aussicht auf Regen", "line": "Besucher aus dem Sumpf sahen ihre eigene Hand nicht mehr.", "terms": [{"key": "clarity"}], "best": "min"},
            {"title": "Drachenatem", "line": "Bitter und sauer genug, um einen schlafenden Wyrm zu wecken.",
             "terms": [{"key": "bitterness"}, {"key": "ph_sensation", "invert": True}], "best": "max"},
            {"title": "Die reinste Quelle", "line": "Ausgewogen genug, um das ganze Königreich zu beruhigen.", "terms": [{"key": "harmony"}], "best": "max"},
            {"title": "Der bescheidene Hahn", "line": "Jemand musste es trinken. Es brauchte Mut.", "terms": [{"key": "personal_enjoyment"}], "best": "min"},
        ],
        "ratings": ratings,
    }


if __name__ == "__main__":
    aliases = json.load(open(sys.argv[3], encoding="utf-8")) if len(sys.argv) > 3 else {}
    for name, archive in (("export/archiv-cola.json", cola(sys.argv[1])), ("export/archiv-wasser.json", water(sys.argv[2], aliases))):
        with open(name, "w", encoding="utf-8") as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)
        print(name, len(archive["items"]), "Dinge,", len(archive["ratings"]), "Wertungen")
