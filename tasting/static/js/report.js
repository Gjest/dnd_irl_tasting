"use strict";

// Building blocks shared by every results page: chart colors and the
// bars, tables and headings the tabs are made of.

const SERIES_CHIP = "#dc6a12";
const SERIES_GROUP = "#3d90d0";
const TEXT = "#c2b19a";
const GRID = "rgba(194, 177, 154, .16)";
const TOOLTIP = { backgroundColor: "#271a16", borderColor: "#4a332a", borderWidth: 1, titleColor: "#efe4d2", bodyColor: "#efe4d2" };

Chart.defaults.color = TEXT;
Chart.defaults.font.family = "Lato, sans-serif";
Chart.defaults.locale = "de-DE";

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

// Diverging scale: red for opposite taste, gray at zero, blue for shared taste.
function heatColor(r) {
  const neutral = [58, 50, 46];
  const end = r >= 0 ? [40, 110, 170] : [190, 50, 40];
  const t = Math.min(1, Math.abs(r));
  return `rgb(${neutral.map((n, i) => Math.round(n + (end[i] - n) * t)).join(",")})`;
}

function verdictBox(title, r, verdict) {
  const box = el("div", "person");
  box.append(el("h3", "", title));
  box.append(el("p", "", verdict));
  box.append(el("p", "hint", `Korrelation ${fmt(r, 2)}`));
  return box;
}

// Taste twins: who rates like whom, as callouts and a heat map.
function twinsBlock(twins, rated, unit) {
  const fragment = document.createDocumentFragment();
  fragment.append(heading("Geschmackszwillinge", `Wie ähnlich zwei Personen ${rated} bewerten: +1 heißt gleicher Geschmack, −1 das genaue Gegenteil. Braucht mindestens ${twins.min_shared} gemeinsame ${unit}.`));
  if (!twins.closest) {
    fragment.append(emptyNote("Dafür gibt es zu wenige gemeinsame Wertungen."));
    return fragment;
  }
  const callouts = el("div", "callouts");
  const addCallout = (title, pair) => {
    const box = el("div", "person");
    box.append(el("h3", "", title));
    box.append(el("p", "", `${pair.a} & ${pair.b}`));
    box.append(el("p", "hint", `Übereinstimmung ${fmt(pair.r, 2)} über ${pair.shared} ${unit}`));
    callouts.append(box);
  };
  addCallout("Seelenverwandte", twins.closest);
  if (twins.furthest) addCallout("Erzfeinde", twins.furthest);
  fragment.append(callouts);

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
  fragment.append(wrap);
  return fragment;
}
