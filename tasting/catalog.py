"""All tasting content: rating categories, status effects, flavors, passphrase words.

Edit this file to change what gets rated. Keys are what ends up in the JSON
file, so don't rename them once ratings exist.
"""

SECTIONS = [
    {
        "title": "Wahrnehmungswurf",
        "subtitle": "Das Auge",
        "ratings": [
            {"key": "roast", "label": "Röstgrad", "low": "Bleich wie Knochen", "high": "Verkohlt wie Avernus"},
            {"key": "coverage", "label": "Gewürzstaub", "low": "Nackt", "high": "Unter Asche begraben"},
            {"key": "integrity", "label": "Strukturelle Integrität", "hint": "Wie groß sind die Stücke in der Schale?", "low": "Nur Brösel und Knochenstaub", "high": "Ganze Chips, groß wie Schilde"},
        ],
    },
    {
        "title": "Schwefelprobe",
        "subtitle": "Die Nase",
        "ratings": [
            {"key": "aroma", "label": "Aroma", "low": "Geruchlos", "high": "Füllt die ganze Taverne"},
            {"key": "artificial", "label": "Künstlichkeit", "low": "Ehrlicher Acker", "high": "Bels Labor"},
        ],
    },
    {
        "title": "Der Biss",
        "subtitle": "Die Zähne",
        "ratings": [
            {"key": "crunch", "label": "Heimlichkeitswurf (Crunch)", "low": "Lautlos", "high": "Weckt Tiamat"},
            {"key": "hardness", "label": "Härte", "low": "Labbrig", "high": "Bricht einen Zahn"},
        ],
    },
    {
        "title": "Der Gaumen",
        "subtitle": "Die Zunge",
        "ratings": [
            {"key": "salt", "label": "Salz", "low": "Fad", "high": "Totes Meer"},
            {"key": "heat", "label": "Höllenfeuer (Schärfe)", "low": "Mild", "high": "Zariels Zorn"},
            {"key": "tang", "label": "Säure", "low": "Stumpf", "high": "Pointiert"},
            {"key": "sweet", "label": "Süße", "low": "Keine", "high": "Lulu ist begeistert"},
            {"key": "potato", "label": "Kartoffelpräsenz", "low": "Aromatisierte Pappe", "high": "Reine Kartoffel"},
        ],
    },
    {
        "title": "Das Nachspiel",
        "subtitle": "Der Abgang",
        "ratings": [
            {"key": "echo", "label": "Nachhall", "low": "Sofort verflogen", "high": "Verfolgt deine Seele"},
            {"key": "grease", "label": "Styx-Faktor (Fett)", "low": "Staubtrocken", "high": "Finger hinterlassen Flecken"},
            {"key": "thirst", "label": "Durst der Verdammten", "low": "Keiner", "high": "Würde den Styx trinken"},
        ],
    },
    {
        "title": "Das Urteil",
        "subtitle": "Die Gesamtwertung",
        "ratings": [
            {"key": "harmony", "label": "Harmonie", "low": "Einseitig", "high": "Ausbalanciert"},
        ],
    },
]

SCALE_KEYS = [r["key"] for s in SECTIONS for r in s["ratings"]]
SCALE_LABELS = {r["key"]: r["label"] for s in SECTIONS for r in s["ratings"]}
# Short names for the radar chart, whose axis labels have little room.
SCALE_SHORT = {
    "roast": "Röstgrad", "coverage": "Gewürz", "integrity": "Integrität",
    "aroma": "Aroma", "artificial": "Künstlich", "crunch": "Crunch",
    "hardness": "Härte", "grease": "Fett", "salt": "Salz", "heat": "Schärfe",
    "tang": "Säure", "sweet": "Süße", "potato": "Kartoffel", "echo": "Nachhall",
    "thirst": "Durst", "harmony": "Harmonie",
}

MIN_DC = 1
MAX_DC = 20

# What a Sucht-Save DC does to you. A tier starts at `from` and runs up to the next one.
ADDICTION_TIERS = [
    {"from": 1, "name": "Immun", "line": "Nicht einmal ein Lemure greift hier zu."},
    {"from": 2, "name": "Verängstigt", "line": "Du weichst vor der Schale zurück und näherst dich nicht freiwillig."},
    {"from": 6, "name": "Erschöpft", "line": "Du greifst noch einmal zu, aber nur aus Pflichtgefühl."},
    {"from": 11, "name": "Bezaubert", "line": "Die Hand wandert von selbst zur Schale."},
    {"from": 15, "name": "Gepackt", "line": "Die Schale hält dich fest. Aufstehen wird schwierig."},
    {"from": 18, "name": "Gelähmt", "line": "Du kannst nicht aufhören. Du kannst nicht einmal blinzeln."},
    {"from": 20, "name": "Beherrscht", "line": "Die Tüte ist leer, und du weißt nicht mehr, wer sie geöffnet hat."},
]

# Group averages that give a chip a status effect. "min" triggers at or above the
# value, "max" at or below it.
CONDITIONS = [
    {"scale": "heat", "min": 3.5, "name": "Brennend", "line": "Jede Runde 1W6 Feuerschaden am Gaumen."},
    {"scale": "artificial", "min": 3.5, "name": "Vergiftet", "line": "Nachteil auf alle Geschmackswürfe. Bel nickt zufrieden."},
    {"scale": "crunch", "min": 4, "name": "Taub", "line": "Das eigene Kauen übertönt jedes Gespräch."},
    {"scale": "hardness", "min": 4, "name": "Kampfunfähig", "line": "Ein Zahn weniger. Keine Aktionen, bis der Schmerz nachlässt."},
    {"scale": "grease", "min": 3.5, "name": "Liegend", "line": "Auf dem eigenen Fettzauber ausgerutscht."},
    {"scale": "thirst", "min": 3.5, "name": "Erschöpfung Stufe 1", "line": "Ohne Getränk geht gar nichts mehr."},
    {"scale": "coverage", "min": 4, "name": "Blind", "line": "Gewürzstaub in den Augen. Das war der falsche Finger."},
    {"scale": "echo", "min": 4, "name": "Verflucht", "line": "Der Geschmack bleibt, bis jemand Fluch brechen wirkt."},
    {"scale": "salt", "min": 4, "name": "Versteinert", "line": "Zur Salzsäule erstarrt."},
    {"scale": "potato", "max": 2, "name": "Unsichtbar", "line": "Die Kartoffel ist da, sagen sie. Gesehen hat sie niemand."},
]

# Every chip gets a character sheet. A scale in "against" counts the other way round.
ATTRIBUTES = [
    {"label": "STÄ", "name": "Stärke", "for": ["hardness", "crunch"], "against": []},
    {"label": "GES", "name": "Geschicklichkeit", "for": [], "against": ["grease", "coverage"]},
    {"label": "KON", "name": "Konstitution", "for": ["echo", "thirst"], "against": []},
    {"label": "INT", "name": "Intelligenz", "for": ["harmony", "tang"], "against": []},
    {"label": "WEI", "name": "Weisheit", "for": ["potato"], "against": ["artificial"]},
    {"label": "CHA", "name": "Charisma", "for": ["aroma", "roast"], "against": []},
]

ALIGNMENTS = {
    ("lawful", "good"): {"name": "Rechtschaffen Gut", "chip": "Ehrlich, ordentlich, ein Paladin in der Tüte.", "player": "Bewertet sauber, freundlich und im Sinne der Gruppe."},
    ("neutral", "good"): {"name": "Neutral Gut", "chip": "Tut niemandem weh und macht alle ein bisschen glücklicher.", "player": "Findet überall etwas Gutes, ganz ohne Regelwerk."},
    ("chaotic", "good"): {"name": "Chaotisch Gut", "chip": "Wild und unberechenbar, aber das Herz sitzt am rechten Fleck.", "player": "Weicht ständig von der Gruppe ab, aber immer aus Liebe."},
    ("lawful", "neutral"): {"name": "Rechtschaffen Neutral", "chip": "Macht genau, was auf der Tüte steht. Nicht mehr.", "player": "Urteilt nach Vorschrift. Niemand weiß, ob es Spaß gemacht hat."},
    ("neutral", "neutral"): {"name": "Wahrhaft Neutral", "chip": "Existiert. Mehr lässt sich nicht beweisen.", "player": "Hat zu allem eine Meinung, und zwar die mittlere."},
    ("chaotic", "neutral"): {"name": "Chaotisch Neutral", "chip": "Keiner weiß, was als Nächstes passiert. Auch die Chips nicht.", "player": "Würfelt vermutlich heimlich."},
    ("lawful", "evil"): {"name": "Rechtschaffen Böse", "chip": "Präzise kalkuliertes Leid. Asmodeus hat das Kleingedruckte gelesen.", "player": "Streng, gnadenlos und mit lückenloser Begründung."},
    ("neutral", "evil"): {"name": "Neutral Böse", "chip": "Will nur deinen Gaumen und deine Seele. Nichts Persönliches.", "player": "Unterschreibt und richtet, wie es gerade nützt."},
    ("chaotic", "evil"): {"name": "Chaotisch Böse", "chip": "Ein Dämon aus dem Abyss, frittiert.", "player": "Will den Tisch einfach brennen sehen."},
}

# Correlation verdicts, checked from the top. The first `from` at or below r wins.
PRICE_GUESS_VERDICTS = [
    {"from": 0.7, "line": "Die Gruppe riecht Preise. Mammon bietet euch eine Stelle in Minauros an."},
    {"from": 0.3, "line": "Ein Hauch von Preisgefühl. Für einen Rabatt in Avernus reicht es."},
    {"from": -0.3, "line": "Reiner Zufall. Ihr hättet genauso gut würfeln können."},
    {"from": -1.01, "line": "Je billiger, desto edler kam es euch vor. Das Marketing hat eure Seelen längst."},
]
PRICE_ADDICTION_VERDICTS = [
    {"from": 0.5, "line": "Teuer macht süchtig. Mammon reibt sich die Hände."},
    {"from": -0.3, "line": "Preis und Sucht haben nichts miteinander zu tun. Der Discounter lacht."},
    {"from": -1.01, "line": "Je billiger, desto süchtiger. Deine Seele ist günstig zu haben."},
]

FLAVOR_TYPES = [
    "Gesalzen",
    "Paprika",
    "Sour Cream & Zwiebel",
    "Salt & Vinegar",
    "Käse",
    "BBQ",
    "Chili / Scharf",
    "Kräuter & Gewürze",
    "Sonstiges",
]

MAX_SOUL_COINS = 10
MAX_NOTES_LENGTH = 1000
MAX_WEIGHT_GRAMS = 5000

POINTS_FLAVOR = 2
POINTS_BRAND = 3

PASSPHRASE_SUBJECTS = [
    "zariel", "bel", "lulu", "maggie", "arkhan", "thavius", "tiamat", "yael",
    "reya", "imp", "teufel", "lemure", "erinnye", "hoellenreiter", "paladin",
    "barde", "druide", "kobold", "ork", "goblin", "drache", "lich", "oger",
    "troll", "hexe", "ritter", "zwerg", "elf", "gnom", "mimik", "beholder",
    "geist", "ghul", "golem", "greif", "harpyie", "knappe", "magier", "moench",
    "waechter",
]
PASSPHRASE_VERBS = [
    "beisst", "knuspert", "klaut", "liebt", "hasst", "bewacht", "verflucht",
    "segnet", "wuerzt", "sammelt", "versteckt", "verschlingt", "tauscht",
    "schmuggelt", "kostet", "preist", "verkauft", "vermisst", "zaehlt", "jagt",
    "rettet", "verbrennt", "verschmaeht", "wirft",
]
PASSPHRASE_OBJECTS = [
    "paprika", "chips", "tuete", "salz", "knabberei", "kartoffel", "seele",
    "muenze", "schale", "krume", "essig", "zwiebel", "kaese", "chili", "krone",
    "schwert", "schild", "vertrag", "kriegsmaschine", "schwefel", "asche",
    "funke", "flamme", "taverne", "laterne", "truhe", "karte", "fackel",
    "banner", "kelch", "ring", "amulett", "trank", "rolle", "wuerfel", "stiefel",
    "laute", "feder", "kessel", "knochen",
]
