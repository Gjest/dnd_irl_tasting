"""Turns raw ratings into rankings, comparisons and awards. No web code in here."""

import difflib
import math
import re
from statistics import mean, pstdev

from .catalog import (
    ADDICTION_TIERS,
    ALIGNMENTS,
    ATTRIBUTES,
    CONDITIONS,
    POINTS_BRAND,
    POINTS_FLAVOR,
    PRICE_ADDICTION_VERDICTS,
    PRICE_GUESS_VERDICTS,
    SCALE_KEYS,
    SCALE_SHORT,
)

MIN_SHARED_FOR_CORRELATION = 3
EPSILON = 1e-9
# How far an axis score must leave the middle to count as lawful/chaotic or good/evil.
ALIGNMENT_THRESHOLD = 0.12
PRICE_READ_BAR = 0.3


def de(value, digits=1):
    return f"{value:.{digits}f}".replace(".", ",")


def euro(value):
    return f"{de(value, 2)} €"


def chip_label(chip):
    # Without a name of its own, "Pringles" plus its flavor says what it is.
    parts = [chip.get("brand"), chip.get("name") or chip.get("flavor_type")]
    return " ".join(p.strip() for p in parts if p and p.strip()) or "Unbenannte Tüte"


def normalize_text(text):
    return re.sub(r"[^a-z0-9äöüß]", "", (text or "").lower())


def similar(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.8


def brand_matches(guess, actual):
    guess, actual = normalize_text(guess), normalize_text(actual)
    if len(guess) < 3 or not actual:
        return False
    if guess in actual or actual in guess:
        return True
    return similar(guess, actual)


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


def price_per_100g(chip):
    if chip.get("price") is None or not chip.get("weight"):
        return None
    return chip["price"] / chip["weight"] * 100


def addiction_tier(dc):
    """The status effect of a DC. A group average can sit between whole numbers."""
    current = ADDICTION_TIERS[0]
    for tier in ADDICTION_TIERS:
        if dc >= tier["from"]:
            current = tier
    return {"name": current["name"], "line": current["line"]}


def _verdict(verdicts, r):
    return next(v["line"] for v in verdicts if r >= v["from"])


def _alignment(law, good):
    """Turns two axis scores (positive is lawful, positive is good) into a D&D alignment."""
    def side(value, positive, negative):
        if value >= ALIGNMENT_THRESHOLD:
            return positive
        return negative if value <= -ALIGNMENT_THRESHOLD else "neutral"

    key = (side(law, "lawful", "chaotic"), side(good, "good", "evil"))
    return {"law": key[0], "good": key[1], **ALIGNMENTS[key]}


def _chip_alignment(chip):
    def scale(key):
        return (chip["scales"][key] - 3) / 2

    # A group that agrees on a chip is order; a chip that splits the table is chaos.
    discord = (chip["spread"] - 4) / 4 if chip["spread"] is not None else 0
    law = mean([scale("integrity"), scale("harmony"), -scale("coverage"), -discord])
    good = mean([scale("potato"), scale("harmony"), -scale("artificial"), -scale("heat"), -scale("thirst")])
    return _alignment(law, good)


def _character_sheet(chip):
    sheet = []
    for attribute in ATTRIBUTES:
        values = [chip["scales"][k] for k in attribute["for"]] + [6 - chip["scales"][k] for k in attribute["against"]]
        # Scales run from 1 to 5, D&D attributes from 3 to 18.
        score = round(3 + (mean(values) - 1) * 15 / 4)
        sheet.append({"label": attribute["label"], "name": attribute["name"], "score": score, "modifier": (score - 10) // 2})
    return sheet


def _conditions(chip):
    found = []
    for condition in CONDITIONS:
        value = chip["scales"][condition["scale"]]
        if value >= condition.get("min", math.inf) or value <= condition.get("max", -math.inf):
            found.append({"name": condition["name"], "line": condition["line"]})
    return found


def _chip_stats(chip, ratings):
    dc = [r["dc"] for r in ratings.values()]
    scales = {
        key: mean(r["scores"][key] for r in ratings.values()) if ratings else None
        for key in SCALE_KEYS
    }
    coins = [r["coins"] for r in ratings.values() if r.get("coins") is not None]
    return {
        "id": chip["id"],
        "bowl": chip["bowl"],
        "label": chip_label(chip),
        "name": chip["name"],
        "brand": chip.get("brand", ""),
        "flavor_type": chip.get("flavor_type", ""),
        "own_brand": bool(chip.get("own_brand")),
        "image": chip.get("image"),
        "price": chip.get("price"),
        "weight": chip.get("weight"),
        "price_100g": price_per_100g(chip),
        "raters": len(ratings),
        "dc": mean(dc) if dc else None,
        "spread": pstdev(dc) if len(dc) >= 2 else None,
        "scales": scales,
        "coins": mean(coins) if coins else None,
        "contracts": sum(1 for r in ratings.values() if r.get("contract") is True),
    }


def rank_key(stat):
    return (-stat["dc"], -stat["scales"]["harmony"], stat["label"])


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


def _player_awards(players, per_player, guessing, price_reads):
    def score_mean(pid):
        values = per_player[pid]["dc"]
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

    # Only a real hit or a real miss earns these, not the best of a mediocre table.
    def good_price_read(pid):
        r = price_reads.get(pid)
        return r if r is not None and r >= PRICE_READ_BAR else None

    def bad_price_read(pid):
        r = price_reads.get(pid)
        return r if r is not None and r < PRICE_READ_BAR else None

    definitions = [
        ("arkhan", "Arkhan der Grausame", "Der härteste Kritiker am Tisch. Selbst Tiamat wäre ihm zu lasch.",
         score_mean, min, lambda v: f"Ø Sucht-DC {de(v)}"),
        ("lulu", "Lulus Herz", "Findet in jedem Krümel das Gute. Die Hölle hat keine Macht über dieses Gemüt.",
         score_mean, max, lambda v: f"Ø Sucht-DC {de(v)}"),
        ("thavius", "Thavius der Ketzer", "Predigt gegen jede Mehrheit und verkauft der Gruppe das Gegenteil.",
         deviation, max, lambda v: f"Ø {de(v)} Punkte von der Gruppe entfernt"),
        ("hellriders", "Stimme der Höllenreiter", "Reitet immer mit der Truppe. Geschmack im Gleichschritt.",
         deviation, min, lambda v: f"Ø {de(v)} Punkte von der Gruppe entfernt"),
        ("maggie", "Mad Maggies Auge", "Blind probiert, trotzdem alles gesehen. Unheimlich.",
         guess, max, lambda v: f"{v} Orakelpunkte"),
        ("bard", "Barde der Neun Höllen", "Hat mehr geschrieben als gekaut.",
         poet, max, lambda v: f"{v} Zeichen Notizen"),
        ("fate", "Vom Schicksal gezeichnet", "Kennt keine Mitte: Für diese Person gibt es nur Immunität oder Unterwerfung.",
         fate, max, lambda v: f"{v} × DC 1 oder DC 20"),
        ("accountant", "Asmodeus' Buchhalter", "Riecht den Preis pro 100 Gramm durch die Schale. Die Hölle stellt ein.",
         good_price_read, max, lambda v: f"Korrelation {de(v, 2)} mit dem echten Preis"),
        ("mammon", "Von Mammon betrogen", "Hält Ramsch für Gold und Gold für Ramsch. Bitte hier unterschreiben.",
         bad_price_read, min, lambda v: f"Korrelation {de(v, 2)} mit dem echten Preis"),
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
        if c["price_100g"] and c["dc"] is not None:
            return c["dc"] / c["price_100g"]
        return None

    def conditions(c):
        return len(c["conditions"]) or None

    def price_gap(c):
        return c["price_gap"]

    def contracts(c):
        return c["contracts"] or None

    def scale(key):
        return lambda c: c["scales"][key]

    definitions = [
        ("crown", "Krone von Avernus", "Der unangefochtene Herrscher über alle Schalen.",
         lambda c: c["dc"], max, lambda v: f"Ø Sucht-DC {de(v)}", 1),
        ("zariel", "Zariels Zorn", "Brennt länger als der Blutkrieg.",
         scale("heat"), max, lambda v: f"Ø Höllenfeuer {de(v)} / 5", 1),
        ("stealth", "Patzer beim Heimlichkeitswurf", "Die ganze Stadt Elturel weiß jetzt, wo ihr seid.",
         scale("crunch"), max, lambda v: f"Ø Crunch {de(v)} / 5", 1),
        ("styx", "Fluss Styx", "Nach einer Handvoll erinnert sich niemand mehr an saubere Finger.",
         scale("grease"), max, lambda v: f"Ø Styx-Faktor {de(v)} / 5", 1),
        ("bloodwar", "Der Blutkrieg", "Spaltet die Gruppe wie Teufel und Dämonen.",
         lambda c: c["spread"], max, lambda v: f"Standardabweichung {de(v)} Punkte", 1),
        ("bargain", "Seelenmünzen-Schnäppchen", "So viel Sucht für so wenig Gold. Verdächtig.",
         bargain, max, lambda v: f"{de(v)} DC pro Euro je 100 g", 1),
        ("conditions", "Wandelnde Zustandsliste", "Wer das isst, braucht einen Kleriker und eine zweite Spielleitung.",
         conditions, max, lambda v: f"{v} Zustände", 1),
        ("impostor", "Thavius' Mogelpackung", "Wirkt wie Hofstaat, kostet wie Ramsch. Predigen kann sie.",
         price_gap, max, lambda v: f"Überschätzt um {de(v)} Standardabweichungen", 1),
        ("hidden_gem", "Der verkannte Schatz", "Sieht billig aus, ist es aber nicht. Ein Mimik unter den Chips.",
         price_gap, min, lambda v: f"Unterschätzt um {de(abs(v))} Standardabweichungen", 1),
        ("contract", "Der unterschriebene Vertrag", "Ein Jahr lang nur diese Chips. Die Unterschriften sind blutig, aber gültig.",
         contracts, max, lambda v: f"{v} × unterschrieben", 1),
        ("elturel", "Der Fall von Elturel", "Auch diese Chips stürzten in die Hölle. Niemand hat sie aufgefangen.",
         lambda c: c["dc"], min, lambda v: f"Ø Sucht-DC {de(v)}", 2),
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


def _price_stats(chips, players, all_ratings):
    """How well blind coin guesses and addiction line up with the real price per 100 g."""
    known = [c for c in chips if c["price_100g"] is not None]
    guessed = [c for c in known if c["coins"] is not None]
    addictive = [c for c in known if c["dc"] is not None]

    guess_r = dc_r = None
    if len(guessed) >= MIN_SHARED_FOR_CORRELATION:
        coins = [c["coins"] for c in guessed]
        prices = [c["price_100g"] for c in guessed]
        guess_r = pearson(coins, prices)
        if pstdev(coins) > EPSILON and pstdev(prices) > EPSILON:
            for chip in guessed:
                # Coins and euros have no common unit, so both become "how far from typical".
                chip["price_gap"] = (chip["coins"] - mean(coins)) / pstdev(coins) - (chip["price_100g"] - mean(prices)) / pstdev(prices)
    if len(addictive) >= MIN_SHARED_FOR_CORRELATION:
        dc_r = pearson([c["dc"] for c in addictive], [c["price_100g"] for c in addictive])

    readers = []
    reads = {}
    for player in players:
        pairs = [
            (rating["coins"], chip["price_100g"])
            for chip in known
            for rating in [all_ratings.get(chip["id"], {}).get(player["id"])]
            if rating and rating.get("coins") is not None
        ]
        if len(pairs) >= MIN_SHARED_FOR_CORRELATION:
            r = pearson([a for a, _ in pairs], [b for _, b in pairs])
            if r is not None:
                reads[player["id"]] = r
                readers.append({"name": player["name"], "r": r, "chips": len(pairs)})
    readers.sort(key=lambda row: (-row["r"], row["name"]))

    return reads, {
        "guess_r": guess_r,
        "guess_verdict": _verdict(PRICE_GUESS_VERDICTS, guess_r) if guess_r is not None else None,
        "dc_r": dc_r,
        "dc_verdict": _verdict(PRICE_ADDICTION_VERDICTS, dc_r) if dc_r is not None else None,
        "readers": readers,
        "min_chips": MIN_SHARED_FOR_CORRELATION,
    }


def _player_alignments(players, per_player, all_ratings):
    rows = []
    active = [p for p in players if per_player[p["id"]]["dc"]]
    if not active:
        return rows
    group_dc = mean(mean(per_player[p["id"]]["dc"]) for p in active)
    deviations = [mean(per_player[p["id"]]["deviations"]) for p in active if per_player[p["id"]]["deviations"]]
    group_deviation = mean(deviations) if deviations else 0
    for player in active:
        entry = per_player[player["id"]]
        signed = sum(
            1 for ratings in all_ratings.values()
            if ratings.get(player["id"], {}).get("contract") is True
        )
        # Generous is good, signing hell contracts is not.
        good = (mean(entry["dc"]) - group_dc) / 5 - 0.5 * signed / len(entry["dc"])
        # Going with the table is lawful, going against it is chaotic.
        law = 0.0
        if entry["deviations"] and group_deviation > EPSILON:
            law = (group_deviation - mean(entry["deviations"])) / max(group_deviation, 1)
        rows.append({"name": player["name"], "alignment": _alignment(law, good)})
    return rows


def _battle(chips, group_of, min_groups=2):
    groups = {}
    for chip in chips:
        if chip["dc"] is not None and group_of(chip):
            groups.setdefault(group_of(chip), []).append(chip["dc"])
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
    for chip in chips:
        chip["price_gap"] = None
        rated = chip["dc"] is not None
        chip["tier"] = addiction_tier(chip["dc"]) if rated else None
        chip["alignment"] = _chip_alignment(chip) if rated else None
        chip["sheet"] = _character_sheet(chip) if rated else []
        chip["conditions"] = _conditions(chip) if rated else []
    chips.sort(key=lambda c: (c["dc"] is None, rank_key(c) if c["dc"] is not None else ()))
    for position, chip in enumerate(chips, start=1):
        chip["rank"] = position if chip["dc"] is not None else None

    per_player = {
        p["id"]: {"dc": [], "deviations": [], "crits": 0, "note_chars": 0, "best": None, "worst": None}
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
                value = rating["dc"]
                entry["dc"].append(value)
                scores_by_player[pid][chip_id] = value
                if value in (1, 20):
                    entry["crits"] += 1
                entry["note_chars"] += len(rating.get("notes") or "")
                others = [r["dc"] for other, r in ratings.items() if other != pid]
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
                    "dc": rating["dc"],
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
            "average": mean(per_player[p["id"]]["dc"]) if per_player[p["id"]]["dc"] else None,
            "rated": len(per_player[p["id"]]["dc"]),
            "tier": addiction_tier(mean(per_player[p["id"]]["dc"])) if per_player[p["id"]]["dc"] else None,
        }
        for p in players
    ]

    all_values = [r["dc"] for ratings in all_ratings.values() for r in ratings.values()]
    scale_averages = {}
    rated_chips = [c for c in chips if c["raters"]]
    if rated_chips:
        scale_averages = {k: mean(c["scales"][k] for c in rated_chips) for k in SCALE_KEYS}

    price_reads, pricing = _price_stats(chips, players, all_ratings)
    awards = _chip_awards(chips) + _player_awards(players, per_player, guessing, price_reads)

    return {
        "summary": {
            "chips": len(chips_raw),
            "ratings": len(all_values),
            "average": mean(all_values) if all_values else None,
            "dc20": sum(1 for v in all_values if v == 20),
            "dc1": sum(1 for v in all_values if v == 1),
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
        "pricing": pricing,
        "alignment_names": {f"{law}/{good}": a["name"] for (law, good), a in ALIGNMENTS.items()},
        "player_alignments": _player_alignments(players, per_player, all_ratings),
        "awards": awards,
        "notes": notes,
    }
