// Interactive map of Euskal Herria: territories and municipalities rendered from
// a single PMTiles file (site/data/euskal_herria.pmtiles, built by
// scripts/11_pmtiles.py) served straight off GitHub Pages — no tile server.
// MapLibre GL JS and the pmtiles adapter are vendored in vendor/.
// "Gaia" (theme) buttons recolour the municipality fills into the printed
// chapter maps' choropleths (same classes, same ramps); the figures ride
// along in the tiles, so switching is instant and adds no requests.
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

  // Ramps from site/palette.json (validated with the dataviz checks).
  const R = {
    people: ["#D69476", "#C26C4C", "#A44C32", "#7D3324", "#521D16"],
    forest: ["#90B26E", "#6A9858", "#4A7C48", "#316139", "#1B4429"],
    heat: ["#EE8B68", "#E25E44", "#CA322B", "#A31C22", "#75151E"],
    earth: ["#BCA273", "#A08455", "#82663F", "#624A2C", "#43311D"],
  };

  // "Gaia" themes: choropleths over the municipality fills, using the same
  // classes and ramps as the printed chapter maps (07_site_maps.py).
  const THEMES = {
    lurraldeak: { label: "Lurraldeak" },
    erliebea: {
      label: "Erliebea", prop: "elev_mean", continuous: true,
      stops: [0, 150, 300, 500, 750, 1050, 1350],
      colors: ["land", "#E3D5B3", ...R.earth],   // hypsometric, like the printed map
      legendTitle: "Batez besteko garaiera", ends: ["0 m", "1.400 m"],
      row: "Altitudea", value: (v) => `${fmt.format(Math.round(v))} m`,
    },
    basoa: {
      label: "Basoa", prop: "forest_pct", colors: R.forest,
      edges: [10, 30, 50, 70, 90],                 // printed Basoa classes
      legendTitle: "Zuhaitz-estaldura (udalerria)",
      legend: [[-1, "%10 baino gutxiago"], [0, "%10–30"], [1, "%30–50"],
               [2, "%50–70"], [3, "%70–90"], [4, "%90–100"]],
      row: "Basoa", value: (v) => `${Math.round(v)} %`,
    },
    jendea: {
      label: "Jendea", prop: "density_km2", colors: R.people,
      edges: [25, 100, 500, 2500, 10000],          // printed Jendea bins
      legendTitle: "Biztanleria-dentsitatea",
      legend: [[-1, "25 baino gutxiago"], [0, "25–100"], [1, "100–500"],
               [2, "500–2.500"], [3, "2.500–10.000"], [4, "10.000 baino gehiago"]],
      row: null,   // Dentsitatea is already in the municipality card
    },
    beroa: {
      label: "Beroa", prop: "temperature_change_c", colors: R.heat,
      edges: [0.7, 0.8, 0.9, 1.0],                 // printed Klima classes
      base: "first",                               // every place warmed ≥ +0.6 °C
      legendTitle: "Tenperaturaren igoera, 1961–1990etik 1991–2020ra",
      legend: [[0, "+0,6–0,7 °C"], [1, "+0,7–0,8 °C"], [2, "+0,8–0,9 °C"],
               [3, "+0,9–1,0 °C"], [4, "+1,0 °C baino gehiago"]],
      row: "Beroa", value: (v) => `${v >= 0 ? "+" : ""}${fmt.format(Math.round(v * 10) / 10)} °C`,
    },
  };

  const gaiaPaint = (t, c) => {
    // In dark mode the paper-toned base would sink into the background, so
    // below-threshold areas get a slightly lifted tone instead.
    const below = dark.matches ? "#3F3A31" : c.land;
    const col = (k) => (k === "land" ? below : k);
    return t.continuous
      ? ["interpolate", ["linear"], ["get", t.prop],
         ...t.stops.flatMap((s, i) => [s, col(t.colors[i])])]
      : ["step", ["get", t.prop],
         t.base === "first" ? t.colors[0] : below,
         ...t.edges.flatMap((e, i) => [e, t.colors[t.base === "first" ? i + 1 : i]])];
  };

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

  // Deep-linking: #gaia/zoom/lat/lon (the gaia segment is omitted for the
  // default theme), kept in sync as the map moves or the theme changes.
  const deep = location.hash.match(/^#(?:([a-z]+)\/)?(\d+\.?\d*)\/(-?\d+\.?\d*)\/(-?\d+\.?\d*)$/);
  let gaia = deep && THEMES[deep[1]] ? deep[1] : "lurraldeak";
  const map = new maplibregl.Map({
    container: "map",
    style: style(colors()),
    maxZoom: 14,
    maxBounds: [[-4.6, 41.2], [0.6, 44.3]],
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
  if (deep) map.jumpTo({ center: [parseFloat(deep[4]), parseFloat(deep[3])], zoom: parseFloat(deep[2]) });
  else map.fitBounds(EH, { padding: 24, duration: 0 });

  const syncHash = () => {
    const c = map.getCenter(), z = map.getZoom();
    const g = gaia === "lurraldeak" ? "" : `${gaia}/`;
    history.replaceState(null, "", `#${g}${z.toFixed(1)}/${c.lat.toFixed(3)}/${c.lng.toFixed(3)}`);
  };
  map.on("moveend", syncHash);

  // Theme switching: recolour the municipality fills (the figures ride in
  // the tiles), show the legend, and widen the fills' zoom range so the
  // choropleth is visible from z7 — one zoom short of the hairline borders.
  const legend = document.getElementById("map-legend");
  const themeButtons = [...document.querySelectorAll("[data-gaia]")];
  const sw = (color, label) =>
    `<li><span class="sw" style="background:${color}"></span>${esc(label)}</li>`;
  const renderLegend = (t) => {
    const c = colors();
    const base = dark.matches ? "#3F3A31" : c.land;   // match the map's below-tone
    legend.innerHTML = t.continuous
      ? `<p class="title">${esc(t.legendTitle)}</p>
         <div class="ramp" style="background:linear-gradient(90deg, ${t.colors.map((k) => k === "land" ? base : k).join(", ")})"></div>
         <div class="ramp-labels"><span>${esc(t.ends[0])}</span><span>${esc(t.ends[1])}</span></div>`
      : `<p class="title">${esc(t.legendTitle)}</p>
         <ul class="legend">${t.legend.map(([i, label]) => sw(i < 0 ? base : t.colors[i], label)).join("")}</ul>`;
    legend.hidden = false;
  };
  let styleReady = false;
  const applyGaia = (id, sync = true) => {
    gaia = THEMES[id] ? id : "lurraldeak";
    const t = THEMES[gaia], c = colors();
    for (const b of themeButtons) b.setAttribute("aria-pressed", String(b.dataset.gaia === gaia));
    if (t.prop) {
      renderLegend(t);
      if (styleReady) {
        map.setPaintProperty("municipalities", "fill-color", gaiaPaint(t, c));
        map.setLayerZoomRange("municipalities", 7, 24);
      }
    } else {
      legend.hidden = true;
      if (styleReady) {
        map.setPaintProperty("municipalities", "fill-color", c.land);
        map.setLayerZoomRange("municipalities", 8, 24);
      }
    }
    if (sync) syncHash();
  };
  for (const b of themeButtons) b.addEventListener("click", () => applyGaia(b.dataset.gaia));
  map.on("load", () => { styleReady = true; applyGaia(gaia, false); });
  applyGaia(gaia, false);   // set button/legend state while the style loads

  // Re-colour when the colour scheme changes.
  dark.addEventListener("change", () => {
    const c = colors();
    const set = (layer, prop, v) => map.setPaintProperty(layer, prop, v);
    set("sea", "background-color", c.sea);
    set("land", "fill-color", c.land);
    set("territories", "fill-color", c.land);
    applyGaia(gaia, false);   // re-apply the theme fill (ramps stay, base follows the scheme)
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
      const t = THEMES[gaia];
      if (t?.row && p[t.prop] != null) pairs.push([t.row, t.value(p[t.prop])]);
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
