# One app for every tasting

The group has tasted cola (Google Forms), water (a Spring app) and chips (this app). This document describes how the app holds all of them, and how a future tasting fits in without changing the Docker setup or breaking the data that already lives on the server.

## Constraints

- **Deployment stays as it is.** The server runs this repository with its own Docker adjustments. Every change happens in Python code and in files below `./data`, which is already a volume. No new ports, services, databases or dependencies.
- **Existing data keeps working.** `data/tasting.json`, `data/users.json`, `data/images/` and `data/backups/` keep their meaning and location. New things go into new files or folders.
- **Plain files.** One JSON file per tasting, readable and editable by hand, with a backup before anything is overwritten.
- **Offline, LAN only, blind.** Nothing new loads from the internet. Nothing a player can fetch before a reveal may say what is in a bowl.

## What exists now

```
data/
  tasting.json          the live tasting (chips), unchanged
  users.json            logins, shared by every tasting
  images/  backups/     unchanged
  archive/
    cola.json           finished tastings, one self-describing file each
    wasser.json
```

| Page | What it shows |
|---|---|
| `/verkostungen` | The overview everyone lands on after logging in: the live tasting with its state and a button to take part, and a card per archived tasting with its winner. |
| `/`, `/einkauf`, `/schale/…`, `/ergebnisse` | The live chips tasting, exactly as before. |
| `/archiv/<id>` | Results of an archived tasting: ranking, awards, x-ray, group battle, controversy, people, taste twins, flags, notes and the original questionnaire. |
| Admin page, "Archiv" | Upload or remove archive files. |

`tasting/archive.py` validates archive files and computes every statistic from the file alone. `static/js/archive.js` renders them, and `static/js/report.js` holds the building blocks it shares with the chips results page.

## The archive format (`tasting-archive/1`)

```json
{
  "format": "tasting-archive/1",
  "id": "cola",                      // lower case, digits, dashes; also the file name
  "number": 1,                       // order on the overview
  "title": "Cola-Verkostung",
  "subtitle": "…", "date": "2026-08-14", "intro": "…",
  "scale": {"min": 1, "max": 5},
  "ranking": "genuss",               // criterion the ranking uses
  "tiebreak": "harmonie",            // optional
  "group_label": "Zero gegen Zucker",// optional, names the group battle
  "sections": [
    {"title": "Das Auge", "criteria": [
      {"key": "farbe", "label": "Farbintensität", "low": "Helles Kastanienbraun", "high": "Tiefes Schwarz"}
    ]}
  ],
  "items": [{"id": "1", "name": "Pepsi Max", "group": "Zero"}],
  "flags": [{"key": "served", "label": "Selbst eingeschenkt", "hint": "…"}],
  "awards": [
    {"title": "Drachenatem", "line": "…", "best": "max",
     "terms": [{"key": "bitterness"}, {"key": "ph_sensation", "invert": true}]}
  ],
  "ratings": [
    {"person": "Milka", "item": "1", "scores": {"farbe": 2, "zimt": null},
     "flags": {"served": false}, "notes": "…"}
  ]
}
```

- **Missing answers** are `null` and are skipped in averages.
- **Awards** average the listed criteria per item. `invert` flips a criterion, so a low pH score counts as "acidic". The app adds the most controversial item and three awards for people on its own.
- **Groups** are free text per item. With two or more groups the results get a battle tab.
- **Flags** are yes/no facts per rating, such as "poured it myself". The results compare the ranking score with and without each flag.

### Where the two past tastings came from

| Tasting | Source | Notes |
|---|---|---|
| Cola | `cola-tasting/Cola Tasting.html` (the saved form) and `cola_tasting_analyse_v3-1.html` (all 75 answers) | The questions, their order and the scale ends come straight from the saved form, so nothing had to be guessed. "Weitere Noten" became the notes, "Eingeschenkt?" the flag. Zero and sugar come from the old analysis. |
| Water | `WaterTasting/export/watertasting.mv.db` | Read directly from the H2 file by `tools/h2rows.py`, without Java or H2. That file is the cleaned version, in which names and sample spellings were already unified. It holds 82 ratings, and the 9 deleted test rows stay deleted. The questions come from the app's form, translated to German. The mineral battle splits at the average mineral intensity, as the old dashboard did. |

`tools/archive_cola_water.py` rebuilds both archive files from those sources. The results stay out of git like every other export with real names.

## Plan for future tastings

The live tasting is still chips-specific code: the catalog, the d20 Sucht-Save, the shopping list and the stats all assume chips. A new tasting would mean changing that code. The steps below remove that assumption gradually, and each step leaves a working app.

### Step 1: Archive the chips tasting (small, next)

Add an admin action "Als Archiv sichern" that converts `data/tasting.json` into an archive file:

- The scale questions become criteria, and the DC becomes the ranking criterion, with a scale from 1 to 20.
- Price guesses and contracts become flags or extra criteria. Nutrition goes into item fields that the archive page can show.
- Buyer and setter go into the items, so the archive can show who brought what.

After that, "Alles niederbrennen" can start a fresh live tasting without losing anything. The chips-specific results page keeps working for the live tasting.

### Step 2: Tasting definitions instead of a hard-coded catalog

Move what `catalog.py` holds today into a definition per tasting:

```
data/tastings/<id>/definition.json   questions, ranking question, item noun, features
data/tastings/<id>/tasting.json      bowls, ratings, shopping list (today's format)
data/tastings.json                   {"live": "<id>"}
```

A definition reuses the archive's `sections`, `scale`, `ranking` and `awards`, and adds:

- `item_noun`: "Schale", "Glas" or "Flasche".
- `ranking_input`: `"die"` (the d20) or `"scale"`.
- `features`: `shopping_list`, `photos`, `price_guess`, `brand_guess`, `nutrition`.

Migration: on start, if `data/tastings.json` is missing and `data/tasting.json` exists, the app treats the old file as tasting `chips` with today's catalog as its definition. Nothing on disk moves until an admin action does it, and that action makes a backup first. Old URLs (`/`, `/schale/…`) keep pointing at the live tasting.

### Step 3: Generic live pages

Rating, bowls, ceremony and results read the definition instead of the catalog. Chips-only statistics (Sucht-Save tiers, alignment, character sheets, nutrition) become optional modules that switch on via `features`. A new tasting is then mostly a new `definition.json`, which an admin uploads like an archive file. Every finished live tasting ends as an archive file, which closes the loop.

### Step 4: Across tastings

- **People:** The same people appear under different names: real names for water, nicknames for cola and chips. An admin-maintained `data/people.json` would map them, for example `{"Lennart": "Der Lenny"}`. The app does not guess these mappings.
- **Hall of fame:** With people mapped, the overview can show statistics across tastings: the most generous palate of all time, who agrees most often over three tastings, and who wins the most guessing points.

### What stays the same throughout

- **Logins:** Logins and their passphrases are shared by all tastings.
- **Security:** CSRF, the host check, rate limits and the strict CSP stay as they are. Uploads stay validated, and nothing loads from outside.
- **Backups and import:** Backups and the admin import keep working per tasting file.
