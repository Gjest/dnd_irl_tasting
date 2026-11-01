"use strict";

const SERIES_CHIP = "#dc6a12";
const SERIES_GROUP = "#3d90d0";
const TEXT = "#c2b19a";
const GRID = "rgba(194, 177, 154, .16)";
const TOOLTIP = { backgroundColor: "#271a16", borderColor: "#4a332a", borderWidth: 1, titleColor: "#efe4d2", bodyColor: "#efe4d2" };

Chart.defaults.color = TEXT;
Chart.defaults.font.family = "Lato, sans-serif";
Chart.defaults.locale = "de-DE";

const panel = document.getElementById("panel");
let data = null;
let activeChart = null;

function destroyChart() {
  if (activeChart) activeChart.destroy();
  activeChart = null;
}

function heading(title, hint) {
  const fragment = document.createDocumentFragment();
  fragment.append(el("h2", "", title));
  if (hint) fragment.append(el("p", "hint", hint));
  return fragment;
}

function emptyNote(text) {
  return el("p", "empty", text);
}

function bars(rows, max) {
  const wrap = el("div", "bars");
  for (const row of rows) {
    const item = el("div", "bar-row");
    const label = el("span", "bar-label", row.label);
    if (row.detail) label.append(el("small", "", row.detail));
    item.append(label, el("span", "bar-value", row.valueText));
    const track = el("div", "bar-track");
    const fill = el("div", "bar-fill");
    fill.style.width = `${Math.max(0, Math.min(100, (row.value / max) * 100))}%`;
    track.append(fill);
    item.append(track);
    wrap.append(item);
  }
  return wrap;
}

function table(headers, rows, numericColumns = []) {
  const wrap = el("div", "table-wrap");
  const tbl = el("table");
  const headRow = el("tr");
  headers.forEach((text, i) => headRow.append(el("th", numericColumns.includes(i) ? "num" : "", text)));
  const thead = el("thead");
  thead.append(headRow);
  const tbody = el("tbody");
  for (const row of rows) {
    const tr = el("tr");
    row.forEach((text, i) => tr.append(el("td", numericColumns.includes(i) ? "num" : "", text)));
    tbody.append(tr);
  }
  tbl.append(thead, tbody);
  wrap.append(tbl);
  return wrap;
}

function chartBox(short) {
  const box = el("div", short ? "chart-box chart-box-short" : "chart-box");
  const canvas = el("canvas");
  box.append(canvas);
  return { box, canvas };
}

// --- Tabs ------------------------------------------------------------------

function renderRanking() {
  const rated = data.chips.filter((c) => c.enjoyment !== null);
  panel.append(heading("Rangliste", "Durchschnittlicher Genuss-Wurf (d20). Bei Gleichstand entscheidet die Harmonie."));
  panel.append(bars(rated.map((c) => ({
    label: `${c.rank}. ${c.label}`,
    detail: `${c.flavor_type} · ${c.raters} Wertungen`,
    value: c.enjoyment,
    valueText: fmt(c.enjoyment),
  })), 20));
}

function renderXray() {
  panel.append(heading("Röntgenblick", "Das Sinnesprofil einer Schale gegen den Schnitt aller Schalen. Alle Achsen laufen von 1 bis 5."));
  const rated = data.chips.filter((c) => c.enjoyment !== null);
  const select = el("select");
  select.setAttribute("aria-label", "Chips auswählen");
  for (const chip of rated) {
    const option = el("option", "", chip.label);
    option.value = chip.id;
    select.append(option);
  }
  const facts = el("div", "fact-row");
  const { box, canvas } = chartBox();
  const details = el("details", "spoiler");
  details.append(el("summary", "", "Alle Werte als Tabelle"));
  const detailBody = el("div");
  details.append(detailBody);
  panel.append(select, facts, box, details);

  function show() {
    const chip = rated.find((c) => c.id === select.value);
    const npc = chip.npc.slice().sort((a, b) => b.votes - a.votes)[0];
    const items = [
      ["Genuss", `${fmt(chip.enjoyment)} / 20`],
      ["Seelenmünzen", chip.coins === null ? "–" : fmt(chip.coins)],
      ["Verträge", String(chip.contracts)],
      ["Als NPC", npc ? `${npc.name} (${npc.votes})` : "–"],
    ];
    facts.replaceChildren(...items.map(([label, value]) => {
      const fact = el("span", "fact", `${label}: `);
      fact.append(el("b", "", value));
      return fact;
    }));
    detailBody.replaceChildren(table(
      ["Kategorie", "Diese Schale", "Alle Schalen"],
      data.scale_keys.map((key, i) => [data.scale_labels[i], fmt(chip.scales[key]), fmt(data.scale_averages[key])]),
      [1, 2],
    ));
    destroyChart();
    activeChart = new Chart(canvas, {
      type: "radar",
      data: {
        labels: data.scale_labels,
        datasets: [
          {
            label: chip.label,
            data: data.scale_keys.map((k) => chip.scales[k]),
            borderColor: SERIES_CHIP,
            backgroundColor: "rgba(220, 106, 18, .22)",
            pointBackgroundColor: SERIES_CHIP,
            borderWidth: 2,
            pointRadius: 3,
            pointHoverRadius: 6,
            pointHitRadius: 14,
          },
          {
            label: "Schnitt aller Schalen",
            data: data.scale_keys.map((k) => data.scale_averages[k]),
            borderColor: SERIES_GROUP,
            backgroundColor: "transparent",
            pointBackgroundColor: SERIES_GROUP,
            pointStyle: "rect",
            borderDash: [5, 4],
            borderWidth: 2,
            pointRadius: 3,
            pointHoverRadius: 6,
            pointHitRadius: 14,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: "bottom", labels: { usePointStyle: true } },
          tooltip: { ...TOOLTIP, callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.r)}` } },
        },
        scales: {
          r: {
            min: 0,
            max: 5,
            ticks: { stepSize: 1, backdropColor: "transparent", color: TEXT },
            grid: { color: GRID },
            angleLines: { color: GRID },
            pointLabels: { color: "#efe4d2", font: { size: 11 } },
          },
        },
      },
    });
  }
  select.addEventListener("change", show);
  show();
}

function renderControversy() {
  panel.append(heading("Der Blutkrieg", "Wie weit die Genuss-Würfe auseinanderliegen (Standardabweichung). Je länger der Balken, desto lauter der Streit."));
  const rows = data.chips.filter((c) => c.spread !== null).sort((a, b) => b.spread - a.spread);
  if (!rows.length) {
    panel.append(emptyNote("Streit braucht mindestens zwei Meinungen zur selben Schale."));
    return;
  }
  const max = Math.max(...rows.map((r) => r.spread), 1);
  panel.append(bars(rows.map((c) => ({ label: c.label, value: c.spread, valueText: fmt(c.spread) })), max));
}

// Diverging scale: red for opposite taste, gray at zero, blue for shared taste.
function heatColor(r) {
  const neutral = [58, 50, 46];
  const end = r >= 0 ? [40, 110, 170] : [190, 50, 40];
  const t = Math.min(1, Math.abs(r));
  return `rgb(${neutral.map((n, i) => Math.round(n + (end[i] - n) * t)).join(",")})`;
}

function renderTwins() {
  const twins = data.twins;
  panel.append(heading("Geschmackszwillinge", `Wie ähnlich zwei Personen die Chips bewerten: +1 heißt gleicher Geschmack, −1 das genaue Gegenteil. Braucht mindestens ${twins.min_shared} gemeinsame Schalen.`));
  if (!twins.closest) {
    panel.append(emptyNote("Dafür gibt es noch zu wenige gemeinsame Wertungen."));
    return;
  }
  const callouts = el("div", "callouts");
  const addCallout = (title, pair) => {
    const box = el("div", "person");
    box.append(el("h3", "", title));
    box.append(el("p", "", `${pair.a} & ${pair.b}`));
    box.append(el("p", "hint", `Übereinstimmung ${fmt(pair.r, 2)} über ${pair.shared} Schalen`));
    callouts.append(box);
  };
  addCallout("Seelenverwandte", twins.closest);
  if (twins.furthest) addCallout("Erzfeinde", twins.furthest);
  panel.append(callouts);

  const wrap = el("div", "table-wrap");
  const tbl = el("table", "heat");
  const head = el("tr");
  head.append(el("th"));
  twins.names.forEach((name) => head.append(el("th", "", name)));
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  twins.matrix.forEach((row, i) => {
    const tr = el("tr");
    tr.append(el("th", "", twins.names[i]));
    row.forEach((value, j) => {
      const cell = el("td", i === j || value === null ? "self" : "", i === j ? "" : value === null ? "–" : fmt(value, 2));
      if (i !== j && value !== null) {
        cell.style.background = heatColor(value);
        cell.style.color = "#fff";
      }
      tr.append(cell);
    });
    tbody.append(tr);
  });
  tbl.append(thead, tbody);
  wrap.append(tbl);
  panel.append(wrap);
}

function renderBattles() {
  panel.append(heading("Schlachten", "Durchschnittlicher Genuss nach Lager."));
  const { flavor, brand } = data.battles;
  panel.append(el("h3", "", "Geschmacksrichtungen"));
  panel.append(flavor.length
    ? bars(flavor.map((r) => ({ label: r.label, detail: `${r.chips} Schalen`, value: r.value, valueText: fmt(r.value) })), 20)
    : emptyNote("Für diese Schlacht braucht es mindestens zwei Geschmacksrichtungen."));
  panel.append(el("h3", "", "Markenprodukt gegen Eigenmarke"));
  panel.append(brand.length
    ? bars(brand.map((r) => ({ label: r.label, detail: `${r.chips} Schalen`, value: r.value, valueText: fmt(r.value) })), 20)
    : emptyNote("Für diese Schlacht braucht es beide Lager."));
}

function renderCoins() {
  panel.append(heading("Seelenmünzen", "Wie viele Seelenmünzen die Gruppe für eine Tüte zahlen würde, gegen den echten Preis. Höher und weiter links ist das bessere Geschäft."));
  const rows = data.chips.filter((c) => c.price !== null && c.coins !== null);
  if (rows.length) {
    const { box, canvas } = chartBox(true);
    panel.append(box);
    activeChart = new Chart(canvas, {
      type: "scatter",
      data: {
        datasets: [{
          label: "Chips",
          data: rows.map((c) => ({ x: c.price, y: c.coins, label: c.label })),
          backgroundColor: SERIES_CHIP,
          borderColor: "#1a1210",
          borderWidth: 2,
          pointRadius: 8,
          pointHoverRadius: 10,
          pointHitRadius: 14,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            ...TOOLTIP,
            callbacks: {
              title: (items) => items[0].raw.label,
              label: (c) => `${fmt(c.raw.x, 2)} € · ${fmt(c.raw.y)} Seelenmünzen`,
            },
          },
        },
        scales: {
          x: { title: { display: true, text: "Preis pro Tüte (€)" }, grid: { color: GRID }, beginAtZero: true },
          y: { title: { display: true, text: "Ø Seelenmünzen" }, grid: { color: GRID }, min: 0, max: 10 },
        },
      },
    });
  } else {
    panel.append(emptyNote("Für das Diagramm braucht es Preise und Münzgebote."));
  }
  const all = data.chips.filter((c) => c.enjoyment !== null);
  panel.append(table(
    ["Chips", "Preis", "Ø Münzen", "Verträge"],
    all.map((c) => [c.label, c.price === null ? "–" : `${fmt(c.price, 2)} €`, fmt(c.coins), String(c.contracts)]),
    [1, 2, 3],
  ));
}

function renderOracle() {
  const g = data.guessing;
  panel.append(heading("Das Orakel", `Blinde Tipps: ${g.points_flavor} Punkte für den Geschmack, ${g.points_brand} für die Marke. Eigene Chips zählen nicht.`));
  panel.append(table(
    ["Platz", "Wer", "Punkte", "Geschmack", "Marke"],
    g.board.map((r, i) => [`${i + 1}.`, r.name, String(r.points), String(r.flavor_hits), String(r.brand_hits)]),
    [2, 3, 4],
  ));
}

function renderAwards() {
  const groups = [
    ["chip", "Für die Chips"],
    ["player", "Für die Gruppe"],
  ];
  panel.append(heading("Trophäen", "Jede Trophäe gibt es auch als druckbaren Höllenvertrag."));
  for (const [kind, title] of groups) {
    panel.append(el("h3", "", title));
    const grid = el("div", "award-grid");
    for (const award of data.awards.filter((a) => a.kind === kind)) {
      const card = el("article", "award");
      card.append(el("h3", "", award.title));
      card.append(el("p", "award-winner", award.winner));
      card.append(el("p", "award-line", award.line));
      card.append(el("div", "award-stat", award.stat));
      const link = el("a", "", "Vertrag ansehen");
      link.href = `/urkunde/${encodeURIComponent(award.key)}`;
      card.append(link);
      grid.append(card);
    }
    panel.append(grid);
  }
}

function renderTops() {
  panel.append(heading("Tops & Flops", "Was alle am meisten geliebt und am meisten verflucht haben."));
  const grid = el("div", "person-grid");
  for (const person of data.tops) {
    const card = el("article", "person");
    card.append(el("h3", "", person.name));
    if (!person.best) {
      card.append(el("p", "empty", "Hat nichts gewertet."));
    } else {
      const add = (title, entry) => {
        const line = el("p");
        line.append(el("b", "", title), `${entry.label} (${entry.value})`);
        card.append(line);
      };
      add("Top", person.best);
      add("Flop", person.worst);
      card.append(el("p", "hint", `${person.rated} Schalen, Ø ${fmt(person.average)}`));
    }
    grid.append(card);
  }
  panel.append(grid);
}

function renderNotes() {
  panel.append(heading("Notizen der Abenteurer", "Ungefiltert vom Verkostungstisch."));
  if (!data.notes.length) {
    panel.append(emptyNote("Alle haben geschwiegen. Verdächtig."));
    return;
  }
  for (const note of data.notes) {
    const card = el("article", "note");
    card.append(el("small", "", `${note.player} über ${note.chip} · Wurf ${note.enjoyment}`));
    card.append(el("p", "", note.text));
    panel.append(card);
  }
}

const TABS = [
  ["Rangliste", renderRanking],
  ["Trophäen", renderAwards],
  ["Röntgenblick", renderXray],
  ["Blutkrieg", renderControversy],
  ["Zwillinge", renderTwins],
  ["Schlachten", renderBattles],
  ["Seelenmünzen", renderCoins],
  ["Orakel", renderOracle],
  ["Tops & Flops", renderTops],
  ["Notizen", renderNotes],
];

function selectTab(index) {
  destroyChart();
  panel.replaceChildren();
  document.querySelectorAll(".tab").forEach((tab, i) => {
    tab.setAttribute("aria-selected", String(i === index));
    if (i === index) tab.scrollIntoView({ block: "nearest", inline: "nearest" });
  });
  TABS[index][1]();
}

function renderSummary() {
  const s = data.summary;
  const tiles = [
    [s.chips, "Schalen"],
    [s.ratings, "Wertungen"],
    [fmt(s.average), "Ø Genuss"],
    [s.nat20, "Nat 20"],
    [s.nat1, "Nat 1"],
  ];
  document.getElementById("summary").replaceChildren(...tiles.map(([value, label]) => {
    const tile = el("div", "tile");
    tile.append(el("strong", "", value), el("span", "", label));
    return tile;
  }));
}

async function start() {
  try {
    data = await getJson("/api/results");
  } catch (err) {
    document.getElementById("load-error").hidden = false;
    return;
  }
  renderSummary();
  const tabBar = document.getElementById("tabs");
  TABS.forEach(([title], index) => {
    const tab = el("button", "tab", title);
    tab.type = "button";
    tab.addEventListener("click", () => selectTab(index));
    tabBar.append(tab);
  });
  selectTab(0);
}

start();
