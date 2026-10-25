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
