#!/usr/bin/env bash
# First-time setup: writes .env, builds and starts the container, creates logins.
# Safe to run again. Existing .env, logins and ratings are kept.
set -euo pipefail
cd "$(dirname "$0")"

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose wurde nicht gefunden. Bitte zuerst Docker installieren." >&2
  exit 1
fi

if [ ! -f .env ]; then
  detected="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' || true)"
  read -r -p "WLAN-IP dieses Laptops [${detected:-keine erkannt}]: " bind_ip
  bind_ip="${bind_ip:-$detected}"
  if ! [[ "$bind_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || [ "$bind_ip" = "0.0.0.0" ]; then
    echo "Das ist keine brauchbare IP: '$bind_ip'" >&2
    exit 1
  fi
  sed -e "s/^BIND_IP=.*/BIND_IP=$bind_ip/" \
      -e "s/^PUID=.*/PUID=$(id -u)/" \
      -e "s/^PGID=.*/PGID=$(id -g)/" \
      .env.example > .env
  echo ".env angelegt."
fi

mkdir -p data
docker compose up -d --build

# Give the container a moment to come up before talking to it.
for _ in $(seq 1 20); do
  if docker compose exec -T app python -c "pass" >/dev/null 2>&1; then break; fi
  sleep 1
done
docker compose exec -T app python -m tasting.manage init

source_ip="$(sed -n 's/^BIND_IP=//p' .env)"
port="$(sed -n 's/^PORT=//p' .env)"
echo "Läuft: http://${source_ip}:${port:-9001}"
