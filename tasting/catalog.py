"""All tasting content: rating categories, NPCs, flavors, passphrase words.

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
            {"key": "integrity", "label": "Strukturelle Integrität", "low": "Schale voller Schutt", "high": "Infernalische Kriegsmaschine"},
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
            {"key": "grease", "label": "Styx-Faktor (Fett)", "low": "Staubtrocken", "high": "Finger hinterlassen Flecken"},
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
            {"key": "fingers", "label": "Verfluchte Finger", "low": "Sauber", "high": "Für immer gezeichnet"},
            {"key": "thirst", "label": "Durst der Verdammten", "low": "Keiner", "high": "Würde den Styx trinken"},
            {"key": "wisdom", "label": "Weisheitsrettungswurf (Suchtfaktor)", "low": "Locker bestanden", "high": "Nat 1, die Tüte ist leer"},
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
    "fingers": "Finger", "thirst": "Durst", "wisdom": "Sucht", "harmony": "Harmonie",
}

NPCS = ["Zariel", "Bel", "Lulu", "Mad Maggie", "Arkhan", "Thavius Kreeg"]

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
