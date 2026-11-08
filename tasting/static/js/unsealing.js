"use strict";

const REFRESH_MS = 2500;
const root = document.getElementById("ceremony");
const list = document.getElementById("ceremony-list");
const statusLine = document.getElementById("ceremony-status");
const nextButton = document.getElementById("ceremony-next");
const doneLink = document.getElementById("ceremony-done");
let shown = -1;

function card(chip, isNew) {
  const item = el("li", "reveal-card");
  if (chip.place === 1) item.classList.add("reveal-first");
  if (isNew) item.classList.add("reveal-new");
  item.append(el("span", "reveal-place", chip.place === 1 ? "♛" : `${chip.place}.`));
  const name = el("div");
  if (chip.image) {
    const photo = el("img", "reveal-photo");
    photo.src = `/bild/${encodeURIComponent(chip.image)}`;
    photo.alt = "";
    name.append(photo);
  }
  name.append(el("span", "reveal-name", chip.label));
  name.append(el("span", "reveal-meta", `Schale ${chip.bowl} · ${chip.flavor_type}`));
  item.append(name);
  item.append(el("span", "reveal-score", `DC ${fmt(chip.dc)}`));
  return item;
}

function render(data) {
  const finished = data.phase === "revealed";
  statusLine.textContent = finished
    ? "Alle Siegel sind gebrochen."
    : data.reveal_count === 0
      ? `${data.total} Siegel warten. Der Admin hat das Wort.`
      : `${data.reveal_count} von ${data.total} Siegeln gebrochen.`;
  if (nextButton) {
    nextButton.hidden = finished;
    const remaining = data.total - data.reveal_count;
    nextButton.textContent = remaining === 1 ? "Den Sieger enthüllen" : "Nächste Schale enthüllen";
  }
  doneLink.hidden = !finished;
  if (data.reveal_count === shown) return;
  const firstRender = shown === -1;
  shown = data.reveal_count;
  // Newest on top, so the winner lands at the top of the list.
  const items = data.revealed.map((chip, index) =>
    card(chip, !firstRender && index === data.revealed.length - 1)).reverse();
  list.replaceChildren(...items);
}

async function refresh() {
  try {
    const data = await getJson("/api/ceremony");
    if (data.phase === "tasting") {
      window.location.href = "/";
      return;
    }
    render(data);
  } catch (err) {
    statusLine.textContent = "Die Verbindung ist abgerissen. Neuer Versuch läuft.";
  }
}

if (nextButton) {
  nextButton.addEventListener("click", async () => {
    nextButton.disabled = true;
    try {
      render(await postJson(root.dataset.nextUrl));
    } catch (err) {
      statusLine.textContent = "Das Siegel hält noch. Versuch es noch einmal.";
    }
    nextButton.disabled = false;
  });
}

refresh();
setInterval(refresh, REFRESH_MS);
