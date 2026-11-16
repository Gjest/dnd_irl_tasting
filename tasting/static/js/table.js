"use strict";

// Admin editor for the table picture: pick a tasting, tap its dish in the
// picture, adjust the size. The form then saves x and y in percent of the
// picture and r in percent of its width.
const editor = document.getElementById("spot-editor");
if (editor) {
  const aspect = Number(editor.dataset.aspect);
  const picture = editor.querySelector(".m-table-edit");
  const image = picture.querySelector("img");

  const field = (slug, key) => editor.elements.namedItem(`spot_${slug}_${key}`);
  const preview = (slug) => editor.querySelector(`.m-spot-preview[data-slug="${slug}"]`);
  const active = () => editor.querySelector('input[name="active"]:checked').value;

  function draw(slug) {
    const group = preview(slug);
    const x = field(slug, "x").value;
    if (x === "") {
      group.setAttribute("visibility", "hidden");
      return;
    }
    const y = Number(field(slug, "y").value) * aspect;
    const r = field(slug, "r").value;
    const circle = group.querySelector("circle");
    const text = group.querySelector("text");
    circle.setAttribute("cx", x);
    circle.setAttribute("cy", y);
    circle.setAttribute("r", r);
    text.setAttribute("x", x);
    text.setAttribute("y", y);
    group.setAttribute("visibility", "visible");
  }

  function highlight() {
    editor.querySelectorAll(".m-spot-preview").forEach((group) => {
      group.classList.toggle("is-active", group.dataset.slug === active());
    });
  }

  picture.addEventListener("click", (event) => {
    // Measured on the picture itself, so the frame around it doesn't shift the spot.
    const box = image.getBoundingClientRect();
    if (!box.width || !box.height) return; // not laid out yet
    const slug = active();
    const x = ((event.clientX - box.left) / box.width) * 100;
    const y = ((event.clientY - box.top) / box.height) * 100;
    field(slug, "x").value = Math.min(100, Math.max(0, x)).toFixed(2);
    field(slug, "y").value = Math.min(100, Math.max(0, y)).toFixed(2);
    draw(slug);
  });

  editor.addEventListener("input", (event) => {
    if (event.target.type === "range") draw(event.target.name.split("_")[1]);
    if (event.target.name === "active") highlight();
  });

  editor.querySelectorAll("[data-clear]").forEach((button) => {
    button.addEventListener("click", () => {
      field(button.dataset.clear, "x").value = "";
      field(button.dataset.clear, "y").value = "";
      draw(button.dataset.clear);
    });
  });

  highlight();
}
