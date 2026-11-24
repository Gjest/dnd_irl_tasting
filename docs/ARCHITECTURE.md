# One app for every tasting

The group has tasted cola (Google Forms), water (a Spring app) and chips (this app). This document describes how one app holds all of them, and how a new tasting gets its tile without touching the Docker setup or the data already on the server.

## Constraints

- **Deployment stays as it is.** The server runs this repository with its own Docker adjustments. Every change happens in Python code and in files below `./data`, which is already a volume. No new ports, services, databases or dependencies.
- **Existing data keeps working.** `data/tasting.json`, `data/users.json`, `data/images/` and `data/backups/` keep their meaning and location. A new tasting gets its own file next to them.
- **Plain files.** One JSON file per tasting, readable and editable by hand, with a backup before anything is replaced.
- **Offline, LAN only, blind.** Nothing loads from the internet. Nothing a player can fetch before a reveal may say what is in a bowl.

## Layout

```
/                 guild hall start page: tiles, photo gallery     core.py, landing.html, master.css
/login            guild hall login, one login for every tasting   core.py, login.html
/chips/…          the live chips tasting, Avernus look            views.py (blueprint "main"), base.html, style.css
/cola/  /wasser/  finished tastings, each in its own look         results.py, results_page.html, theme-<slug>.css
/plaene/…         planned tastings: name and questions, "Bald"    plans.py, plan.html, plan_new.html
/ideen            the idea list with stars                        ideas.py, ideas.html
/live/<name>/…    tastings started from a plan, guild look        live.py, live_*.html, theme-gilde.css
/verwaltung       admin panel: logins, participants, hidden tastings  admin_panel.py, verwaltung.html; accounts.py
```

| Module | Job | Reused by |
|---|---|---|
| `registry.py` | The list of tiles: slug, kind, title, tagline, icon, theme | The start page and `results.py` |
| `store.py` → `JsonDocument` | One JSON file in memory, atomic writes, rolling backups, `replace()` with a backup first | `tasting.json` for chips, `<slug>.json` for every other tasting |
| `images.py` | Re-encodes uploaded photos, `save_from_form()` for the camera and file buttons | Bowls, list items and start page photos (`data/start.json`) |
| `web.py` | `store()`, `login_required`, `admin_required`, `visible_tastings()`, `check_not_hidden()` | Every blueprint |
| `accounts.py` | Logins: create, reset, the guards for the last admin; `"active": false` in `users.json` | `manage.py` and the admin panel |
| `archive.py` | Checks a results file and computes ranking, awards, groups, people, twins, flags and notes | `results.py` |
| `static/js/report.js` | Bars, tables, heat maps, taste twins, chart colors read from the theme | Chips results and every results page |
| `static/css/style.css` | Components (cards, tabs, bars, tables) styled through CSS variables | Chips, and as the base below every `theme-<slug>.css` |

`core.py` also turns addresses from before the move (`/einkauf`, `/schale/…`, `/ergebnisse`, `/archiv/…`, `/water`) into redirects. The printed QR code still points at the root and now lands on the tiles.

## Results files (`tasting-archive/1`)

A finished tasting is one JSON file that brings its own questions along. The results page is built from that file alone.

```json
{
  "format": "tasting-archive/1",
  "id": "cola",                       // overwritten with the slug on upload
  "title": "Cola-Verkostung", "subtitle": "…", "date": "2026-08-14", "intro": "…",
  "scale": {"min": 1, "max": 5},
  "ranking": "genuss",                // criterion the ranking uses
  "tiebreak": "harmonie",             // optional
  "group_label": "Zero gegen Zucker", // optional, names the group battle
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
- **Groups** are free text per item. With two or more groups the page gets a battle tab.
- **Flags** are yes/no facts per rating, such as "poured it myself". The page compares the ranking score with and without each flag.

### Where the cola and water files came from

| Tasting | Source | Notes |
|---|---|---|
| Cola | `cola-tasting/Cola Tasting.html` (the saved form) and `cola_tasting_analyse_v3-1.html` (all 75 answers) | The questions, their order and the scale ends come straight from the saved form, so nothing had to be guessed. "Weitere Noten" became the notes, "Eingeschenkt?" the flag. Zero and sugar come from the old analysis. |
| Water | `WaterTasting/export/watertasting.mv.db` | `tools/h2rows.py` reads the H2 file directly, without Java or H2. That file is the cleaned version, with names and sample spellings already unified. It holds 82 ratings, and the 9 deleted test rows stay deleted. The questions come from the old form, translated to German. The mineral battle splits at the average mineral intensity, as the old dashboard did. |

`tools/archive_cola_water.py` rebuilds both files. An optional third argument maps recorded names to the group's nicknames. For the water tasting that file is `export/aliase.json`, kept out of git because it pairs nicknames with real names. They hold real names and stay out of git; the admin uploads them on the tile's page.

## Adding a tasting

### A finished tasting (results only)

1. **Results file:** turn the old data into a results file in the format above. `tools/` has two converters to start from.
2. **Registry:** add an entry to `TASTINGS` in `registry.py`, for example:
   ```python
   {"slug": "kaffee", "kind": "results", "number": 4, "title": "Kaffee-Verkostung", "short": "Kaffee",
    "tagline": "…", "icon": "☕", "theme": "kaffee"}
   ```
3. **Look:** add `static/css/theme-kaffee.css`. It sets the color variables of `style.css` (`--ash`, `--soot`, `--ember`, `--bone`, …) and the chart variables (`--series-1`, `--chart-text`, …) on `.theme-kaffee`, and can restyle headings. `theme-cola.css` and `theme-wasser.css` are short examples.
4. **Tile color:** add `.app-tile-kaffee { --tile-a: …; --tile-b: …; }` to `master.css`.
5. **Upload:** deploy, open the new tile as admin and upload the file. The app writes `data/kaffee.json`.
6. **Table picture:** if the start page has one, mark the new tasting's dish under "Tafelbild". `short` is the name in the links below the picture. Until then the tasting is still reachable through the links below the picture and in the tile view.

No new Python code is needed. Routes, upload, download, backups and the results page come from `results.py`.

### From a planned tasting

No code is needed. A plan (`plans.py`, `data/plans.json`) holds name, look, questions, participants, the container word (`vessel`, e.g. `{"one": "Glas", "many": "Gläser"}`) and the `ranking` scale question. Its template (`tasting-template/1`) carries the same `sections` and `criteria` as a results file, plus `"type": "scale"` or `"text"` per question.

"Jetzt starten" sets `state: "live"` and creates `data/live-<slug>.json` (`live.py`). It freezes a copy of the questions, scale and ranking, because ratings are keyed by them. The rest stays in the plan and can change:

```
{"format": "live-tasting/1", "slug", "started", "phase": "tasting" | "ceremony" | "revealed",
 "ceremony_order": [ids, worst first], "reveal_count", "scale", "sections", "ranking",
 "items":   [{id, name, brand, note, price, amount, unit, image, creator, buyer, bought}],
 "vessels": [{id, number, item_id, snapshot, image, added_by, bought_by}],
 "ratings": {vessel_id: {uid: {"scores": {key: int}, "texts": {key: str}, "notes": str}}}}
```

`live.py` copies the proven flow of `views.py` without its chips content: shopping list, set-up with sequential numbers and shuffle, blind photos, rating, reveal. `to_archive()` turns a tasting into a `tasting-archive/1` file. Text answers go into the notes, and price per 100 g/ml goes along as `price_per_100`. So `archive.compute()`, `report.js` and `archive.js` serve its results, and the admin can download it as a finished results file. Photos live in `data/images/live-<slug>/`, apart from the chips photos. `bowls.js`, `unsealing.js` and `rate.js` are shared with the chips tasting; the last two take the live payload and the missing d20 die.

### A new live tasting

Today the chips tasting is the only live one, and its code assumes chips: `catalog.py`, the d20 Sucht-Save, the shopping list and the chips statistics. For a new live tasting, copy it:

1. **Code:** copy `views.py`, `catalog.py`, `stats.py` and the chips templates and scripts. Give the blueprint a new name and register it in `create_app` under its own prefix, e.g. `/kaffee`.
2. **Data file:** point its store at its own document, `store.document("kaffee")`, instead of `tasting.json`. `JsonDocument` already gives atomic writes, backups and `replace()`.
3. **Registry:** add it with `"kind": "live"` and its `endpoint`. Its module provides a `tile()` function like `views.tile()`.
4. **Content:** adapt the questions in its catalog and its look. When it is over, export it as a results file and switch its tile to `"kind": "results"`, so it keeps working without its live code.

### Later

- **Live engine:** instead of copying code, move the questions into a definition file per tasting, using the same `sections`, `scale`, `ranking` and `awards` keys as a results file, and have one set of live pages read it. Chips-only features (Sucht-Save tiers, alignment, nutrition, shopping list) would become switches in that definition. The copy above is the first step and shows which parts really differ.
- **Chips into the archive:** an admin action that turns `tasting.json` into a results file once the chips tasting is over, so its tile stays readable after the next tasting starts.
- **People across tastings:** every tasting now uses the same nicknames, so a hall of fame across all tastings only needs to read the files that are already there.
