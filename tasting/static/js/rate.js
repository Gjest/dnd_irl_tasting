"use strict";

const form = document.getElementById("rate-form");
const draftKey = form.dataset.draftKey;
const countLabel = document.getElementById("rate-count");
const requiredNames = [...new Set(
  [...form.querySelectorAll("input[type=radio][required]")].map((input) => input.name),
)];

function updateCount() {
  const done = requiredNames.filter((name) => form.querySelector(`input[name="${name}"]:checked`)).length;
  countLabel.textContent = done === requiredNames.length
    ? "Alles bewertet"
    : `${done} von ${requiredNames.length} bewertet`;
}

// Browser storage may be unavailable (private mode), so a draft is only a bonus.
function saveDraft() {
  const entries = [...new FormData(form).entries()].filter(([name]) => name !== "csrf_token");
  try {
    localStorage.setItem(draftKey, JSON.stringify(entries));
  } catch (err) { /* ignored */ }
}

function restoreDraft() {
  let entries = null;
  try {
    entries = JSON.parse(localStorage.getItem(draftKey));
  } catch (err) { /* ignored */ }
  if (!Array.isArray(entries)) return;
  for (const [name, value] of entries) {
    const field = form.elements.namedItem(name);
    if (!field) continue;
    if (field instanceof RadioNodeList) {
      for (const radio of field) radio.checked = radio.value === value;
    } else {
      field.value = value;
    }
  }
}

function clearDraft() {
  try {
    localStorage.removeItem(draftKey);
  } catch (err) { /* ignored */ }
}

let critTimer = null;
function showCrit(isHit) {
  const crit = document.getElementById("crit");
  crit.hidden = true;
  void crit.offsetWidth; // restarts the animation on repeated clicks
  crit.className = isHit ? "crit crit-hit" : "crit crit-fail";
  document.getElementById("crit-text").textContent = isHit ? "Kritischer Treffer!" : "Kritischer Patzer!";
  crit.hidden = false;
  clearTimeout(critTimer);
  critTimer = setTimeout(() => { crit.hidden = true; }, 1600);
}

if (form.dataset.hasSaved !== "1") restoreDraft();
updateCount();

form.addEventListener("input", (event) => {
  saveDraft();
  updateCount();
  if (event.target.name === "enjoyment") {
    if (event.target.value === "20") showCrit(true);
    if (event.target.value === "1") showCrit(false);
  }
});
form.addEventListener("submit", clearDraft);
