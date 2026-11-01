"use strict";

const showToggle = document.getElementById("show-passphrase");
if (showToggle) {
  showToggle.addEventListener("change", () => {
    document.getElementById("passphrase").type = showToggle.checked ? "text" : "password";
  });
}
