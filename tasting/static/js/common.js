"use strict";

const CSRF_TOKEN = document.querySelector('meta[name="csrf-token"]').content;

// Builds DOM nodes. Text always goes through textContent, so player-written
// names and notes can never turn into markup.
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function fmt(value, digits = 1) {
  if (value === null || value === undefined) return "–";
  return value.toLocaleString("de-DE", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

async function getJson(url) {
  const response = await fetch(url, { headers: { Accept: "application/json" } });
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("not logged in");
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function postJson(url) {
  const response = await fetch(url, { method: "POST", headers: { "X-CSRF-Token": CSRF_TOKEN } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

document.addEventListener("submit", (event) => {
  const question = event.target.dataset && event.target.dataset.confirm;
  if (question && !window.confirm(question)) event.preventDefault();
});
