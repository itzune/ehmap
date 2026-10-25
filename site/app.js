// Full-screen map viewer: wheel / pinch zoom around the pointer, drag to pan,
// keyboard + − 0 and Esc. No dependencies.
(() => {
  const dialog = document.getElementById("viewer");
  if (!dialog) return;
  const stage = dialog.querySelector(".stage");
  const img = stage.querySelector("img");
  const caption = dialog.querySelector(".caption");
  let scale = 1, x = 0, y = 0, minScale = 0.1;
  const pointers = new Map();
  let lastPinch = 0;

  const apply = () => { img.style.transform = `translate(${x}px, ${y}px) scale(${scale})`; };

  const fit = () => {
    const w = stage.clientWidth, h = stage.clientHeight;
    scale = minScale = Math.min(w / img.naturalWidth, h / img.naturalHeight);
    x = (w - img.naturalWidth * scale) / 2;
    y = (h - img.naturalHeight * scale) / 2;
    apply();
  };

  const zoomAt = (factor, cx, cy) => {
    const next = Math.min(Math.max(scale * factor, minScale), 2.5);
    const k = next / scale;
    x = cx - (cx - x) * k;
    y = cy - (cy - y) * k;
    scale = next;
    apply();
  };

  const centre = () => [stage.clientWidth / 2, stage.clientHeight / 2];

  document.querySelectorAll(".map button[data-full]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const thumb = btn.querySelector("img");
      img.alt = thumb.alt;
      caption.textContent = btn.closest("figure").querySelector("figcaption")?.textContent ?? "";
      img.onload = fit;
      img.src = btn.dataset.full;
      dialog.showModal();
      if (img.complete && img.naturalWidth) fit();
    });
  });

  dialog.addEventListener("click", (e) => {
    const z = e.target.closest("[data-zoom]");
    if (z) {
      const [cx, cy] = centre();
      if (z.dataset.zoom === "in") zoomAt(1.5, cx, cy);
      if (z.dataset.zoom === "out") zoomAt(1 / 1.5, cx, cy);
      if (z.dataset.zoom === "fit") fit();
    }
    if (e.target.closest("[data-close]")) dialog.close();
  });

  dialog.addEventListener("keydown", (e) => {
    const [cx, cy] = centre();
    if (e.key === "+" || e.key === "=") zoomAt(1.5, cx, cy);
    else if (e.key === "-") zoomAt(1 / 1.5, cx, cy);
    else if (e.key === "0") fit();
  });

  stage.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = stage.getBoundingClientRect();
    zoomAt(Math.exp(-e.deltaY * 0.0015), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });

  stage.addEventListener("pointerdown", (e) => {
    stage.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    stage.classList.add("dragging");
  });
  stage.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    const [px, py] = pointers.get(e.pointerId);
    pointers.set(e.pointerId, [e.clientX, e.clientY]);
    if (pointers.size === 1) {
      x += e.clientX - px;
      y += e.clientY - py;
      apply();
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      const r = stage.getBoundingClientRect();
      if (lastPinch) zoomAt(d / lastPinch, (a[0] + b[0]) / 2 - r.left, (a[1] + b[1]) / 2 - r.top);
      lastPinch = d;
    }
  });
  const release = (e) => {
    pointers.delete(e.pointerId);
    if (pointers.size < 2) lastPinch = 0;
    if (!pointers.size) stage.classList.remove("dragging");
  };
  stage.addEventListener("pointerup", release);
  stage.addEventListener("pointercancel", release);
  window.addEventListener("resize", () => { if (dialog.open) fit(); });
})();

// Warming stripes: one SVG row per area, built from site/data/stripes.json, with a shared
// year cursor and a tooltip. Colours: cold arm, neutral, warm arm in 0.5 °C classes.
(() => {
  const chart = document.querySelector(".stripes-chart");
  if (!chart) return;
  const tip = document.getElementById("tip");
  const COLD = ["#2F5996", "#4475B2", "#6491C3", "#88ADD4"];
  const WARM = ["#EE8B68", "#E25E44", "#CA322B", "#A31C22"];
  const NEUTRAL = "#D8D2C6";
  const colour = (v) => {
    if (v == null || Number.isNaN(v)) return "transparent";
    const k = Math.min(Math.round(Math.abs(v) / 0.5), 4);   // ±0.25 → 0, ±0.75 → 1, …
    if (k === 0) return NEUTRAL;
    return v > 0 ? WARM[k - 1] : COLD[4 - k];
  };
  const fmt = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(1).replace(".", ",") + " °C";
  const NS = "http://www.w3.org/2000/svg";

  fetch(chart.dataset.src).then((r) => r.json()).then((data) => {
    const n = data.years.length;
    const svgs = [];
    data.rows.forEach((row, i) => {
      const label = document.createElement("span");
      label.className = "lbl" + (i === 0 ? " main" : "");
      label.textContent = row.name;
      const svg = document.createElementNS(NS, "svg");
      svg.setAttribute("viewBox", `0 0 ${n} 1`);
      svg.setAttribute("preserveAspectRatio", "none");
      svg.setAttribute("shape-rendering", "crispEdges");
      svg.setAttribute("aria-hidden", "true");
      if (i === 0) svg.classList.add("main");
      row.anomaly.forEach((v, j) => {
        const r = document.createElementNS(NS, "rect");
        r.setAttribute("x", j); r.setAttribute("width", 1.02); r.setAttribute("height", 1);
        r.setAttribute("fill", colour(v));
        svg.append(r);
      });
      svg.dataset.row = i;
      svgs.push(svg);
      chart.append(label, svg);
    });

    const axis = document.createElement("div");
    axis.className = "axis";
    const at = (y) => `${((y - data.years[0] + 0.5) / n) * 100}%`;
    for (const y of [1950, 1975, 2000, 2025]) {
      const s = document.createElement("span");
      s.style.left = at(y); s.textContent = y;
      axis.append(s);
    }
    const ref = document.createElement("span");
    ref.className = "ref";
    ref.style.left = `${((1961 - data.years[0]) / n) * 100}%`;
    ref.style.width = `${(30 / n) * 100}%`;
    ref.textContent = "erreferentzia: 1961–1990";
    axis.append(ref);
    chart.append(document.createElement("span"), axis);

    const cursor = document.createElement("div");
    cursor.className = "cursor";
    chart.append(cursor);

    const hide = () => { tip.hidden = true; cursor.style.opacity = 0; };
    chart.addEventListener("pointerleave", hide);
    chart.addEventListener("pointermove", (e) => {
      const svg = e.target.closest("svg");
      if (!svg) { hide(); return; }
      const box = svg.getBoundingClientRect();
      const j = Math.min(n - 1, Math.max(0, Math.floor(((e.clientX - box.left) / box.width) * n)));
      const row = data.rows[svg.dataset.row];
      const v = row.anomaly[j];
      const cbox = chart.getBoundingClientRect();
      const first = svgs[0].getBoundingClientRect(), last = svgs[svgs.length - 1].getBoundingClientRect();
      cursor.style.left = `${box.left - cbox.left + ((j + 0.5) / n) * box.width}px`;
      cursor.style.top = `${first.top - cbox.top}px`;
      cursor.style.height = `${last.bottom - first.top}px`;
      cursor.style.opacity = "";
      tip.innerHTML = `<b>${data.years[j]}</b> · ${row.name}<br><span>${fmt(v)} 1961–1990ekin alderatuta</span>`;
      tip.hidden = false;
      const x = Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
      tip.style.left = `${x}px`;
      tip.style.top = `${e.clientY - tip.offsetHeight - 12}px`;
    });
  });
})();

// Marine heatwave days per year: one bar per year, a tooltip on hover.
(() => {
  const chart = document.querySelector(".sea-chart");
  if (!chart) return;
  const tip = document.getElementById("tip");
  const NS = "http://www.w3.org/2000/svg";
  const el = (name, attrs, parent) => {
    const e = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    parent?.append(e);
    return e;
  };
  fetch(chart.dataset.src).then((r) => r.json()).then((d) => {
    const draw = () => {
      chart.replaceChildren();
      const W = chart.clientWidth, H = W < 520 ? 220 : 280, L = 34, T = 8, B = 24, top = 300;
      const n = d.years.length, bw = (W - L) / n;
      const y = (v) => T + (1 - v / top) * (H - T - B);
      const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, height: H, "aria-hidden": "true" }, chart);
      for (const t of [0, 100, 200, 300]) {
        el("line", { class: "grid", x1: L, x2: W, y1: y(t), y2: y(t) }, svg);
        el("text", { class: "tick", x: L - 6, y: y(t) + 4, "text-anchor": "end" }, svg).textContent = t;
      }
      d.years.forEach((yr, i) => {
        const v = d.heatwave_days[i];
        const r = el("rect", { x: L + i * bw + 1, y: y(v), width: Math.max(bw - 2, 1), height: y(0) - y(v), rx: 1.5 }, svg);
        r.dataset.text = `<b>${yr}</b><br><span>${v} egun bero-boladan</span>`;
        if (yr % 10 === 0 || i === 0 || i === n - 1) {
          el("text", { class: "tick", x: L + (i + 0.5) * bw, y: H - 6, "text-anchor": "middle" }, svg).textContent = yr;
        }
      });
      svg.addEventListener("pointermove", (e) => {
        const r = e.target.closest("rect");
        if (!r) { tip.hidden = true; return; }
        tip.innerHTML = r.dataset.text;
        tip.hidden = false;
        tip.style.left = `${Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8)}px`;
        tip.style.top = `${e.clientY - tip.offsetHeight - 12}px`;
      });
      svg.addEventListener("pointerleave", () => { tip.hidden = true; });
    };
    draw();
    let t;
    window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(draw, 150); });
  });
})();
