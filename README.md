# Blutkrieg der Chips

A chips tasting for our Descent into Avernus group. It runs in one Docker container on a laptop in the home WLAN. Everyone logs in on their phone, adds the chips they brought, rates numbered bowls, and the admin reveals the results from worst to best.

## Start

The laptop needs Docker with the Compose plugin. Make sure the Docker service runs and starts at boot:

```bash
sudo systemctl enable --now docker
```

Then, once:

```bash
git clone git@github.com:Gjest/dnd_irl_tasting.git && cd dnd_irl_tasting
./setup.sh
```

`setup.sh` asks for the laptop's WLAN IP (with a suggestion), builds and starts the container, and prints each person's passphrase **once**. Write them down: only their hashes are stored.

After that the container comes back on its own after a reboot, unless you stopped it with `docker compose down`. By hand:

```bash
docker compose up -d
```

```bash
docker compose down
```

Open `http://<laptop-ip>:9001`. `localhost` does not work, because the port is only bound to the WLAN IP. After logging in, everyone sees one tile per tasting. The chips tasting lives below `/chips/`, and addresses from before the move redirect there.

Give the laptop a fixed IP in your router. If the IP ever changes, update `BIND_IP` in `.env` and run `docker compose up -d`.

## During the tasting

1. **Shopping:** under "Einkauf" everyone sees one shared list of who buys which bag. Exact duplicates are refused, and similar names get a warning. A wish without a buyer can be claimed with "Ich kaufe das". An item takes everything a bowl needs, including price, weight and a photo. Price and weight stay visible only to the buyer and the admin. At the tasting, anyone can turn any item into a bowl with "Als Schale aufstellen", and the same bag can go on the table more than once. If brand or name and the flavor are filled in, that takes one tap. Otherwise the bowl form opens with everything filled in. Only whoever set a bowl up knows what is in it and gets no guessing points for it. The buyer stays as blind as everyone else, and the list never says which items became bowls. Only the admin sees that until the reveal. Everyone knows which chips are in the game, so guessing the brand is easier.
2. **Before:** everyone adds the chips they brought under "Chips mitgebracht?" on their bowls page, ideally with price and bag weight so that prices compare per 100 g. A name is optional: "Pringles" plus "Paprika" is enough. Only the person who added a chip and the admin can see what's in that bowl.
3. **Tasting:** players rate every bowl, including their own, and can change a rating until the reveal. The ranking comes from the Sucht-Save: turn the 3D d20 to how hard it is to stop eating (DC 1 to 20). On your own bowls you can't guess the flavor, brand or price. Everyone sees who is still missing which bowl, but no scores.
4. **Reveal:** press "Enthüllung starten" and click through on the big screen. This locks ratings. "Wertung wieder öffnen" undoes it without losing anything.
5. **After:** results, statistics and printable certificates are open to everyone.

## All tastings in one place

The start page, the guild hall, shows a tile per tasting. As admin you can hang photos there under "Gildenhalle schmücken". They form a gallery, and one of them becomes the page background. The login page shows no photos, because it is visible without logging in. Under "Tafelbild" the admin can put up a picture of the group at the table, then tap each tasting's dish in it. Players tap a dish to open that tasting. A switch above it toggles between the table and the tiles. Each device remembers its choice in a cookie of its own (`ansicht`), so it survives logging out. Below the picture every tasting is also linked by name, including one without a dish on the table. Under "Daten der Verkostungen" the admin sets the date of each tasting. It shows on the tile and on the results page. Without one, a tile uses the date its data brings along, if any. Each tasting has its own look and lives at its own address:

| Tile | Address | What it is |
|---|---|---|
| Blutkrieg der Chips | `/chips/` | The live tasting with shopping list, bowls, reveal and results |
| Cola-Verkostung | `/cola/` | Results of the first tasting |
| Wasser-Verkostung | `/wasser/` | Results of the second tasting |

The cola and water results come in once as an upload. As admin, open the tile and upload the file under "Daten verwalten". The app writes it to `data/cola.json` or `data/wasser.json` and reads only that file from then on. Each upload replaces the old file, which goes to `data/backups/` first. Files uploaded with the previous version under `data/archive/` are taken over on the next start. The files were built from the old sources with the scripts in `tools/`. The water tasting recorded real names, which `export/aliase.json` maps to the group's nicknames during the conversion. Both stay out of git.

Below the tastings, "Was als Nächstes?" holds what is coming:

- **Ideensammlung** (`/ideen`): everyone adds ideas for the next tasting, just a name, and gives each idea one to five stars. Tapping your own rating again takes it back. The list is sorted by average stars. Whoever added an idea, and the admin, can remove it.
- **Planned tastings** (`/plaene/<name>`): the admin starts one with the + tile, gives it a name and adds questions in sections, as scales (with words for both ends) or free text. It shows as "Bald" on the start page, and everyone can read its questions. "Vorlage herunterladen" saves the questions as a JSON file (`tasting-template/1`), which "Neues Tasting planen" takes in again.
- **Starting one:** "Jetzt starten" on a planned tasting turns it into a running one under `/live/<name>/`, with the flow of the chips tasting:
  - **Shopping list:** free text (name, plus optional brand, variety or note, price and amount in g or ml). Who buys what, and whether it's bought.
  - **Blind containers:** set up from the list with one tap and numbered. The plan says what they are called, e.g. Glas/Gläser. Only whoever set one up knows what is in it.
  - **Rating:** the plan's questions, scales required, free text optional. The plan picks which scale question decides the ranking.
  - **Reveal and results:** the admin reveals worst first. The results page is the one cola and water use, with price per 100 g/ml and a value award.

  Only participants (set in `/verwaltung`) shop, set up and rate, the admin too if entered. Everyone can read. Once started, the questions are frozen; name, look and participants can still change. The admin page of the tasting shows which number holds what, shuffles the numbers, downloads the results as a `tasting-archive/1` file and deletes the tasting.

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) also has the plan for future tastings.

## Cleaning up data

The Admin login can open "Datenpflege" on the admin page. It shows all ratings in plain text, so it spoils the tasting while it's running. That's why Admin is a separate login from your player login.

| Action | Effect |
|---|---|
| Notiz löschen | Removes one note and keeps the rating |
| Wertung löschen | Removes one person's rating of one bowl |
| Ganze Schale löschen | Removes a bowl and all its ratings |
| Alles niederbrennen | Removes all bowls and ratings, keeps logins and the shopping list. Type `ASCHE` to confirm. |

| Daten einspielen | On the admin page: replaces bowls, ratings and the shopping list with a JSON file, e.g. an edited JSON download. Logins and photos stay. |

Each of these saves a backup to `data/backups/` first. To restore one, stop the container and copy it over `data/tasting.json`. Deleting isn't possible during a running reveal. After the reveal, the ranking updates itself.

Players can change their own chips and delete them until someone else has rated them.

## Logins

As admin, "Verwaltung" in the header opens the admin panel (`/verwaltung`):

- **Nutzer:** add a login (player or admin), give someone a new passphrase, rename, change the role, deactivate or delete. A new passphrase is shown once on the page that answers the form and is never stored. Deactivated logins can't sign in and drop out of the login list, but their name stays in old results. Only a login without any data can be deleted. Nobody can lock out themselves or the last active admin.
- **Teilnahme:** who takes part in which planned tasting. Everyone logged in can still read every tasting. In the chips tasting all players take part, as before.
- **Tastings auf der Startseite:** hide chips, cola or water, e.g. on a fresh install for another group. Hidden tastings disappear for players, also at their addresses. Their data, dates and table spots stay until they are shown again.

The same works from the command line:

```bash
docker compose exec app python -m tasting.manage reset "Milka"
```

```bash
docker compose exec app python -m tasting.manage add "New Friend"
```

```bash
docker compose exec app python -m tasting.manage list
```

Resetting a passphrase also logs that person out everywhere. Names for the first setup come from `PLAYERS` in `.env`.

## Data

Everything is in `./data` on the laptop, so it survives restarts and rebuilds. It is not in git.

| File | Content |
|---|---|
| `data/tasting.json` | Chips and all ratings, plain JSON |
| `data/start.json` | Photos on the start page, the background, the table picture with its dishes, the date of each tasting, and which tastings are hidden |
| `data/cola.json`, `data/wasser.json` | Results of the finished tastings, written by the app after an upload |
| `data/plans.json` | Planned tastings with their questions and participants |
| `data/ideas.json` | The idea list with everyone's stars |
| `data/live-<name>.json`, `data/images/live-<name>/` | A running tasting started from a plan: list, containers, ratings, photos |
| `data/images/` | Photos of bags, re-encoded as JPEG |
| `data/backups/` | A copy at most every 5 minutes while data changes, last 100 kept |
| `data/users.json` | Names and passphrase hashes |
| `data/secret.key` | Signs the login cookies. Deleting it logs everyone out. |

The admin page also offers CSV and JSON downloads, which never contain passphrases. A JSON download can be edited and loaded again under "Daten einspielen". List items and bowls may carry `nutrition` (per 100 g: `kcal`, `fat`, `saturated_fat`, `carbs`, `sugar`, `fiber`, `protein`, `salt`), `ingredients` and `nutrition_source`. The list shows them, a bowl takes them over when it is set up, and the results compare them with the ratings. Starting a new tasting: stop the container and move `data/tasting.json` somewhere else.

To change what gets rated, edit `tasting/catalog.py` and run `docker compose up -d --build`. Don't rename keys once ratings exist.

## Security

- **LAN only:** the port is published on the WLAN IP alone. Don't add port forwarding on your router. Docker's published ports bypass `ufw`, so `ufw` rules would not protect this port.
- **Logins:** random passphrases hashed with scrypt, 6 failed tries per person and device per 5 minutes, 60 overall.
- **Web:** CSRF tokens on every POST, `HttpOnly` and `SameSite=Strict` cookies, a strict Content Security Policy with no inline scripts, host header check, 64 KB request limit.
- **Photos:** only JPEG, PNG and WebP up to 12 MB. The app decodes each one and saves a fresh JPEG under a random name, which drops EXIF data such as the phone's GPS position. Before the reveal, a bowl's photo is only shown to whoever brought it and the admin.
- **Offline:** fonts and Chart.js are bundled, so the pages make no outside requests.
- **Container:** non-root, read-only filesystem, all capabilities dropped, no privilege escalation, memory and process limits. Only `./data` is writable.

**Known limit:** there is no HTTPS, because a self-signed certificate would mean a browser warning on every phone. Someone on the same WLAN could in theory read traffic, including a passphrase as it is typed. Passphrases are generated and unique, so that exposes nothing but this app.

## Troubleshooting

| Problem | Fix |
|---|---|
| Phones can't connect | Everyone must be on the same network, not an isolated guest WLAN. Check the laptop firewall too. |
| Container won't start, "cannot assign requested address" | The laptop's IP changed. Update `BIND_IP` in `.env`. |
| `PermissionError` on `/data` in `docker compose logs` | `PUID`/`PGID` in `.env` must own `./data`. Fix with `sudo chown -R $(id -u):$(id -g) data`. |
| Bad request (400) | Open the app by the laptop's IP. Other addresses are refused on purpose. |
| Locked out after wrong tries | Wait 5 minutes, or `docker compose restart`. |

## Development

```bash
pip install -r requirements.txt
```

```bash
python -m unittest discover -s tests -t .
```
