"use strict";

const form = document.getElementById("rate-form");
const draftKey = form.dataset.draftKey;
const countLabel = document.getElementById("rate-count");
const requiredNames = [...new Set(
  [...form.querySelectorAll("input[type=radio][required]")].map((input) => input.name),
)];
const dcInput = form.elements.namedItem("dc");

function updateCount() {
  const done = requiredNames.filter((name) => form.querySelector(`input[name="${name}"]:checked`)).length
    + (dcInput.value ? 1 : 0);
  const total = requiredNames.length + 1;
  countLabel.textContent = done === total ? "Alles bewertet" : `${done} von ${total} bewertet`;
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
function showCrit(isTop) {
  const crit = document.getElementById("crit");
  crit.hidden = true;
  void crit.offsetWidth; // restarts the animation on repeated clicks
  crit.className = isTop ? "crit crit-hit" : "crit crit-fail";
  document.getElementById("crit-text").textContent = isTop ? "DC 20: Beherrscht!" : "DC 1: Immun!";
  crit.hidden = false;
  clearTimeout(critTimer);
  critTimer = setTimeout(() => { crit.hidden = true; }, 1600);
}

if (form.dataset.hasSaved !== "1") restoreDraft();
die.syncFromInput();
updateCount();

form.addEventListener("input", () => {
  saveDraft();
  updateCount();
});
// The die reports "change" once it has settled, so spinning past 20 doesn't count.
dcInput.addEventListener("change", () => {
  if (dcInput.value === "20") showCrit(true);
  if (dcInput.value === "1") showCrit(false);
});
form.addEventListener("submit", clearDraft);
