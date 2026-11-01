"""Turns raw ratings into rankings, comparisons and awards. No web code in here."""

import difflib
import math
import re
from collections import Counter
from statistics import mean, pstdev

from .catalog import NPCS, POINTS_BRAND, POINTS_FLAVOR, SCALE_KEYS, SCALE_SHORT

MIN_SHARED_FOR_CORRELATION = 3
EPSILON = 1e-9


def de(value, digits=1):
    return f"{value:.{digits}f}".replace(".", ",")


def euro(value):
    return f"{de(value, 2)} €"


def chip_label(chip):
    return f"{chip['brand']} {chip['name']}".strip() if chip.get("brand") else chip["name"]


def _normalize_brand(text):
    return re.sub(r"[^a-z0-9äöüß]", "", (text or "").lower())


def brand_matches(guess, actual):
    guess, actual = _normalize_brand(guess), _normalize_brand(actual)
    if len(guess) < 3 or not actual:
        return False
    if guess in actual or actual in guess:
        return True
    return difflib.SequenceMatcher(None, guess, actual).ratio() >= 0.8


def guess_hits(rating, chip, player_id):
    """(flavor right, brand right). Whoever brought a chip can't score on it."""
    if chip.get("added_by") == player_id:
        return False, False
    flavor = bool(rating.get("guess_flavor")) and rating["guess_flavor"] == chip.get("flavor_type")
    return flavor, brand_matches(rating.get("guess_brand"), chip.get("brand"))


def guess_points(rating, chip, player_id):
    flavor, brand = guess_hits(rating, chip, player_id)
    return POINTS_FLAVOR * flavor + POINTS_BRAND * brand


def pearson(xs, ys):
    if len(xs) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denominator = math.sqrt(sum(a * a for a in dx) * sum(b * b for b in dy))
    if denominator == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denominator


def _chip_stats(chip, ratings):
    enjoyment = [r["enjoyment"] for r in ratings.values()]
    scales = {
        key: mean(r["scores"][key] for r in ratings.values()) if ratings else None
        for key in SCALE_KEYS
    }
    coins = [r["coins"] for r in ratings.values() if r.get("coins") is not None]
    npcs = Counter(r["npc"] for r in ratings.values() if r.get("npc"))
    return {
        "id": chip["id"],
        "bowl": chip["bowl"],
        "label": chip_label(chip),
        "name": chip["name"],
        "brand": chip.get("brand", ""),
        "flavor_type": chip.get("flavor_type", ""),
        "own_brand": bool(chip.get("own_brand")),
        "price": chip.get("price"),
        "raters": len(ratings),
        "enjoyment": mean(enjoyment) if enjoyment else None,
        "spread": pstdev(enjoyment) if len(enjoyment) >= 2 else None,
        "scales": scales,
        "coins": mean(coins) if coins else None,
        "contracts": sum(1 for r in ratings.values() if r.get("contract") is True),
        "npc": [{"name": n, "votes": npcs[n]} for n in NPCS if npcs[n]],
    }


def rank_key(stat):
    return (-stat["enjoyment"], -stat["scales"]["harmony"], stat["label"])


def ranked_chip_ids(tasting):
    """Chip ids from best to worst. Chips nobody rated are left out."""
    rated = [
        _chip_stats(chip, tasting["ratings"].get(chip["id"], {}))
        for chip in tasting["chips"]
        if tasting["ratings"].get(chip["id"])
    ]
    return [s["id"] for s in sorted(rated, key=rank_key)]


def _winners(items, value, best):
    """All items tied for the best value. `best` is max or min."""
    candidates = [(i, value(i)) for i in items]
    candidates = [(i, v) for i, v in candidates if v is not None]
    if not candidates:
        return [], None
    top = best(v for _, v in candidates)
    return [i for i, v in candidates if abs(v - top) < EPSILON], top


def _player_awards(players, per_player, guessing):
    def score_mean(pid):
        values = per_player[pid]["enjoyment"]
        return mean(values) if values else None

    def deviation(pid):
        values = per_player[pid]["deviations"]
        return mean(values) if values else None

    def fate(pid):
        return per_player[pid]["crits"] or None

    def poet(pid):
        return per_player[pid]["note_chars"] or None

    def guess(pid):
        return guessing.get(pid) or None

    definitions = [
        ("arkhan", "Arkhan der Grausame", "Der härteste Kritiker am Tisch. Selbst Tiamat wäre ihm zu lasch.",
         score_mean, min, lambda v: f"Ø Genuss {de(v)} / 20"),
        ("lulu", "Lulus Herz", "Findet in jedem Krümel das Gute. Die Hölle hat keine Macht über dieses Gemüt.",
         score_mean, max, lambda v: f"Ø Genuss {de(v)} / 20"),
        ("thavius", "Thavius der Ketzer", "Predigt gegen jede Mehrheit und verkauft der Gruppe das Gegenteil.",
         deviation, max, lambda v: f"Ø {de(v)} Punkte von der Gruppe entfernt"),
        ("hellriders", "Stimme der Höllenreiter", "Reitet immer mit der Truppe. Geschmack im Gleichschritt.",
         deviation, min, lambda v: f"Ø {de(v)} Punkte von der Gruppe entfernt"),
        ("maggie", "Mad Maggies Auge", "Blind probiert, trotzdem alles gesehen. Unheimlich.",
         guess, max, lambda v: f"{v} Orakelpunkte"),
        ("bard", "Barde der Neun Höllen", "Hat mehr geschrieben als gekaut.",
         poet, max, lambda v: f"{v} Zeichen Notizen"),
        ("fate", "Vom Schicksal gezeichnet", "Kennt keine Mitte: Für diese Person gibt es nur Triumph oder Untergang.",
         fate, max, lambda v: f"{v} × Nat 1 oder Nat 20"),
    ]
    awards = []
    for key, title, line, value, best, stat in definitions:
        winners, top = _winners(players, lambda p: value(p["id"]), best)
        if winners:
            awards.append({
                "key": key, "kind": "player", "title": title, "line": line,
                "winner": " & ".join(p["name"] for p in winners), "stat": stat(top),
            })
    return awards


def _chip_awards(chips):
    rated = [c for c in chips if c["raters"]]

    def bargain(c):
        if c["price"] and c["enjoyment"] is not None:
            return c["enjoyment"] / c["price"]
        return None

    def contracts(c):
        return c["contracts"] or None

    def scale(key):
        return lambda c: c["scales"][key]

    definitions = [
        ("crown", "Krone von Avernus", "Der unangefochtene Herrscher über alle Schalen.",
         lambda c: c["enjoyment"], max, lambda v: f"Ø Genuss {de(v)} / 20", 1),
        ("zariel", "Zariels Zorn", "Brennt länger als der Blutkrieg.",
         scale("heat"), max, lambda v: f"Ø Höllenfeuer {de(v)} / 5", 1),
        ("stealth", "Patzer beim Heimlichkeitswurf", "Die ganze Stadt Elturel weiß jetzt, wo ihr seid.",
         scale("crunch"), max, lambda v: f"Ø Crunch {de(v)} / 5", 1),
        ("styx", "Fluss Styx", "Nach einer Handvoll erinnert sich niemand mehr an saubere Finger.",
         scale("grease"), max, lambda v: f"Ø Styx-Faktor {de(v)} / 5", 1),
        ("bloodwar", "Der Blutkrieg", "Spaltet die Gruppe wie Teufel und Dämonen.",
         lambda c: c["spread"], max, lambda v: f"Standardabweichung {de(v)} Punkte", 1),
        ("bargain", "Seelenmünzen-Schnäppchen", "So viel Genuss für so wenig Gold. Verdächtig.",
         bargain, max, lambda v: f"{de(v)} Genusspunkte pro Euro", 1),
        ("contract", "Der unterschriebene Vertrag", "Ein Jahr lang nur diese Chips. Die Unterschriften sind blutig, aber gültig.",
         contracts, max, lambda v: f"{v} × unterschrieben", 1),
        ("elturel", "Der Fall von Elturel", "Auch diese Chips stürzten in die Hölle. Niemand hat sie aufgefangen.",
         lambda c: c["enjoyment"], min, lambda v: f"Ø Genuss {de(v)} / 20", 2),
    ]
    awards = []
    for key, title, line, value, best, stat, min_chips in definitions:
        if len(rated) < min_chips:
            continue
        winners, top = _winners(rated, value, best)
        if winners:
            awards.append({
                "key": key, "kind": "chip", "title": title, "line": line,
                "winner": " & ".join(c["label"] for c in winners), "stat": stat(top),
            })
    return awards


def _battle(chips, group_of, min_groups=2):
    groups = {}
    for chip in chips:
        if chip["enjoyment"] is not None and group_of(chip):
            groups.setdefault(group_of(chip), []).append(chip["enjoyment"])
    rows = [
        {"label": label, "value": mean(values), "chips": len(values)}
        for label, values in groups.items()
    ]
    rows.sort(key=lambda r: -r["value"])
    return rows if len(rows) >= min_groups else []


def compute(tasting, users):
    """Everything the results page shows. Only call this once results are public."""
    chips_raw = tasting["chips"]
    all_ratings = tasting["ratings"]
    players = [
        {"id": uid, "name": u["name"]}
        for uid, u in users.items()
        if u.get("role") == "player"
    ]
    known = {p["id"] for p in players}
    # A rating can outlive its login if a player was removed from users.json.
    names = {uid: u["name"] for uid, u in users.items()}

    chips = [_chip_stats(c, all_ratings.get(c["id"], {})) for c in chips_raw]
    chips.sort(key=lambda c: (c["enjoyment"] is None, rank_key(c) if c["enjoyment"] is not None else ()))
    for position, chip in enumerate(chips, start=1):
        chip["rank"] = position if chip["enjoyment"] is not None else None

    per_player = {
        p["id"]: {"enjoyment": [], "deviations": [], "crits": 0, "note_chars": 0, "best": None, "worst": None}
        for p in players
    }
    by_id = {c["id"]: c for c in chips_raw}
    scores_by_player = {p["id"]: {} for p in players}
    guessing = {p["id"]: 0 for p in players}
    guess_detail = {p["id"]: {"flavor": 0, "brand": 0} for p in players}
    notes = []

    for chip_id, ratings in all_ratings.items():
        chip = by_id.get(chip_id)
        if chip is None:
            continue
        for pid, rating in ratings.items():
            if pid in known:
                entry = per_player[pid]
                value = rating["enjoyment"]
                entry["enjoyment"].append(value)
                scores_by_player[pid][chip_id] = value
                if value in (1, 20):
                    entry["crits"] += 1
                entry["note_chars"] += len(rating.get("notes") or "")
                others = [r["enjoyment"] for other, r in ratings.items() if other != pid]
                if others:
                    entry["deviations"].append(abs(value - mean(others)))
                if entry["best"] is None or value > entry["best"]["value"]:
                    entry["best"] = {"label": chip_label(chip), "value": value}
                if entry["worst"] is None or value < entry["worst"]["value"]:
                    entry["worst"] = {"label": chip_label(chip), "value": value}
                guessing[pid] += guess_points(rating, chip, pid)
                flavor_hit, brand_hit = guess_hits(rating, chip, pid)
                guess_detail[pid]["flavor"] += flavor_hit
                guess_detail[pid]["brand"] += brand_hit
            if rating.get("notes"):
                notes.append({
                    "player": names.get(pid, pid),
                    "chip": chip_label(chip),
                    "bowl": chip["bowl"],
                    "text": rating["notes"],
                    "enjoyment": rating["enjoyment"],
                })
    notes.sort(key=lambda n: (n["bowl"], n["player"]))

    guess_board = sorted(
        (
            {
                "name": p["name"], "points": guessing[p["id"]],
                "flavor_hits": guess_detail[p["id"]]["flavor"],
                "brand_hits": guess_detail[p["id"]]["brand"],
            }
            for p in players
        ),
        key=lambda r: (-r["points"], r["name"]),
    )

    # Taste twins: how similarly two players rank chips (Pearson over shared chips).
    ids = [p["id"] for p in players]
    matrix = []
    pairs = []
    for a in ids:
        row = []
        for b in ids:
            if a == b:
                row.append(None)
                continue
            shared = sorted(set(scores_by_player[a]) & set(scores_by_player[b]))
            r = None
            if len(shared) >= MIN_SHARED_FOR_CORRELATION:
                r = pearson([scores_by_player[a][c] for c in shared], [scores_by_player[b][c] for c in shared])
            row.append(r)
            if r is not None and a < b:
                pairs.append({"a": names[a], "b": names[b], "r": r, "shared": len(shared)})
        matrix.append(row)
    pairs.sort(key=lambda p: -p["r"])

    tops = [
        {
            "name": p["name"],
            "best": per_player[p["id"]]["best"],
            "worst": per_player[p["id"]]["worst"],
            "average": mean(per_player[p["id"]]["enjoyment"]) if per_player[p["id"]]["enjoyment"] else None,
            "rated": len(per_player[p["id"]]["enjoyment"]),
        }
        for p in players
    ]

    all_values = [r["enjoyment"] for ratings in all_ratings.values() for r in ratings.values()]
    scale_averages = {}
    rated_chips = [c for c in chips if c["raters"]]
    if rated_chips:
        scale_averages = {k: mean(c["scales"][k] for c in rated_chips) for k in SCALE_KEYS}

    awards = _chip_awards(chips) + _player_awards(players, per_player, guessing)

    return {
        "summary": {
            "chips": len(chips_raw),
            "ratings": len(all_values),
            "average": mean(all_values) if all_values else None,
            "nat20": sum(1 for v in all_values if v == 20),
            "nat1": sum(1 for v in all_values if v == 1),
        },
        "chips": chips,
        "scale_keys": SCALE_KEYS,
        "scale_labels": [SCALE_SHORT[k] for k in SCALE_KEYS],
        "scale_averages": scale_averages,
        "battles": {
            "flavor": _battle(chips, lambda c: c["flavor_type"]),
            "brand": _battle(chips, lambda c: "Eigenmarke" if c["own_brand"] else "Markenprodukt"),
        },
        "guessing": {"board": guess_board, "points_flavor": POINTS_FLAVOR, "points_brand": POINTS_BRAND},
        "twins": {
            "names": [names[i] for i in ids],
            "matrix": matrix,
            "closest": pairs[0] if pairs else None,
            "furthest": pairs[-1] if len(pairs) >= 2 else None,
            "min_shared": MIN_SHARED_FOR_CORRELATION,
        },
        "tops": tops,
        "awards": awards,
        "notes": notes,
    }
