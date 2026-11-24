"""Finished tastings, kept as one self-describing JSON file each.

Every past tasting had its own questions, so an archive file brings its
questions along. The results page is built from that description alone, which
is what lets cola, water and every later tasting share one page. The format is
described in docs/ARCHITECTURE.md.
"""

import re
from statistics import mean, pstdev

from .stats import EPSILON, MIN_SHARED_FOR_CORRELATION, de, pearson

FORMAT = "tasting-archive/1"
ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
MAX_ITEMS = 200
MAX_RATINGS = 5000


def validate(archive):
    """Returns what is wrong with an archive file, or None if it can be used."""
    if not isinstance(archive, dict) or archive.get("format") != FORMAT:
        return f"Das ist keine Archivdatei (format muss „{FORMAT}“ sein)."
    if not isinstance(archive.get("id"), str) or not ID_PATTERN.fullmatch(archive["id"]):
        return "Die Id fehlt oder enthält mehr als Kleinbuchstaben, Ziffern und Bindestriche."
    if not isinstance(archive.get("title"), str) or not archive["title"].strip():
        return "Der Titel fehlt."
    scale = archive.get("scale")
    if not (isinstance(scale, dict) and isinstance(scale.get("min"), int) and isinstance(scale.get("max"), int)
            and scale["min"] < scale["max"]):
        return "Die Skala (scale.min, scale.max) fehlt."
    sections = archive.get("sections")
    if not isinstance(sections, list) or not sections:
        return "Die Fragen (sections) fehlen."
    keys = set()
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("criteria"), list):
            return "Ein Abschnitt hat keine Kriterien."
        for criterion in section["criteria"]:
            if not isinstance(criterion, dict) or not isinstance(criterion.get("key"), str) or not criterion.get("label"):
                return "Ein Kriterium hat keinen Schlüssel oder keine Beschriftung."
            keys.add(criterion["key"])
    if archive.get("ranking") not in keys:
        return "Das Kriterium für die Rangliste (ranking) gibt es nicht."
    items = archive.get("items")
    if not isinstance(items, list) or not items or len(items) > MAX_ITEMS:
        return "Die Liste der verkosteten Dinge (items) fehlt oder ist zu lang."
    item_ids = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("name"), str):
            return "Ein verkostetes Ding hat keine Id oder keinen Namen."
        item_ids.add(item["id"])
    ratings = archive.get("ratings")
    if not isinstance(ratings, list) or not ratings or len(ratings) > MAX_RATINGS:
        return "Die Wertungen fehlen oder sind zu viele."
    low, high = scale["min"], scale["max"]
    for rating in ratings:
        if not isinstance(rating, dict) or not isinstance(rating.get("person"), str) or rating.get("item") not in item_ids:
            return "Eine Wertung gehört zu keiner Person oder keinem bekannten Ding."
        scores = rating.get("scores")
        if not isinstance(scores, dict):
            return "Eine Wertung hat keine Punkte."
        for key, value in scores.items():
            if key not in keys or not (value is None or (isinstance(value, int) and low <= value <= high)):
                return f"Eine Wertung hat einen ungültigen Wert bei „{key}“."
        if not isinstance(scores.get(archive["ranking"]), int):
            return "Einer Wertung fehlt der Wert für die Rangliste."
    for award in archive.get("awards", []):
        terms = award.get("terms") if isinstance(award, dict) else None
        if not award.get("title") or not isinstance(terms, list) or not terms or award.get("best") not in ("max", "min"):
            return "Eine Auszeichnung ist unvollständig."
        if any(not isinstance(t, dict) or t.get("key") not in keys for t in terms):
            return "Eine Auszeichnung nutzt ein unbekanntes Kriterium."
    return None


def summary(archive):
    """What the tasting overview shows on a card."""
    result = compute(archive)
    return {
        "id": archive["id"],
        "title": archive["title"],
        "subtitle": archive.get("subtitle", ""),
        "date": archive.get("date"),
        "number": archive.get("number"),
        "items": len(archive["items"]),
        "people": len(result["people"]),
        "ratings": len(archive["ratings"]),
        "winner": result["ranking"][0]["name"] if result["ranking"] else None,
    }


def _criteria(archive):
    return [c for section in archive["sections"] for c in section["criteria"]]


def _winners(rows, value, best):
    scored = [(row, value(row)) for row in rows]
    scored = [(row, v) for row, v in scored if v is not None]
    if not scored:
        return [], None
    top = best(v for _, v in scored)
    return [row for row, v in scored if abs(v - top) < EPSILON], top


def _term_value(scores, term, scale):
    value = scores.get(term["key"])
    if value is None:
        return None
    # "invert" turns a low score into a high one, e.g. acidic for a pH scale.
    return scale["min"] + scale["max"] - value if term.get("invert") else value


def compute(archive):
    """Everything an archive's results page shows."""
    scale = archive["scale"]
    criteria = _criteria(archive)
    keys = [c["key"] for c in criteria]
    rank_key = archive["ranking"]
    tie_key = archive.get("tiebreak") if archive.get("tiebreak") in keys else None
    items = {item["id"]: item for item in archive["items"]}
    ratings = archive["ratings"]
    people = sorted({r["person"] for r in ratings})

    def averages(rows):
        result = {}
        for key in keys:
            values = [r["scores"].get(key) for r in rows]
            values = [v for v in values if v is not None]
            result[key] = mean(values) if values else None
        return result

    by_item = {item_id: [r for r in ratings if r["item"] == item_id] for item_id in items}
    item_rows = []
    for item_id, rows in by_item.items():
        if not rows:
            continue
        values = [r["scores"][rank_key] for r in rows]
        item_rows.append({
            "id": item_id,
            "name": items[item_id]["name"],
            "group": items[item_id].get("group"),
            "raters": len(rows),
            "value": mean(values),
            "spread": pstdev(values) if len(values) >= 2 else None,
            "averages": averages(rows),
            "by_person": {r["person"]: r["scores"][rank_key] for r in rows},
            # Optional: what 100 g or 100 ml cost, for tastings that recorded prices.
            "price_per_100": items[item_id].get("price_per_100"),
            "unit": items[item_id].get("unit", "g"),
        })
    item_rows.sort(key=lambda row: (-row["value"], -(row["averages"].get(tie_key) or 0) if tie_key else 0, row["name"]))
    for position, row in enumerate(item_rows, start=1):
        row["rank"] = position
    overall = averages(ratings)

    groups = []
    group_names = sorted({row["group"] for row in item_rows if row["group"]})
    if len(group_names) >= 2:
        for name in group_names:
            rows = [r for r in ratings if items[r["item"]].get("group") == name]
            groups.append({"name": name, "items": sum(1 for row in item_rows if row["group"] == name),
                           "averages": averages(rows)})

    person_rows = []
    for person in people:
        rows = [r for r in ratings if r["person"] == person]
        values = [r["scores"][rank_key] for r in rows]
        best = max(rows, key=lambda r: r["scores"][rank_key])
        worst = min(rows, key=lambda r: r["scores"][rank_key])
        deviations = []
        for r in rows:
            others = [o["scores"][rank_key] for o in by_item[r["item"]] if o["person"] != person]
            if others:
                deviations.append(abs(r["scores"][rank_key] - mean(others)))
        person_rows.append({
            "name": person,
            "ratings": len(rows),
            "average": mean(values),
            "deviation": mean(deviations) if deviations else None,
            "best": {"name": items[best["item"]]["name"], "value": best["scores"][rank_key]},
            "worst": {"name": items[worst["item"]]["name"], "value": worst["scores"][rank_key]},
            "averages": averages(rows),
        })

    # Taste twins over items both people rated, averaging repeat tastings.
    scores = {p: {} for p in people}
    for row in item_rows:
        for person, value in row["by_person"].items():
            scores[person][row["id"]] = value
    matrix, pairs = [], []
    for a in people:
        line = []
        for b in people:
            if a == b:
                line.append(None)
                continue
            shared = sorted(set(scores[a]) & set(scores[b]))
            r = None
            if len(shared) >= MIN_SHARED_FOR_CORRELATION:
                r = pearson([scores[a][i] for i in shared], [scores[b][i] for i in shared])
            line.append(r)
            if r is not None and a < b:
                pairs.append({"a": a, "b": b, "r": r, "shared": len(shared)})
        matrix.append(line)
    pairs.sort(key=lambda p: -p["r"])

    flags = []
    for flag in archive.get("flags", []):
        marked = [r["scores"][rank_key] for r in ratings if r.get("flags", {}).get(flag["key"])]
        unmarked = [r["scores"][rank_key] for r in ratings if not r.get("flags", {}).get(flag["key"])]
        if marked and unmarked:
            flags.append({**flag, "with": mean(marked), "without": mean(unmarked),
                          "count": len(marked), "people": sorted({r["person"] for r in ratings if r.get("flags", {}).get(flag["key"])})})

    awards = []
    for award in archive.get("awards", []):
        best = max if award["best"] == "max" else min
        def item_value(row, terms=award["terms"]):
            values = [_term_value(r["scores"], t, scale) for r in by_item[row["id"]] for t in terms]
            values = [v for v in values if v is not None]
            return mean(values) if values else None
        winners, top = _winners(item_rows, item_value, best)
        if winners:
            awards.append({"title": award["title"], "line": award.get("line", ""), "kind": "item",
                           "winner": " & ".join(w["name"] for w in winners),
                           "stat": f"Ø {de(top)} / {scale['max']}"})
    rank_label = next(c["label"] for c in criteria if c["key"] == rank_key)
    priced = [r for r in item_rows if isinstance(r["price_per_100"], (int, float)) and r["price_per_100"] > 0]
    if len(priced) >= 2:
        # Most of the ranking score per euro: a good one that costs little.
        winners, _ = _winners(priced, lambda r: r["value"] / r["price_per_100"], max)
        if winners:
            top = winners[0]
            awards.append({"title": "Das Schnäppchen", "line": "Viel Genuss für wenig Gold.", "kind": "item",
                           "winner": " & ".join(w["name"] for w in winners),
                           "stat": f"Ø {de(top['value'])} für {de(top['price_per_100'])} €/100 {top['unit']}"})
    if len(item_rows) >= 2:
        winners, top = _winners([r for r in item_rows if r["spread"] is not None], lambda r: r["spread"], max)
        if winners:
            awards.append({"title": "Der Zankapfel", "line": "Die halbe Tafel jubelt, die andere Hälfte protestiert.",
                           "kind": "item", "winner": " & ".join(w["name"] for w in winners),
                           "stat": f"Standardabweichung {de(top)}"})
    if len(person_rows) >= 2:
        for title, line, value, best, stat in (
            ("Großzügigster Gaumen", "Findet in jedem Glas etwas Gutes.", lambda p: p["average"], max,
             lambda v: f"Ø {rank_label} {de(v)}"),
            ("Härteste Kritik", "Kein Getränk ist gut genug. Respekt.", lambda p: p["average"], min,
             lambda v: f"Ø {rank_label} {de(v)}"),
            ("Ketzer der Tafel", "Liegt am weitesten vom Rest entfernt.", lambda p: p["deviation"], max,
             lambda v: f"Ø {de(v)} Punkte von den anderen entfernt"),
        ):
            winners, top = _winners(person_rows, value, best)
            if winners:
                awards.append({"title": title, "line": line, "kind": "person",
                               "winner": " & ".join(w["name"] for w in winners), "stat": stat(top)})

    notes = [
        {"person": r["person"], "item": items[r["item"]]["name"], "text": r["notes"], "value": r["scores"][rank_key]}
        for r in ratings if r.get("notes")
    ]
    notes.sort(key=lambda n: (n["item"], n["person"]))

    return {
        "id": archive["id"],
        "title": archive["title"],
        "subtitle": archive.get("subtitle", ""),
        "date": archive.get("date"),
        "intro": archive.get("intro", ""),
        "scale": scale,
        "sections": archive["sections"],
        "ranking_key": rank_key,
        "ranking_label": rank_label,
        "summary": {
            "items": len(item_rows),
            "people": len(people),
            "ratings": len(ratings),
            "average": mean(r["scores"][rank_key] for r in ratings),
        },
        "ranking": [{k: v for k, v in row.items() if k != "by_person"} for row in item_rows],
        "overall": overall,
        "groups": groups,
        "group_label": archive.get("group_label", "Lager"),
        "people": person_rows,
        "twins": {"names": people, "matrix": matrix, "closest": pairs[0] if pairs else None,
                  "furthest": pairs[-1] if len(pairs) >= 2 else None, "min_shared": MIN_SHARED_FOR_CORRELATION},
        "flags": flags,
        "awards": awards,
        "notes": notes,
    }
