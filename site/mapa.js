// Interactive map of Euskal Herria: territories and municipalities rendered from
// a single PMTiles file (site/data/euskal_herria.pmtiles, built by
// scripts/11_pmtiles.py) served straight off GitHub Pages — no tile server.
// MapLibre GL JS and the pmtiles adapter are vendored in vendor/.
(() => {
  const status = document.getElementById("status");
  const say = (msg, err = false) => {
    status.textContent = msg;
    status.classList.toggle("err", err);
  };
  const cssVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = new Intl.NumberFormat("eu-ES");
  const dark = matchMedia("(prefers-color-scheme: dark)");

  // Map colours, echoing the printed territory map: warm paper land on a pale
  // grey-blue sea, charcoal territory borders, hairline municipal borders.
  const colors = () => ({
    sea: dark.matches ? "#22272A" : "#DCE3E1",
    land: cssVar("--paper"),
    ink: cssVar("--ink"),
    ink2: cssVar("--ink-2"),
    muni: dark.matches ? "#4A463D" : "#A69F94",
    halo: cssVar("--paper"),
    accent: cssVar("--accent"),
  });

  const EH = [[-3.4503, 41.9099], [-0.6526, 43.5473]];

  const style = (c) => ({
    version: 8,
    glyphs: "fonts/glyphs/{fontstack}/{range}.pbf",
    sources: {
      ehmap: {
        type: "vector",
        url: "pmtiles://data/euskal_herria.pmtiles",
        attribution: '<a href="https://itzune.eus/ehmap/">ehmap</a> · CC BY 4.0',
      },
    },
    layers: [
      { id: "sea", type: "background", paint: { "background-color": c.sea } },
      { id: "land", type: "fill", source: "ehmap", "source-layer": "euskal_herria",
        paint: { "fill-color": c.land } },
      { id: "territories", type: "fill", source: "ehmap", "source-layer": "territories",
        paint: { "fill-color": c.land } },
      { id: "municipalities", type: "fill", source: "ehmap", "source-layer": "municipalities",
        minzoom: 8, paint: { "fill-color": c.land } },
      { id: "territory-lines", type: "line", source: "ehmap", "source-layer": "territory-borders",
        paint: { "line-color": c.ink, "line-opacity": 0.75,
                 "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.8, 8, 1.6, 13, 1.2] } },
      { id: "municipality-lines", type: "line", source: "ehmap", "source-layer": "municipality-borders",
        minzoom: 7,
        paint: { "line-color": c.muni,
                 "line-width": ["interpolate", ["linear"], ["zoom"], 7, 0.35, 8, 0.55, 13, 1.05] } },
      { id: "hover", type: "fill", source: "ehmap", "source-layer": "municipalities",
        minzoom: 8, filter: ["==", ["get", "code"], ""],
        paint: { "fill-color": c.accent, "fill-opacity": 0.16 } },
      { id: "outline", type: "line", source: "ehmap", "source-layer": "eh-outline",
        paint: { "line-color": c.ink,
                 "line-width": ["interpolate", ["linear"], ["zoom"], 4, 1.2, 10, 2, 13, 2.4] } },
      { id: "territory-labels", type: "symbol", source: "ehmap", "source-layer": "territories",
        minzoom: 5.2, filter: ["==", ["geometry-type"], "Point"],
        layout: { "text-field": ["coalesce", ["get", "name_eu"], ["get", "name"]],
                  "text-font": ["OpenSansBold"], "text-transform": "uppercase",
                  "text-letter-spacing": 0.12, "text-max-width": 7,
                  "text-size": ["interpolate", ["linear"], ["zoom"], 5.2, 12, 8, 15.5] },
        paint: { "text-color": c.ink, "text-halo-color": c.halo, "text-halo-width": 1.4 } },
      { id: "city-labels", type: "symbol", source: "ehmap", "source-layer": "municipalities",
        minzoom: 9.2, filter: ["all", ["==", ["geometry-type"], "Point"],
                              [">=", ["coalesce", ["get", "population"], 0], 40000]],
        layout: { "text-field": ["coalesce", ["get", "name_eu"], ["get", "name"]],
                  "text-font": ["OpenSansBold"], "text-max-width": 7,
                  "symbol-sort-key": ["coalesce", ["get", "population"], 0],
                  "text-size": ["interpolate", ["linear"], ["zoom"], 9.2, 11.5, 13, 13.5] },
        paint: { "text-color": c.ink, "text-halo-color": c.halo, "text-halo-width": 1.4 } },
      { id: "municipality-labels", type: "symbol", source: "ehmap", "source-layer": "municipalities",
        minzoom: 10.6, filter: ["all", ["==", ["geometry-type"], "Point"],
                               ["<", ["coalesce", ["get", "population"], 0], 40000]],
        layout: { "text-field": ["coalesce", ["get", "name_eu"], ["get", "name"]],
                  "text-font": ["OpenSansRegular"], "text-max-width": 7,
                  "symbol-sort-key": ["coalesce", ["get", "population"], 0],
                  "text-size": ["interpolate", ["linear"], ["zoom"], 10.6, 10.5, 13, 12] },
        paint: { "text-color": c.ink2, "text-halo-color": c.halo, "text-halo-width": 1.3 } },
    ],
  });

  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);

  // Deep-linking: #zoom/lat/lon, kept in sync as the map moves.
  const deep = location.hash.match(/^#(\d+\.?\d*)\/(-?\d+\.?\d*)\/(-?\d+\.?\d*)$/);
  const map = new maplibregl.Map({
    container: "map",
    style: style(colors()),
    maxZoom: 14,
    maxBounds: [[-4.6, 41.2], [0.6, 44.3]],
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
  if (deep) map.jumpTo({ center: [parseFloat(deep[3]), parseFloat(deep[2])], zoom: parseFloat(deep[1]) });
  else map.fitBounds(EH, { padding: 24, duration: 0 });
  map.on("moveend", () => {
    const c = map.getCenter(), z = map.getZoom();
    history.replaceState(null, "", `#${z.toFixed(1)}/${c.lat.toFixed(3)}/${c.lng.toFixed(3)}`);
  });

  // Re-colour when the colour scheme changes.
  dark.addEventListener("change", () => {
    const c = colors();
    const set = (layer, prop, v) => map.setPaintProperty(layer, prop, v);
    set("sea", "background-color", c.sea);
    set("land", "fill-color", c.land);
    set("territories", "fill-color", c.land);
    set("municipalities", "fill-color", c.land);
    set("hover", "fill-color", c.accent);
    set("territory-lines", "line-color", c.ink);
    set("municipality-lines", "line-color", c.muni);
    set("outline", "line-color", c.ink);
    for (const l of ["territory-labels", "city-labels"]) {
      set(l, "text-color", c.ink); set(l, "text-halo-color", c.halo);
    }
    set("municipality-labels", "text-color", c.ink2);
    set("municipality-labels", "text-halo-color", c.halo);
  });

  // Hover: highlight the municipality under the pointer.
  const hoverLayer = "hover";
  let hoverCode = null;
  const clearHover = () => {
    if (!hoverCode) return;
    hoverCode = null;
    map.getCanvas().style.cursor = "";
    map.setFilter(hoverLayer, ["==", ["get", "code"], ""]);
  };
  map.on("mousemove", (e) => {
    if (map.getZoom() < 7.9) return clearHover();
    const fs = map.queryRenderedFeatures(e.point, { layers: ["municipalities"] });
    const code = fs.length ? fs[0].properties.code : null;
    if (code === hoverCode) return;
    hoverCode = code;
    if (code) {
      map.getCanvas().style.cursor = "pointer";
      map.setFilter(hoverLayer, ["==", ["get", "code"], code]);
    } else clearHover();
  });
  map.on("mouseout", clearHover);

  // Click: a small card with the municipality's (or territory's) figures.
  const popup = new maplibregl.Popup({ maxWidth: "none", closeOnClick: false });
  const rows = (pairs) => `<dl>${pairs.map(([k, v]) =>
    `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`;
  map.on("click", (e) => {
    const muni = map.queryRenderedFeatures(e.point, { layers: ["municipalities"] });
    if (muni.length) {
      const p = muni[0].properties;
      const eu = p.name_eu || p.name;
      const pairs = [["Lurraldea", p.territory], ["Kodea", `${p.code} (${p.country})`]];
      if (p.population != null) pairs.push(["Biztanleria", fmt.format(p.population)]);
      if (p.density_km2 != null)
        pairs.push(["Dentsitatea", `${fmt.format(Math.round(p.density_km2))} bizt/km²`]);
      popup.setLngLat(e.lngLat).setHTML(
        `<h3>${esc(eu)}</h3>` +
        (p.name && p.name !== eu ? `<p class="official">ofizialki: ${esc(p.name)}</p>` : "") +
        (p.type === "shared_land" ? `<p class="official">lur partzuergoa</p>` : "") +
        rows(pairs)).addTo(map);
      return;
    }
    const terr = map.queryRenderedFeatures(e.point, { layers: ["territories"] });
    if (terr.length) {
      const p = terr[0].properties;
      const pairs = [];
      if (p.population != null) pairs.push(["Biztanleria", fmt.format(p.population)]);
      if (p.area_km2 != null) pairs.push(["Azalera", `${fmt.format(Math.round(p.area_km2))} km²`]);
      if (p.density_km2 != null)
        pairs.push(["Dentsitatea", `${fmt.format(Math.round(p.density_km2))} bizt/km²`]);
      popup.setLngLat(e.lngLat).setHTML(
        `<h3>${esc(p.name_eu || p.name)}</h3>` + rows(pairs)).addTo(map);
    } else {
      popup.remove();   // clicking bare land or sea dismisses the card
    }
  });

  map.on("error", (e) => {
    say("Errorea mapak kargatzean" + (e?.error?.message ? `: ${e.error.message}` : ""), true);
  });
  map.once("idle", () => {
    say("Kargatuta ✓");
    status.classList.add("ok");
    setTimeout(() => status.classList.add("fade"), 3000);
  });
  window.addEventListener("error", (e) =>
    say("Errorea: " + (e.message || "mapa ezin izan da kargatu"), true));

  // On small screens the info card starts collapsed.
  if (matchMedia("(max-width: 40rem)").matches)
    document.querySelector(".map-card")?.removeAttribute("open");

  // Handy for debugging and for power users poking at the console.
  window.ehmap = map;
})();
