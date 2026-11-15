"use strict";

// Results of a finished tasting. Everything, down to the questions, comes
// from the archive file, so this one page serves every past tasting.

const panel = document.getElementById("panel");
let data = null;
let activeChart = null;

function destroyChart() {
  if (activeChart) activeChart.destroy();
  activeChart = null;
}

function criteria() {
  return data.sections.flatMap((section) => section.criteria);
}

function scaleText(value) {
  return `${fmt(value)} / ${data.scale.max}`;
}

function renderRanking() {
  panel.append(heading("Rangliste", `Durchschnitt von „${data.ranking_label}“, von ${data.scale.min} bis ${data.scale.max}.`));
  panel.append(bars(data.ranking.map((row) => ({
    label: `${row.rank}. ${row.name}`,
    detail: [row.group, `${row.raters} Wertungen`].filter(Boolean).join(" · "),
    value: row.value,
    valueText: fmt(row.value),
  })), data.scale.max));
}

function renderAwards() {
  panel.append(heading("Trophäen", "Die Ehrungen dieser Verkostung."));
  for (const [kind, title] of [["item", "Für die Sorten"], ["person", "Für die Tafel"]]) {
    const awards = data.awards.filter((award) => award.kind === kind);
    if (!awards.length) continue;
    panel.append(el("h3", "", title));
    const grid = el("div", "award-grid");
    for (const award of awards) {
      const card = el("article", "award");
      card.append(el("h3", "", award.title));
      card.append(el("p", "award-winner", award.winner));
      card.append(el("p", "award-line", award.line));
      card.append(el("div", "award-stat", award.stat));
      grid.append(card);
    }
    panel.append(grid);
  }
}

function renderXray() {
  panel.append(heading("Röntgenblick", "Das ganze Profil einer Sorte gegen den Schnitt aller Sorten."));
  const select = el("select");
  select.setAttribute("aria-label", "Sorte auswählen");
  for (const row of data.ranking) {
    const option = el("option", "", `${row.rank}. ${row.name}`);
    option.value = row.id;
    select.append(option);
  }
  const { box, canvas } = chartBox();
  const details = el("details", "spoiler");
  details.append(el("summary", "", "Alle Werte als Tabelle"));
  const detailBody = el("div");
  details.append(detailBody);
  panel.append(select, box, details);
  const list = criteria();

  function show() {
    const row = data.ranking.find((r) => r.id === select.value);
    detailBody.replaceChildren(table(
      ["Kriterium", "Diese Sorte", "Alle Sorten"],
      list.map((c) => [c.label, fmt(row.averages[c.key]), fmt(data.overall[c.key])]),
      [1, 2],
    ));
    destroyChart();
    activeChart = new Chart(canvas, {
      type: "radar",
      data: {
        labels: list.map((c) => c.label),
        datasets: [
          {
            label: row.name,
            data: list.map((c) => row.averages[c.key]),
            borderColor: SERIES_CHIP,
            backgroundColor: SERIES_FILL,
            pointBackgroundColor: SERIES_CHIP,
            borderWidth: 2,
            pointRadius: 3,
            pointHitRadius: 14,
          },
          {
            label: "Schnitt aller Sorten",
            data: list.map((c) => data.overall[c.key]),
            borderColor: SERIES_GROUP,
            backgroundColor: "transparent",
            pointBackgroundColor: SERIES_GROUP,
            pointStyle: "rect",
            borderDash: [5, 4],
            borderWidth: 2,
            pointRadius: 3,
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
            max: data.scale.max,
            ticks: { stepSize: 1, backdropColor: "transparent", color: TEXT },
            grid: { color: GRID },
            angleLines: { color: GRID },
            pointLabels: { color: LABEL, font: { size: 10 } },
          },
        },
      },
    });
  }
  select.addEventListener("change", show);
  show();
}

function renderGroups() {
  panel.append(heading(data.group_label, "Die Lager gegeneinander, über alle Kriterien."));
  const list = criteria();
  const [a, b] = data.groups;
  const box = el("div", "chart-box");
  box.style.height = `${list.length * 34 + 90}px`;
  const canvas = el("canvas");
  box.append(canvas);
  panel.append(box);
  activeChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: list.map((c) => c.label),
      datasets: [a, b].map((group, i) => ({
        label: `${group.name} (${group.items})`,
        data: list.map((c) => group.averages[c.key]),
        backgroundColor: i === 0 ? SERIES_CHIP : SERIES_GROUP,
        borderRadius: 3,
      })),
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "top" },
        tooltip: { ...TOOLTIP, callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.parsed.x)}` } },
      },
      scales: {
        x: { min: 0, max: data.scale.max, grid: { color: GRID } },
        y: { grid: { display: false } },
      },
    },
  });
  if (data.groups.length > 2) {
    panel.append(table(
      ["Lager", "Sorten", data.ranking_label],
      data.groups.map((g) => [g.name, String(g.items), fmt(g.averages[data.ranking_key])]),
      [1, 2],
    ));
  }
}

function renderControversy() {
  panel.append(heading("Der Streit", `Wie weit die Wertungen für „${data.ranking_label}“ auseinanderliegen (Standardabweichung).`));
  const rows = data.ranking.filter((r) => r.spread !== null).sort((x, y) => y.spread - x.spread);
  if (!rows.length) {
    panel.append(emptyNote("Streit braucht mindestens zwei Meinungen zur selben Sorte."));
    return;
  }
  const max = Math.max(...rows.map((r) => r.spread), 1);
  panel.append(bars(rows.map((r) => ({ label: r.name, value: r.spread, valueText: fmt(r.spread) })), max));
}

function renderPeople() {
  panel.append(heading("Die Tafel", "Wer hat was geliebt, wer was verflucht?"));
  const grid = el("div", "person-grid");
  for (const person of data.people) {
    const card = el("article", "person");
    card.append(el("h3", "", person.name));
    const add = (title, entry) => {
      const line = el("p");
      line.append(el("b", "", title), `${entry.name} (${entry.value})`);
      card.append(line);
    };
    add("Top", person.best);
    add("Flop", person.worst);
    const distance = person.deviation === null ? "" : `, Ø ${fmt(person.deviation)} vom Rest entfernt`;
    card.append(el("p", "hint", `${person.ratings} Wertungen, Ø ${scaleText(person.average)}${distance}`));
    grid.append(card);
  }
  panel.append(grid);
}

function renderTwins() {
  panel.append(twinsBlock(data.twins, "die Sorten", "Sorten"));
}

function renderFlags() {
  for (const flag of data.flags) {
    panel.append(heading(flag.label, flag.hint || ""));
    panel.append(bars([
      { label: flag.label, detail: `${flag.count} Wertungen`, value: flag.with, valueText: fmt(flag.with) },
      { label: "Alle anderen", value: flag.without, valueText: fmt(flag.without) },
    ], data.scale.max));
    panel.append(el("p", "hint", `Dabei: ${flag.people.join(", ")}`));
  }
}

function renderNotes() {
  panel.append(heading("Notizen", "Ungefiltert von der Tafel."));
  for (const note of data.notes) {
    const card = el("article", "note");
    card.append(el("small", "", `${note.person} über ${note.item} · ${note.value} / ${data.scale.max}`));
    card.append(el("p", "", note.text));
    panel.append(card);
  }
}

function renderQuestions() {
  panel.append(heading("Fragebogen", `So wurde gefragt. Jede Frage lief von ${data.scale.min} bis ${data.scale.max}.`));
  for (const section of data.sections) {
    panel.append(el("h3", "", section.title));
    const list = el("ul", "question-list");
    for (const c of section.criteria) {
      const item = el("li");
      item.append(el("b", "", c.label));
      if (c.low || c.high) item.append(el("span", "", `${c.low || ""} → ${c.high || ""}`));
      list.append(item);
    }
    panel.append(list);
  }
}

function tabs() {
  const list = [
    ["Rangliste", renderRanking],
    ["Trophäen", renderAwards],
    ["Röntgenblick", renderXray],
  ];
  if (data.groups.length >= 2) list.push([data.group_label, renderGroups]);
  list.push(["Streit", renderControversy], ["Die Tafel", renderPeople], ["Zwillinge", renderTwins]);
  if (data.flags.length) list.push([data.flags[0].label, renderFlags]);
  if (data.notes.length) list.push(["Notizen", renderNotes]);
  list.push(["Fragebogen", renderQuestions]);
  return list;
}

function renderSummary() {
  const s = data.summary;
  const tiles = [
    [s.items, "Sorten"],
    [s.people, "Leute"],
    [s.ratings, "Wertungen"],
    [fmt(s.average), `Ø ${data.ranking_label}`],
  ];
  document.getElementById("summary").replaceChildren(...tiles.map(([value, label]) => {
    const tile = el("div", "tile");
    tile.append(el("strong", "", value), el("span", "", label));
    return tile;
  }));
}

async function start() {
  try {
    data = await getJson(panel.dataset.resultsUrl);
  } catch (err) {
    const box = document.getElementById("load-error");
    box.textContent = `Die Ergebnisse ließen sich nicht laden (${err.message}). Lade die Seite neu.`;
    box.hidden = false;
    return;
  }
  renderSummary();
  const list = tabs();
  const tabBar = document.getElementById("tabs");
  const select = (index) => {
    destroyChart();
    panel.replaceChildren();
    tabBar.querySelectorAll(".tab").forEach((tab, i) => {
      tab.setAttribute("aria-selected", String(i === index));
      if (i === index) tab.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
    list[index][1]();
  };
  list.forEach(([title], index) => {
    const tab = el("button", "tab", title);
    tab.type = "button";
    tab.addEventListener("click", () => select(index));
    tabBar.append(tab);
  });
  select(0);
}

start();
