"use strict";

// A real 3D d20 drawn as SVG. Whatever face points at the viewer is the value.
// Consecutive numbers sit on neighbouring faces (like a spindown die), so a small
// turn in the right direction always reaches the next number.
const die = (() => {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const RADIUS = 92;
  const SETTLE_MS = 260;
  const TAP_PIXELS = 4;
  const COLOR_FRONT = "#e8751a";
  const COLOR_UNSET = "#7a5a48";
  const COLOR_TEXT_FRONT = "#1c0d04";
  const COLOR_TEXT = "#efe4d2";
  const FACE_LIGHT = [74, 51, 42];
  const FACE_DARK = [26, 18, 16];
  const START_VALUE = 10;

  const body = document.getElementById("die-body");
  const input = document.getElementById("die-value");
  const title = document.getElementById("die-title");
  const line = document.getElementById("die-line");
  const tiers = JSON.parse(document.getElementById("die").dataset.tiers);
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // --- Vector and quaternion helpers ---------------------------------------

  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
  const normalize = (a) => scale(a, 1 / Math.hypot(...a));

  // Quaternions are [w, x, y, z].
  function multiply(a, b) {
    return [
      a[0] * b[0] - a[1] * b[1] - a[2] * b[2] - a[3] * b[3],
      a[0] * b[1] + a[1] * b[0] + a[2] * b[3] - a[3] * b[2],
      a[0] * b[2] - a[1] * b[3] + a[2] * b[0] + a[3] * b[1],
      a[0] * b[3] + a[1] * b[2] - a[2] * b[1] + a[3] * b[0],
    ];
  }

  function fromAxisAngle(axis, angle) {
    const s = Math.sin(angle / 2);
    return [Math.cos(angle / 2), axis[0] * s, axis[1] * s, axis[2] * s];
  }

  function rotate(q, v) {
    const u = [q[1], q[2], q[3]];
    const t = scale(cross(u, v), 2);
    const c = cross(u, t);
    return [v[0] + q[0] * t[0] + c[0], v[1] + q[0] * t[1] + c[1], v[2] + q[0] * t[2] + c[2]];
  }

  function slerp(a, b, t) {
    let d = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];
    const target = d < 0 ? b.map((n) => -n) : b;
    d = Math.abs(d);
    if (d > 0.9995) {
      const mixed = a.map((n, i) => n + (target[i] - n) * t);
      const length = Math.hypot(...mixed);
      return mixed.map((n) => n / length);
    }
    const theta = Math.acos(d);
    const wa = Math.sin((1 - t) * theta) / Math.sin(theta);
    const wb = Math.sin(t * theta) / Math.sin(theta);
    return a.map((n, i) => n * wa + target[i] * wb);
  }

  // The rotation that sends the three orthonormal vectors to the x, y and z axes.
  function fromBasis(x, y, z) {
    const trace = x[0] + y[1] + z[2];
    if (trace > 0) {
      const s = Math.sqrt(trace + 1) * 2;
      return [s / 4, (z[1] - y[2]) / s, (x[2] - z[0]) / s, (y[0] - x[1]) / s];
    }
    if (x[0] > y[1] && x[0] > z[2]) {
      const s = Math.sqrt(1 + x[0] - y[1] - z[2]) * 2;
      return [(z[1] - y[2]) / s, s / 4, (x[1] + y[0]) / s, (x[2] + z[0]) / s];
    }
    if (y[1] > z[2]) {
      const s = Math.sqrt(1 + y[1] - x[0] - z[2]) * 2;
      return [(x[2] - z[0]) / s, (x[1] + y[0]) / s, s / 4, (y[2] + z[1]) / s];
    }
    const s = Math.sqrt(1 + z[2] - x[0] - y[1]) * 2;
    return [(y[0] - x[1]) / s, (x[2] + z[0]) / s, (y[2] + z[1]) / s, s / 4];
  }

  // --- Geometry ------------------------------------------------------------

  const PHI = (1 + Math.sqrt(5)) / 2;
  const vertices = [
    [-1, PHI, 0], [1, PHI, 0], [-1, -PHI, 0], [1, -PHI, 0],
    [0, -1, PHI], [0, 1, PHI], [0, -1, -PHI], [0, 1, -PHI],
    [PHI, 0, -1], [PHI, 0, 1], [-PHI, 0, -1], [-PHI, 0, 1],
  ].map(normalize);

  function buildFaces() {
    const edge = 2 / Math.sqrt(1 + PHI * PHI);
    const touching = (a, b) => Math.abs(Math.hypot(...sub(vertices[a], vertices[b])) - edge) < 1e-6;
    const faces = [];
    for (let a = 0; a < 12; a += 1) {
      for (let b = a + 1; b < 12; b += 1) {
        for (let c = b + 1; c < 12; c += 1) {
          if (touching(a, b) && touching(b, c) && touching(a, c)) faces.push({ corners: [a, b, c] });
        }
      }
    }
    for (const face of faces) {
      const [a, b, c] = face.corners.map((i) => vertices[i]);
      face.center = scale([a[0] + b[0] + c[0], a[1] + b[1] + c[1], a[2] + b[2] + c[2]], 1 / 3);
      face.normal = normalize(face.center);
      face.up = normalize(sub(a, face.center));
      face.right = cross(face.up, face.normal);
      face.home = fromBasis(face.right, face.up, face.normal);
    }
    return faces;
  }

  // Walks across neighbouring faces so that 1 to 20 form one unbroken path.
  function numberFaces(faces) {
    const neighbours = faces.map((face) => faces
      .map((other, index) => ({ other, index }))
      .filter(({ other }) => other !== face
        && other.corners.filter((corner) => face.corners.includes(corner)).length === 2)
      .map(({ index }) => index));
    const path = [0];
    const walk = () => {
      if (path.length === faces.length) return true;
      for (const next of neighbours[path[path.length - 1]]) {
        if (!path.includes(next)) {
          path.push(next);
          if (walk()) return true;
          path.pop();
        }
      }
      return false;
    };
    walk();
    path.forEach((faceIndex, position) => { faces[faceIndex].value = position + 1; });
  }

  const faces = buildFaces();
  numberFaces(faces);
  const faceFor = (value) => faces.find((face) => face.value === value);

  // --- Drawing -------------------------------------------------------------

  for (const face of faces) {
    face.polygon = document.createElementNS(SVG_NS, "polygon");
    face.polygon.setAttribute("stroke", "#140d0b");
    face.polygon.setAttribute("stroke-width", "1.5");
    face.polygon.setAttribute("stroke-linejoin", "round");
    face.label = document.createElementNS(SVG_NS, "text");
    // 6 and 9 look alike on a turning die, so they get a dot like on real dice.
    face.label.textContent = face.value === 6 || face.value === 9 ? `${face.value}.` : String(face.value);
    body.append(face.polygon, face.label);
  }

  let orientation = faceFor(START_VALUE).home;
  let animation = null;

  function frontFace() {
    let best = faces[0];
    let bestZ = -Infinity;
    for (const face of faces) {
      const z = rotate(orientation, face.normal)[2];
      if (z > bestZ) {
        best = face;
        bestZ = z;
      }
    }
    return best;
  }

  function draw() {
    const front = frontFace();
    const chosen = input.value !== "";
    for (const face of faces) {
      const normal = rotate(orientation, face.normal);
      const visible = normal[2] > 0.02;
      face.polygon.setAttribute("visibility", visible ? "visible" : "hidden");
      face.label.setAttribute("visibility", visible ? "visible" : "hidden");
      if (!visible) continue;
      face.polygon.setAttribute("points", face.corners.map((i) => {
        const p = rotate(orientation, vertices[i]);
        return `${(p[0] * RADIUS).toFixed(2)},${(-p[1] * RADIUS).toFixed(2)}`;
      }).join(" "));
      const isFront = face === front;
      const shade = FACE_DARK.map((n, i) => Math.round(n + (FACE_LIGHT[i] - n) * normal[2]));
      face.polygon.setAttribute("fill", isFront ? (chosen ? COLOR_FRONT : COLOR_UNSET) : `rgb(${shade.join(",")})`);
      face.label.setAttribute("fill", isFront && chosen ? COLOR_TEXT_FRONT : COLOR_TEXT);
      face.label.setAttribute("opacity", Math.min(1, normal[2] * 1.6).toFixed(2));
      // Numbers lie flat on their face, which is an affine map in a parallel projection.
      const right = rotate(orientation, face.right);
      const up = rotate(orientation, face.up);
      const center = rotate(orientation, face.center);
      const matrix = [right[0], -right[1], -up[0], up[1], center[0] * RADIUS, -center[1] * RADIUS];
      face.label.setAttribute("transform", `matrix(${matrix.map((n) => n.toFixed(3)).join(" ")})`);
    }
  }

  // --- Value ---------------------------------------------------------------

  function tierFor(value) {
    return tiers.filter((tier) => value >= tier.from).pop();
  }

  function showValue() {
    const value = Number(input.value);
    if (!value) return;
    const tier = tierFor(value);
    title.textContent = `DC ${value}: ${tier.name}`;
    line.textContent = tier.line;
    body.setAttribute("aria-valuenow", String(value));
    body.setAttribute("aria-valuetext", `DC ${value}, ${tier.name}`);
  }

  function setValue(value) {
    if (input.value === String(value)) return;
    input.value = String(value);
    showValue();
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function settleTo(face, reportChange) {
    if (animation) cancelAnimationFrame(animation);
    const from = orientation;
    const started = performance.now();
    const finish = () => {
      animation = null;
      if (reportChange) input.dispatchEvent(new Event("change", { bubbles: true }));
    };
    if (reducedMotion) {
      orientation = face.home;
      draw();
      finish();
      return;
    }
    const step = (now) => {
      const t = Math.min(1, (now - started) / SETTLE_MS);
      orientation = slerp(from, face.home, 1 - (1 - t) ** 3);
      draw();
      if (t < 1) animation = requestAnimationFrame(step);
      else finish();
    };
    animation = requestAnimationFrame(step);
  }

  function stepBy(delta) {
    const current = Number(input.value) || frontFace().value;
    const next = input.value === "" ? current : Math.max(1, Math.min(20, current + delta));
    const changed = input.value !== String(next);
    setValue(next);
    settleTo(faceFor(next), changed);
    draw();
  }

  // --- Input ---------------------------------------------------------------

  let drag = null;

  body.addEventListener("pointerdown", (event) => {
    if (animation) cancelAnimationFrame(animation);
    animation = null;
    drag = { x: event.clientX, y: event.clientY, moved: 0, before: input.value };
    body.setPointerCapture(event.pointerId);
  });

  body.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    drag.x = event.clientX;
    drag.y = event.clientY;
    drag.moved += Math.abs(dx) + Math.abs(dy);
    if (drag.moved < TAP_PIXELS) return;
    const radius = body.getBoundingClientRect().width / 2;
    const turnY = fromAxisAngle([0, 1, 0], dx / radius);
    const turnX = fromAxisAngle([1, 0, 0], dy / radius);
    orientation = multiply(turnX, multiply(turnY, orientation));
    setValue(frontFace().value);
    draw();
  });

  function endDrag() {
    if (!drag) return;
    const { before } = drag;
    drag = null;
    const face = frontFace();
    setValue(face.value);
    settleTo(face, before !== input.value);
    draw();
  }

  body.addEventListener("pointerup", endDrag);
  body.addEventListener("pointercancel", endDrag);
  document.getElementById("die-down").addEventListener("click", () => stepBy(-1));
  document.getElementById("die-up").addEventListener("click", () => stepBy(1));

  const KEY_STEPS = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 };
  body.addEventListener("keydown", (event) => {
    if (event.key in KEY_STEPS) {
      event.preventDefault();
      stepBy(KEY_STEPS[event.key]);
    } else if (event.key === " " || event.key === "Enter") {
      // Lets keyboard users take the number the die shows, like a tap does.
      event.preventDefault();
      setValue(frontFace().value);
      draw();
    }
  });

  function syncFromInput() {
    const value = Number(input.value);
    if (value >= 1 && value <= 20) {
      orientation = faceFor(value).home;
      showValue();
    }
    draw();
  }

  return { syncFromInput };
})();
