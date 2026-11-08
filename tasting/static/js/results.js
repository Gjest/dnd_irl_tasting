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
  const rated = data.chips.filter((c) => c.dc !== null);
  panel.append(heading("Rangliste", "Durchschnittlicher DC des Sucht-Saves: je höher, desto schwerer kommst du von der Schale los. Bei Gleichstand entscheidet die Harmonie."));
  panel.append(bars(rated.map((c) => ({
    label: `${c.rank}. ${c.label}`,
    detail: `${c.tier.name} · ${c.flavor_type} · ${c.raters} Wertungen`,
    value: c.dc,
    valueText: fmt(c.dc),
  })), 20));
}

function renderXray() {
  panel.append(heading("Röntgenblick", "Das Sinnesprofil einer Schale gegen den Schnitt aller Schalen. Alle Achsen laufen von 1 bis 5."));
  const rated = data.chips.filter((c) => c.dc !== null);
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
    const items = [
      ["Sucht-DC", fmt(chip.dc)],
      ["Zustand", chip.tier.name],
      ["Gesinnung", chip.alignment.name],
      ["Verträge", String(chip.contracts)],
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
  panel.append(heading("Der Blutkrieg", "Wie weit die Sucht-DCs auseinanderliegen (Standardabweichung). Je länger der Balken, desto lauter der Streit."));
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
  panel.append(heading("Schlachten", "Durchschnittlicher Sucht-DC nach Lager."));
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

function verdictBox(title, r, verdict) {
  const box = el("div", "person");
  box.append(el("h3", "", title));
  box.append(el("p", "", verdict));
  box.append(el("p", "hint", `Korrelation ${fmt(r, 2)}`));
  return box;
}

function renderCoins() {
  const pricing = data.pricing;
  panel.append(heading("Seelenmünzen", "Blind geschätzt: Wie teuer wirkt die Schale, verglichen mit dem echten Preis pro 100 g? Korrelation +1 heißt perfekt getroffen, 0 reiner Zufall, −1 genau verkehrt herum."));
  const callouts = el("div", "callouts");
  if (pricing.guess_r !== null) callouts.append(verdictBox("Preisgefühl der Gruppe", pricing.guess_r, pricing.guess_verdict));
  if (pricing.dc_r !== null) callouts.append(verdictBox("Macht teuer süchtig?", pricing.dc_r, pricing.dc_verdict));
  if (callouts.childElementCount) panel.append(callouts);
  else panel.append(emptyNote(`Für Korrelationen braucht es mindestens ${pricing.min_chips} Schalen mit Preis, Gewicht und Schätzung.`));

  const rows = data.chips.filter((c) => c.price_100g !== null && c.coins !== null);
  if (rows.length) {
    const { box, canvas } = chartBox(true);
    panel.append(box);
    activeChart = new Chart(canvas, {
      type: "scatter",
      data: {
        datasets: [{
          label: "Chips",
          data: rows.map((c) => ({ x: c.price_100g, y: c.coins, label: c.label })),
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
              label: (c) => `${fmt(c.raw.x, 2)} € pro 100 g · ${fmt(c.raw.y)} Seelenmünzen`,
            },
          },
        },
        scales: {
          x: { title: { display: true, text: "Echter Preis pro 100 g (€)" }, grid: { color: GRID }, beginAtZero: true },
          y: { title: { display: true, text: "Ø geschätzte Seelenmünzen" }, grid: { color: GRID }, min: 0, max: 10 },
        },
      },
    });
  }

  if (pricing.readers.length) {
    panel.append(el("h3", "", "Wer riecht den Preis?"));
    panel.append(table(
      ["Wer", "Preisgefühl", "Schalen"],
      pricing.readers.map((r) => [r.name, fmt(r.r, 2), String(r.chips)]),
      [1, 2],
    ));
  }

  panel.append(el("h3", "", "Alle Schalen"));
  panel.append(table(
    ["Chips", "Tüte", "Gewicht", "€/100 g", "Ø Münzen", "Verträge"],
    data.chips.filter((c) => c.dc !== null).map((c) => [
      c.label,
      c.price === null ? "–" : `${fmt(c.price, 2)} €`,
      c.weight ? `${fmt(c.weight, 0)} g` : "–",
      c.price_100g === null ? "–" : `${fmt(c.price_100g, 2)} €`,
      fmt(c.coins),
      String(c.contracts),
    ]),
    [1, 2, 3, 4, 5],
  ));
}

const LAW_ORDER = ["lawful", "neutral", "chaotic"];
const GOOD_ORDER = ["good", "neutral", "evil"];

function alignmentBlock(title, entries, textKey) {
  panel.append(el("h3", "", title));
  const grid = el("div", "alignment-grid");
  for (const good of GOOD_ORDER) {
    for (const law of LAW_ORDER) {
      const here = entries.filter((e) => e.alignment.law === law && e.alignment.good === good);
      const cell = el("div", here.length ? "alignment-cell alignment-filled" : "alignment-cell");
      // The soft hyphen keeps the longest word from breaking mid-syllable on phones.
      cell.append(el("h4", "", data.alignment_names[`${law}/${good}`].replace("Rechtschaffen", "Recht\u00adschaffen")));
      for (const entry of here) cell.append(el("p", "", entry.name));
      grid.append(cell);
    }
  }
  panel.append(grid);
  const seen = new Set();
  for (const entry of entries) {
    if (seen.has(entry.alignment.name)) continue;
    seen.add(entry.alignment.name);
    const card = el("article", "note");
    card.append(el("small", "", entry.alignment.name));
    card.append(el("p", "", entry.alignment[textKey]));
    panel.append(card);
  }
}

function renderAlignment() {
  panel.append(heading("Gesinnung", "Chips: Ordnung kommt von Integrität, Harmonie und einem einigen Tisch, das Gute von Kartoffel und Harmonie statt Künstlichkeit, Schärfe und Durst. Abenteurer: Wer mit der Gruppe geht, ist rechtschaffen. Wer großzügig bewertet und keine Höllenverträge unterschreibt, ist gut."));
  const chips = data.chips.filter((c) => c.alignment).map((c) => ({ name: c.label, alignment: c.alignment }));
  alignmentBlock("Die Chips", chips, "chip");
  const people = data.player_alignments;
  alignmentBlock("Die Abenteurer", people, "player");
}

function renderSheets() {
  panel.append(heading("Charakterbögen", "Jede Schale als Charakter: Die Attribute kommen aus den Bewertungen, die Zustände aus allem, was deutlich aus dem Rahmen fällt."));
  const grid = el("div", "person-grid");
  for (const chip of data.chips.filter((c) => c.dc !== null)) {
    const card = el("article", "person");
    if (chip.image) {
      const photo = el("img", "sheet-photo");
      photo.src = `/bild/${encodeURIComponent(chip.image)}`;
      photo.alt = "";
      card.append(photo);
    }
    card.append(el("h3", "", chip.label));
    card.append(el("p", "hint", `Sucht-Save DC ${fmt(chip.dc)}: ${chip.tier.name}. ${chip.tier.line}`));
    const sheet = el("div", "sheet");
    for (const attribute of chip.sheet) {
      const cell = el("div", "sheet-cell");
      cell.title = attribute.name;
      const sign = attribute.modifier >= 0 ? "+" : "−";
      cell.append(el("b", "", attribute.label), el("strong", "", String(attribute.score)), el("small", "", `${sign}${Math.abs(attribute.modifier)}`));
      sheet.append(cell);
    }
    card.append(sheet);
    const list = el("ul", "condition-list");
    if (!chip.conditions.length) list.append(el("li", "", "Keine Zustände. Langweilig, aber gesund."));
    for (const condition of chip.conditions) {
      const item = el("li");
      item.append(el("b", "", `${condition.name}: `), condition.line);
      list.append(item);
    }
    card.append(list);
    grid.append(card);
  }
  panel.append(grid);
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
      card.append(el("p", "hint", `${person.rated} Schalen, Ø DC ${fmt(person.average)}. Zustand am Tisch: ${person.tier.name}.`));
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
    card.append(el("small", "", `${note.player} über ${note.chip} · DC ${note.dc}`));
    card.append(el("p", "", note.text));
    panel.append(card);
  }
}

const TABS = [
  ["Rangliste", renderRanking],
  ["Trophäen", renderAwards],
  ["Gesinnung", renderAlignment],
  ["Charakterbögen", renderSheets],
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
    [fmt(s.average), "Ø Sucht-DC"],
    [s.dc20, "× DC 20"],
    [s.dc1, "× DC 1"],
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
