"use strict";

// Start page: switch between the table picture and the tiles without a
// reload. The form still works without this script; here it only saves.
const viewSwitch = document.getElementById("view-switch");
if (viewSwitch) {
  const buttons = [...viewSwitch.querySelectorAll("button[name=view]")];
  viewSwitch.addEventListener("click", (event) => {
    const button = event.target.closest("button[name=view]");
    if (!button) return;
    event.preventDefault();
    for (const other of buttons) {
      const active = other === button;
      other.setAttribute("aria-pressed", String(active));
      document.getElementById(other.getAttribute("aria-controls")).hidden = !active;
    }
    const body = new FormData();
    body.set("view", button.value);
    // Saving is a nicety: if it fails, the page keeps the view for now.
    fetch(viewSwitch.action, { method: "POST", headers: { "X-CSRF-Token": CSRF_TOKEN }, body }).catch(() => {});
  });
}
