"use strict";

const REFRESH_MS = 8000;
const grid = document.getElementById("bowls");
const rateUrl = grid.dataset.rateUrl;
let lastSnapshot = null;

function renderBowls(bowls) {
  document.getElementById("no-bowls").hidden = bowls.length > 0;
  grid.replaceChildren(...bowls.map((bowl) => {
    const link = el("a", bowl.mine ? "bowl bowl-done" : "bowl");
    link.href = rateUrl.replace("__id__", encodeURIComponent(bowl.id));
    link.append(el("span", "bowl-number", bowl.bowl));
    const state = bowl.mine ? "✓ Gewertet" : "Offen";
    link.append(el("span", "bowl-state", bowl.brought ? `${state} · Deine` : state));
    return link;
  }));
}

function renderProgress(players) {
  document.getElementById("progress").replaceChildren(...players.map((player) => {
    const row = el("li");
    row.append(el("span", "", player.name));
    row.append(player.missing.length
      ? el("span", "", `fehlt: ${player.missing.join(", ")}`)
      : el("span", "done", "✓ Fertig"));
    return row;
  }));
}

async function refresh() {
  const error = document.getElementById("load-error");
  try {
    const data = await getJson("/api/progress");
    if (data.phase !== "tasting") {
      window.location.href = "/";
      return;
    }
    // Only touch the DOM on changes, so a refresh can't swallow a tap on a bowl.
    const snapshot = JSON.stringify(data);
    if (snapshot !== lastSnapshot) {
      lastSnapshot = snapshot;
      renderBowls(data.bowls);
      renderProgress(data.players);
    }
    error.hidden = true;
  } catch (err) {
    error.hidden = false;
  }
}

refresh();
setInterval(refresh, REFRESH_MS);
