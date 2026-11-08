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

Open `http://<laptop-ip>:9001`. `localhost` does not work, because the port is only bound to the WLAN IP.

Give the laptop a fixed IP in your router. If the IP ever changes, update `BIND_IP` in `.env` and run `docker compose up -d`.

## During the tasting

1. **Shopping:** under "Einkauf" everyone sees one shared list of who buys which bag. Exact duplicates are refused, and similar names get a warning. A wish without a buyer can be claimed with "Ich kaufe das". An item takes everything a bowl needs, including price, weight and a photo. Price and weight stay visible only to the buyer and the admin. If brand or name and the flavor are filled in, "Als Schale aufstellen" turns the item into a bowl in one tap. Otherwise the bowl form opens with everything filled in. Only the buyer and the admin see which bowl it became until the reveal. Everyone knows which chips are in the game, so guessing the brand is easier. If players set up bowls one after another, others could match bowl numbers to the list, so press "Schalen mischen" before the first rating.
2. **Before:** everyone adds the chips they brought under "Chips mitgebracht?" on their bowls page, ideally with price and bag weight so that prices compare per 100 g. A name is optional: "Pringles" plus "Paprika" is enough. Only the person who added a chip and the admin can see what's in that bowl.
3. **Tasting:** players rate every bowl, including their own, and can change a rating until the reveal. The ranking comes from the Sucht-Save: turn the 3D d20 to how hard it is to stop eating (DC 1 to 20). On your own bowls you can't guess the flavor, brand or price. Everyone sees who is still missing which bowl, but no scores.
4. **Reveal:** press "Enthüllung starten" and click through on the big screen. This locks ratings. "Wertung wieder öffnen" undoes it without losing anything.
5. **After:** results, statistics and printable certificates are open to everyone.

## Cleaning up data

The Admin login can open "Datenpflege" on the admin page. It shows all ratings in plain text, so it spoils the tasting while it's running. That's why Admin is a separate login from your player login.

| Action | Effect |
|---|---|
| Notiz löschen | Removes one note and keeps the rating |
| Wertung löschen | Removes one person's rating of one bowl |
| Ganze Schale löschen | Removes a bowl and all its ratings |
| Alles niederbrennen | Removes all bowls and ratings, keeps logins and the shopping list. Type `ASCHE` to confirm. |

Each of these saves a backup to `data/backups/` first. To restore one, stop the container and copy it over `data/tasting.json`. Deleting isn't possible during a running reveal. After the reveal, the ranking updates itself.

Players can change their own chips and delete them until someone else has rated them.

## Logins

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
| `data/images/` | Photos of bags, re-encoded as JPEG |
| `data/backups/` | A copy at most every 5 minutes while data changes, last 100 kept |
| `data/users.json` | Names and passphrase hashes |
| `data/secret.key` | Signs the login cookies. Deleting it logs everyone out. |

The admin page also offers CSV and JSON downloads, which never contain passphrases. Starting a new tasting: stop the container and move `data/tasting.json` somewhere else.

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
