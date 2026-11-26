"""Sample questionnaires to start a new tasting from: chips, cola and water.

They are the questions of the group's first three tastings, as templates in
the format of plans.py (tasting-template/1). "Neues Tasting planen" offers
them, so a new install can start from one even after deleting the old
tastings themselves.

This module imports nothing from the app, so tools/archive_cola_water.py can
load the cola and water questions from here as well and both stay the same.
"""

AWAY, STRONG = "nicht wahrnehmbar", "dominant"


def crit(key, label, low, high):
    return {"key": key, "label": label, "low": low, "high": high}


COLA_SECTIONS = [
    {"title": "Das Auge", "criteria": [
        crit("farbe", "Farbintensität", "Helles Kastanienbraun", "Tiefes Schwarz"),
        crit("fenster", "Fenster", "wässrig ohne Rückstände", "sirupartige Schlieren"),
        crit("krone", "Krone", "Nicht vorhanden", "Stabiler Schaum")]},
    {"title": "Die Nase", "criteria": [
        crit("zitrus", "Zitrus", AWAY, STRONG), crit("zimt", "Zimt", AWAY, STRONG),
        crit("nelke", "Nelke", AWAY, STRONG), crit("kraeuter", "Kräuter", AWAY, STRONG)]},
    {"title": "Der Gaumen", "criteria": [
        crit("carb", "Carbonisierung", "Feinperlig, cremig", "Stark spritzig"),
        crit("suesse", "Süße", "Herb, dezent", "Süß, klebrig"),
        crit("saeure", "Säure", "mild, stumpf", "pointiert, sauer"),
        crit("zitrone", "Zitronen-Noten", AWAY, STRONG), crit("limette", "Limetten-Noten", AWAY, STRONG),
        crit("orange", "Orangen-Noten", AWAY, STRONG), crit("beere", "Beeren-Noten", AWAY, STRONG),
        crit("bitter", "Bitterkeit", AWAY, STRONG)]},
    {"title": "Der Abgang", "criteria": [
        crit("koerper", "Körper", "Dünn", "Vollmundig"),
        crit("zahn", "Zahn-Gefühl", "glatt", "pelzig stumpf"),
        crit("nachhall", "Nachhall", "kurzweilig", "anhaltend")]},
    {"title": "Gesamtbewertung", "criteria": [
        crit("harmonie", "Harmonie", "einseitig", "ausbalanciert"),
        crit("genuss", "Persönlicher Genussfaktor", "nicht mein Fall", "absoluter Favorit")]},
]

WATER_SECTIONS = [
    {"title": "Das Auge", "criteria": [
        crit("clarity", "Klarheit", "Trüb", "Kristallklar"),
        crit("color", "Farbe", "Farblos", "Getönt")]},
    {"title": "Die Nase", "criteria": [
        crit("odor", "Geruch", "Keiner, neutral", "Stark, erdig, metallisch")]},
    {"title": "Das Mundgefühl", "criteria": [
        crit("carbonation", "Kohlensäure", "Still", "Stark sprudelnd"),
        crit("temperature", "Temperatur", "Eiskalt", "Zimmerwarm"),
        crit("body", "Körper", "Dünn, leicht", "Schwer, seidig")]},
    {"title": "Der Gaumen", "criteria": [
        crit("mineral_intensity", "Mineralität", "Kaum", "Intensiv"),
        crit("sweetness", "Süße", "Trocken", "Süß"),
        crit("bitterness", "Bitterkeit", "Keine", "Scharf, bitter"),
        crit("salinity", "Salzigkeit", "Frisch", "Salzig, brackig"),
        crit("ph_sensation", "pH-Gefühl", "Sauer, scharf", "Basisch, weich")]},
    {"title": "Der Abgang", "criteria": [
        crit("duration", "Nachhall", "Kurz, sauber", "Lang anhaltend")]},
    {"title": "Gesamtbewertung", "criteria": [
        crit("harmony", "Harmonie", "Unausgewogen", "Perfekt ausbalanciert"),
        crit("personal_enjoyment", "Persönlicher Genuss", "Nicht mein Glas", "Absoluter Favorit")]},
]

# The chips tasting ranks by its d20 "Sucht-Save", which a plain questionnaire
# doesn't have. Its template adds a last scale question that ranks instead.
CHIPS_RANKING = {"key": "genuss", "label": "Persönlicher Genuss", "low": "Nie wieder", "high": "Ich will die ganze Tüte"}


def chips_sections(catalog_sections):
    """The chips questions (catalog.SECTIONS) as template sections, plus the ranking question."""
    sections = [{"title": f"{s['title']} · {s['subtitle']}" if s.get("subtitle") else s["title"],
                 "criteria": [{k: r[k] for k in ("key", "label", "low", "high")} for r in s["ratings"]]}
                for s in catalog_sections]
    sections[-1]["criteria"].append(dict(CHIPS_RANKING))
    return sections


def _template(title, short, icon, tagline, vessel, sections, ranking_label):
    return {
        "format": "tasting-template/1",
        "title": title, "short": short, "icon": icon, "tagline": tagline,
        "scale": {"min": 1, "max": 5},
        "vessel": vessel,
        "sections": [{"title": s["title"], "criteria": [{**c, "type": "scale"} for c in s["criteria"]]} for s in sections],
        "ranking_label": ranking_label,
    }


def templates(catalog_sections):
    """name -> template, in the order "Neues Tasting planen" shows them."""
    return {
        "chips": _template("Neue Chips-Verkostung", "Chips", "🔥", "Nach dem Muster vom Blutkrieg der Chips",
                           {"one": "Schale", "many": "Schalen"}, chips_sections(catalog_sections), CHIPS_RANKING["label"]),
        "cola": _template("Neue Cola-Verkostung", "Cola", "🥤", "Nach dem Muster der ersten Cola-Verkostung",
                          {"one": "Glas", "many": "Gläser"}, COLA_SECTIONS, "Persönlicher Genussfaktor"),
        "wasser": _template("Neue Wasser-Verkostung", "Wasser", "💧", "Nach dem Muster der Wasser-Verkostung",
                            {"one": "Glas", "many": "Gläser"}, WATER_SECTIONS, "Persönlicher Genuss"),
    }
