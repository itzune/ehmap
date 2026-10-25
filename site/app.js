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

// Rain explorer: season tabs, a slider over 10-year windows and a dot per station that has
// data in that window, coloured by its rain as % of its own 1996-2025 mean. Under the slider,
// the median of the stations over time for the chosen season.
(() => {
  const root = document.getElementById("euria-esploratzailea");
  if (!root) return;
  const tip = document.getElementById("tip");
  const tabs = root.querySelector(".tabs"), dots = root.querySelector(".ex-dots");
  const slider = root.querySelector(".ex-slider"), play = root.querySelector(".ex-play");
  const label = root.querySelector(".ex-window"), spark = root.querySelector(".ex-spark");
  const img = root.querySelector(".ex-map img");
  const DRY = ["#CC9967", "#A9733A", "#80521F"], WET = ["#63B5B4", "#2B9191", "#086B6C"], NEUTRAL = "#D8D2C6";
  const colour = (pct) => {
    const d = pct - 100, k = Math.abs(d) < 5 ? 0 : Math.min(Math.floor((Math.abs(d) - 5) / 5) + 1, 3);
    return k === 0 ? NEUTRAL : (d < 0 ? DRY : WET)[k - 1];
  };
  const NS = "http://www.w3.org/2000/svg";
  const el = (name, attrs, parent) => {
    const e = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    parent?.append(e);
    return e;
  };
  let data, season = "year", timer = null;
  const W = 1000, H = Math.round((W * +img.getAttribute("height")) / +img.getAttribute("width"));
  dots.setAttribute("viewBox", `0 0 ${W} ${H}`);

  const median = (xs) => {
    const s = xs.filter((x) => x != null).sort((a, b) => a - b);
    return s.length ? (s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2) : null;
  };

  const drawSpark = () => {
    spark.replaceChildren();
    const w = spark.clientWidth, h = 90, pad = 18;
    const long = data.stations.filter((s) => s.long);
    const meds = data.windows.map((_, i) => {
      const vals = long.map((s) => s.v[season][i]);
      return vals.filter((v) => v != null).length >= 5 ? median(vals) : null;   // a median needs a few stations
    });
    const lo = 70, hi = 140;
    const x = (i) => (i / (data.windows.length - 1)) * w;
    const y = (v) => pad / 2 + (1 - (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * (h - pad);
    el("line", { class: "ref", x1: 0, x2: w, y1: y(100), y2: y(100) }, spark);
    let d = "";
    meds.forEach((m, i) => { if (m != null) d += `${d && meds[i - 1] != null ? "L" : "M"}${x(i)},${y(m)}`; });
    el("path", { class: "line", d }, spark);
    const t1 = el("text", { x: w, y: y(100) + 13, "text-anchor": "end" }, spark);
    t1.textContent = "%100 = 1996–2025";
    const t2 = el("text", { x: 0, y: 10 }, spark);
    t2.textContent = `${long.length} estazio luzeen mediana`;
    for (const yr of [1930, 1960, 1990, 2025]) {
      const i = data.windows.indexOf(yr);
      if (i < 0) continue;
      const t = el("text", { x: x(i), y: h + 4, "text-anchor": yr === 2025 ? "end" : "middle" }, spark);
      t.textContent = yr;
    }
    const i = +slider.value, m = meds[i];
    if (m != null) el("circle", { class: "now", cx: x(i), cy: y(m), r: 5 }, spark);
  };

  const draw = () => {
    const i = +slider.value, end = data.windows[i];
    dots.replaceChildren();
    let n = 0;
    for (const s of data.stations) {
      const v = s.v[season][i];
      if (v == null) continue;
      n++;
      const c = el("circle", { cx: s.fx * W, cy: s.fy * H, r: 9, fill: colour(v), class: s.long ? "long" : "" }, dots);
      c.dataset.text = `<b>${s.name}</b> · ${end - data.window + 1}–${end}<br><span>%${v} (1996–2025 = %100)</span>`;
    }
    label.innerHTML = `${end - data.window + 1}–${end}<small>${n} estazio</small>`;
    drawSpark();
    tabs.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", b.dataset.key === season));
  };

  const stop = () => { clearInterval(timer); timer = null; play.textContent = "▶"; play.setAttribute("aria-label", "Erreproduzitu"); };
  play.addEventListener("click", () => {
    if (timer) return stop();
    if (+slider.value >= +slider.max) slider.value = 0;
    play.textContent = "❚❚"; play.setAttribute("aria-label", "Gelditu");
    timer = setInterval(() => {
      if (+slider.value >= +slider.max) return stop();
      slider.value = +slider.value + 1;
      draw();
    }, 160);
  });
  slider.addEventListener("input", () => { stop(); draw(); });

  dots.addEventListener("pointerover", (e) => {
    const c = e.target.closest("circle");
    if (!c) return;
    tip.innerHTML = c.dataset.text;
    tip.hidden = false;
  });
  dots.addEventListener("pointermove", (e) => {
    if (tip.hidden) return;
    tip.style.left = `${Math.min(e.clientX + 14, window.innerWidth - tip.offsetWidth - 8)}px`;
    tip.style.top = `${e.clientY - tip.offsetHeight - 12}px`;
  });
  dots.addEventListener("pointerout", () => { tip.hidden = true; });

  fetch("data/rain_timeline.json").then((r) => r.json()).then((d) => {
    data = d;
    for (const s of d.seasons) {
      const b = document.createElement("button");
      b.type = "button"; b.role = "tab"; b.dataset.key = s.key; b.textContent = s.name;
      b.addEventListener("click", () => { season = s.key; draw(); });
      tabs.append(b);
    }
    // start at the first window with a handful of stations
    const first = d.windows.findIndex((_, i) => d.stations.filter((s) => s.v.year[i] != null).length >= 3);
    slider.min = Math.max(0, first); slider.max = d.windows.length - 1; slider.step = 1;
    slider.value = slider.max;
    draw();
    window.addEventListener("resize", drawSpark);
  });
})();
