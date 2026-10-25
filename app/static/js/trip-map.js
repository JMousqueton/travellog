import { escapeHtml, modeEntries, modes, t } from "./i18n.js";

const OSM_COPYRIGHT = "https://www.openstreetmap.org/copyright";
const COUNTRIES_PREF = "map:countries";
const PLACES_PREF = "map:places";
const RAD = Math.PI / 180;

/** Points d'un arc de grand cercle (orthodromie), longitudes « dépliées » pour franchir l'antiméridien. */
export function greatCircle([lat1, lon1], [lat2, lon2], segments = 64) {
  const φ1 = lat1 * RAD, λ1 = lon1 * RAD, φ2 = lat2 * RAD, λ2 = lon2 * RAD;
  const d = 2 * Math.asin(Math.sqrt(
    Math.sin((φ2 - φ1) / 2) ** 2 + Math.cos(φ1) * Math.cos(φ2) * Math.sin((λ2 - λ1) / 2) ** 2,
  ));
  if (d < 1e-9 || Math.abs(Math.sin(d)) < 1e-9) return straight([lat1, lon1], [lat2, lon2], segments);
  const points = [];
  let previousLon = null;
  for (let i = 0; i <= segments; i += 1) {
    const f = i / segments;
    const A = Math.sin((1 - f) * d) / Math.sin(d);
    const B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(φ1) * Math.cos(λ1) + B * Math.cos(φ2) * Math.cos(λ2);
    const y = A * Math.cos(φ1) * Math.sin(λ1) + B * Math.cos(φ2) * Math.sin(λ2);
    const z = A * Math.sin(φ1) + B * Math.sin(φ2);
    let lon = Math.atan2(y, x) / RAD;
    if (previousLon !== null) {
      while (lon - previousLon > 180) lon -= 360;
      while (lon - previousLon < -180) lon += 360;
    }
    previousLon = lon;
    points.push([Math.atan2(z, Math.hypot(x, y)) / RAD, lon]);
  }
  return points;
}

function straight([lat1, lon1], [lat2, lon2], segments = 24) {
  return Array.from({ length: segments + 1 }, (_, i) => {
    const f = i / segments;
    return [lat1 + (lat2 - lat1) * f, lon1 + (lon2 - lon1) * f];
  });
}

/** Décale légèrement le trajet retour pour qu'il reste visible à côté de l'aller. */
function bend(points) {
  const [a, b] = [points[0], points[points.length - 1]];
  const dy = b[0] - a[0], dx = b[1] - a[1];
  const length = Math.hypot(dx, dy) || 1;
  const offset = Math.min(length * 0.08, 6);
  const nLat = dx / length, nLon = -dy / length;
  return points.map(([lat, lon], i) => {
    const k = Math.sin((Math.PI * i) / (points.length - 1)) * offset;
    return [lat + nLat * k, lon + nLon * k];
  }).reverse();
}

const modeStyle = (key) => {
  const m = modes[key];
  return `--mode-color:${m.color};--mode-color-dark:${m.colorDark}`;
};

export function tripPopup(trip, leg) {
  const m = modes[trip.transport_mode];
  const isReturn = leg === "return";
  const [from, to] = isReturn ? [trip.destination.name, trip.origin.name] : [trip.origin.name, trip.destination.name];
  return `<div class="trip-popup" style="${modeStyle(trip.transport_mode)}">
    <div class="tp-head">
      <span class="mode-dot" aria-hidden="true"><i class="fa-solid ${m.icon}"></i></span>
      <div><div class="fw-semibold">${escapeHtml(trip.mode_label)}</div>
      <div class="small text-body-secondary">${escapeHtml(isReturn ? t("return_leg") : t("outbound_leg"))}</div></div>
      ${trip.status !== "past" ? `<span class="badge rounded-pill status-badge status-${trip.status} ms-auto">${escapeHtml(trip.countdown)}</span>` : ""}
    </div>
    <div class="tp-route">${escapeHtml(from)} → ${escapeHtml(to)}</div>
    ${trip.journey ? `<div class="small text-body-secondary mb-2"><i class="fa-solid fa-route me-1" aria-hidden="true"></i>${escapeHtml(t("journey_label", { name: trip.journey.name }))}</div>` : ""}
    ${trip.countries?.length ? `<div class="small mb-2">${trip.countries.map((c) => `<span title="${escapeHtml(c.name)}">${c.flag}</span>`).join(" ")}
      <span class="visually-hidden">${escapeHtml(trip.countries.map((c) => c.name).join(", "))}</span></div>` : ""}
    <dl>
      <dt>${escapeHtml(t("departure"))}</dt><dd>${escapeHtml(trip.depart_date_fmt)}</dd>
      ${trip.is_round_trip ? `<dt>${escapeHtml(t("return"))}</dt><dd>${escapeHtml(trip.return_date_fmt)}</dd>` : ""}
      <dt>${escapeHtml(t("distance"))}</dt><dd>${escapeHtml(trip.distance_fmt)}</dd>
    </dl>
    <div class="d-flex align-items-center justify-content-between gap-2">
      <span class="badge rounded-pill text-bg-primary-subtle">${escapeHtml(trip.is_round_trip ? t("round_trip") : t("one_way"))}</span>
      <span class="d-flex gap-3">
      ${trip.detail_url ? `<a href="${escapeHtml(trip.detail_url)}" class="small"><i class="fa-solid fa-circle-info me-1" aria-hidden="true"></i>${escapeHtml(t("details"))}${trip.photo_count ? ` · <i class="fa-regular fa-image" aria-hidden="true"></i> ${trip.photo_count}` : ""}</a>` : ""}
      ${trip.edit_url ? `<a href="${escapeHtml(trip.edit_url)}" class="small"><i class="fa-solid fa-pen me-1" aria-hidden="true"></i>${escapeHtml(t("edit"))}</a>` : ""}
      </span>
    </div>
  </div>`;
}

function placePopup(place) {
  const items = place.trips.map((trip) => `
    <li style="${modeStyle(trip.transport_mode)}"><button type="button" data-trip-id="${trip.id}">
      <i class="fa-solid ${modes[trip.transport_mode].icon}" aria-hidden="true"></i>
      <span>${escapeHtml(trip.origin.name)} → ${escapeHtml(trip.destination.name)}
      <span class="text-body-secondary">· ${escapeHtml(trip.depart_date_fmt)}</span></span>
    </button></li>`).join("");
  return `<div class="place-popup"><div class="fw-semibold">${escapeHtml(place.name)}</div>
    <div class="small text-body-secondary">${escapeHtml(t("trips_here"))}</div><ul>${items}</ul></div>`;
}

export class TripMap {
  constructor(element, { theme = "light", tiles, onSelect = () => {} } = {}) {
    this.theme = theme;
    this.tileConfig = tiles;
    this.onSelect = onSelect;
    this.entries = new Map();
    this.selectedId = null;

    this.map = L.map(element, { worldCopyJump: true, minZoom: 2, zoomSnap: 0.5 }).setView([35, 5], 2.5);
    const attribution = `&copy; <a href="${OSM_COPYRIGHT}">${escapeHtml(t("osm_contributors"))}</a>`;
    this.tiles = L.tileLayer(this.tileUrl(), {
      attribution: [attribution, tiles.attribution].filter(Boolean).join(" "),
      subdomains: tiles.subdomains,
      maxZoom: tiles.maxZoom,
    }).addTo(this.map);
    this.applyTileFilter();
    // Les pays visités sont dessinés sous les trajets.
    this.map.createPane("countries").style.zIndex = 350;
    this.countries = L.geoJSON(null, {
      pane: "countries",
      attribution: '<a href="https://www.naturalearthdata.com/">Natural Earth</a>',
      style: () => this.countryStyle(),
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        layer.bindTooltip(`${p.flag} ${escapeHtml(p.name)} · ${escapeHtml(p.trips_label)}`,
          { sticky: true, className: "country-tooltip" });
      },
    });
    if (this.readPref(COUNTRIES_PREF, "1") === "1") this.countries.addTo(this.map);
    // Lieux visités : un cercle par lieu, d'autant plus grand qu'on y est souvent allé (masqué par défaut).
    this.places = L.layerGroup();
    if (this.readPref(PLACES_PREF, "0") === "1") this.places.addTo(this.map);
    this.map.on("overlayadd overlayremove", (event) => {
      const value = event.type === "overlayadd" ? "1" : "0";
      if (event.layer === this.countries) this.writePref(COUNTRIES_PREF, value);
      if (event.layer === this.places) this.writePref(PLACES_PREF, value);
    });
    L.control.layers(null, {
      [escapeHtml(t("countries_layer"))]: this.countries,
      [escapeHtml(t("places_layer"))]: this.places,
    }, { position: "topright" }).addTo(this.map);
    this.lines = L.featureGroup().addTo(this.map);
    this.markers = L.markerClusterGroup({
      showCoverageOnHover: false,
      maxClusterRadius: 45,
      iconCreateFunction: (cluster) => L.divIcon({
        html: `<div class="cluster-badge">${cluster.getChildCount()}</div>`, className: "", iconSize: [40, 40],
      }),
    }).addTo(this.map);

    this.addLegend();
    this.map.on("click", () => this.clearSelection());
    this.map.on("popupopen", (event) => {
      event.popup.getElement()?.querySelectorAll("[data-trip-id]").forEach((button) => {
        button.addEventListener("click", () => this.select(Number(button.dataset.tripId), { notify: true }));
      });
    });
  }

  readPref(key, fallback) {
    try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
  }

  writePref(key, value) {
    try { localStorage.setItem(key, value); } catch { /* stockage indisponible */ }
  }

  countryStyle() {
    const color = this.theme === "dark" ? "#818cf8" : "#4f46e5";
    return { color, weight: 1, opacity: 0.5, fillColor: color, fillOpacity: this.theme === "dark" ? 0.18 : 0.12 };
  }

  renderPlaces(data) {
    this.placesData = data;
    this.places.clearLayers();
    const color = this.theme === "dark" ? "#fbbf24" : "#d97706";
    for (const place of data?.places ?? []) {
      L.circleMarker([place.lat, place.lon], {
        pane: "countries", radius: 5 + 3 * Math.sqrt(place.visits), color, weight: 1.5, fillColor: color, fillOpacity: 0.35,
      }).bindTooltip(`${place.country ? `${place.country.flag} ` : ""}${escapeHtml(place.name)} · ${escapeHtml(place.visits_label)}`)
        .addTo(this.places);
    }
  }

  renderCountries(geojson) {
    this.countries.clearLayers();
    if (geojson?.features?.length) this.countries.addData(geojson);
  }

  color(mode) {
    return this.theme === "dark" ? modes[mode].colorDark : modes[mode].color;
  }

  style(trip, leg, state = "normal") {
    // Les voyages à venir sont estompés tant qu'ils ne sont pas sélectionnés.
    const base = trip.status === "upcoming" ? 0.45 : 0.9;
    return {
      color: this.color(trip.transport_mode),
      weight: state === "active" ? 5 : 3,
      opacity: state === "dim" ? 0.2 : state === "active" ? 0.95 : base,
      dashArray: leg === "return" ? "2 9" : null,
      lineCap: "round",
      className: "trip-line",
    };
  }

  tileUrl() {
    return (this.theme === "dark" && this.tileConfig.dark) || this.tileConfig.light;
  }

  /** Sans tuiles sombres dédiées, les tuiles claires sont assombries par un filtre CSS. */
  applyTileFilter() {
    const filtered = this.theme === "dark" && !this.tileConfig.dark;
    this.map.getContainer().classList.toggle("tiles-filter-dark", filtered);
  }

  setTheme(theme) {
    this.theme = theme;
    const url = this.tileUrl();
    if (this.tiles._url !== url) this.tiles.setUrl(url);
    this.applyTileFilter();
    this.countries.setStyle(this.countryStyle());
    this.renderPlaces(this.placesData);
    this.restyle();
  }

  addLegend() {
    const Legend = L.Control.extend({
      options: { position: "topright" },
      onAdd: () => {
        const el = L.DomUtil.create("details", "map-legend");
        el.open = window.matchMedia("(min-width: 992px)").matches;
        el.innerHTML = `<summary><i class="fa-solid fa-circle-info" aria-hidden="true"></i>${escapeHtml(t("legend_title"))}</summary>
          <ul>${modeEntries.map(([key, m]) => `
            <li style="${modeStyle(key)}"><i class="fa-solid ${m.icon}" aria-hidden="true"></i>${escapeHtml(m.label)}</li>`).join("")}
            <li><span class="legend-line" aria-hidden="true"></span>${escapeHtml(t("legend_outbound"))}</li>
            <li><span class="legend-line dashed" aria-hidden="true"></span>${escapeHtml(t("legend_return"))}</li>
            <li><span class="legend-line faded" aria-hidden="true"></span>${escapeHtml(t("legend_upcoming"))}</li>
          </ul>`;
        L.DomEvent.disableClickPropagation(el);
        L.DomEvent.disableScrollPropagation(el);
        return el;
      },
    });
    new Legend().addTo(this.map);
  }

  render(trips) {
    this.lines.clearLayers();
    this.markers.clearLayers();
    this.entries.clear();
    this.selectedId = null;
    const places = new Map();

    for (const trip of trips) {
      const a = [trip.origin.lat, trip.origin.lon];
      const b = [trip.destination.lat, trip.destination.lon];
      const path = trip.transport_mode === "plane" ? greatCircle(a, b) : straight(a, b);
      const outbound = L.polyline(path, this.style(trip, "outbound")).bindPopup(tripPopup(trip, "outbound"));
      const layers = [outbound];
      let inbound = null;
      if (trip.is_round_trip) {
        inbound = L.polyline(bend(path), this.style(trip, "return")).bindPopup(tripPopup(trip, "return"));
        layers.push(inbound);
      }
      for (const layer of layers) {
        layer.on("click", (event) => {
          L.DomEvent.stopPropagation(event);
          this.highlight(trip.id);
          this.onSelect(trip.id);
        });
        this.lines.addLayer(layer);
      }
      this.entries.set(trip.id, { trip, outbound, inbound, path, inboundPath: inbound?.getLatLngs() ?? null });

      for (const place of [trip.origin, trip.destination]) {
        const key = `${place.lat.toFixed(4)},${place.lon.toFixed(4)}`;
        if (!places.has(key)) places.set(key, { ...place, trips: [] });
        places.get(key).trips.push(trip);
      }
    }

    for (const place of places.values()) {
      // Icône et couleur du voyage le plus récent passant par ce lieu.
      const mode = place.trips[0].transport_mode;
      const icon = L.divIcon({
        className: "",
        html: `<span class="map-pin" style="${modeStyle(mode)}"><i class="fa-solid ${modes[mode].icon}" aria-hidden="true"></i></span>`,
        iconSize: [32, 32],
        iconAnchor: [4, 30],
        popupAnchor: [12, -28],
      });
      this.markers.addLayer(
        L.marker([place.lat, place.lon], { icon, title: place.name, alt: place.name, riseOnHover: true })
          .bindPopup(placePopup(place)),
      );
    }
  }

  restyle() {
    for (const [id, { trip, outbound, inbound }] of this.entries) {
      const state = this.selectedId === null ? "normal" : id === this.selectedId ? "active" : "dim";
      outbound.setStyle(this.style(trip, "outbound", state));
      inbound?.setStyle(this.style(trip, "return", state));
    }
  }

  highlight(id) {
    this.selectedId = id;
    this.restyle();
    const entry = this.entries.get(id);
    entry?.outbound.bringToFront();
    entry?.inbound?.bringToFront();
  }

  /** Zoome sur un trajet et ouvre sa fiche. */
  select(id, { notify = false } = {}) {
    const entry = this.entries.get(id);
    if (!entry) return;
    this.highlight(id);
    const group = L.featureGroup([entry.outbound, entry.inbound].filter(Boolean));
    this.map.closePopup();
    this.map.flyToBounds(group.getBounds(), { padding: [60, 60], maxZoom: 9, duration: 0.8 });
    // moveend ne se déclenche pas toujours si la vue ne change pas : délai de secours.
    let opened = false;
    const open = () => {
      if (opened || this.selectedId !== id) return;
      opened = true;
      entry.outbound.openPopup(entry.path[Math.floor(entry.path.length / 2)]);
    };
    this.map.once("moveend", open);
    setTimeout(open, 1000);
    if (notify) this.onSelect(id);
  }

  clearSelection() {
    if (this.selectedId === null) return;
    this.selectedId = null;
    this.restyle();
    this.onSelect(null);
  }

  fitAll() {
    const bounds = this.lines.getBounds();
    if (bounds.isValid()) this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 8 });
  }

  /* --- Rejouer : affichage progressif des trajets ------------------------------------------ */

  /** Masque trajets et repères ; les lignes réapparaissent ensuite avec showLeg(). */
  replayStart() {
    this.replaying = true;
    this.map.closePopup();
    this.clearSelection();
    this.lines.clearLayers();
    this.map.removeLayer(this.markers);
    this.replayShown = new Set();
    this.fitAllEntries();
  }

  fitAllEntries() {
    const group = L.featureGroup([...this.entries.values()].map((e) => e.outbound));
    if (group.getLayers().length) this.map.fitBounds(group.getBounds(), { padding: [40, 40], maxZoom: 6 });
  }

  /** Affiche un trajet (« outbound » ou « return »), en le traçant progressivement si animate. */
  showLeg(id, leg, animate) {
    const entry = this.entries.get(id);
    const key = `${id}:${leg}`;
    if (!entry || this.replayShown.has(key)) return;
    const line = leg === "return" ? entry.inbound : entry.outbound;
    const full = leg === "return" ? entry.inboundPath : entry.path;
    if (!line) return;
    this.replayShown.add(key);
    cancelAnimationFrame(line._grow);
    this.lines.addLayer(line);
    if (!animate) {
      line.setLatLngs(full);
      return;
    }
    const started = performance.now();
    const step = (now) => {
      const progress = Math.min(1, (now - started) / 700);
      line.setLatLngs(full.slice(0, Math.max(2, Math.ceil(progress * full.length))));
      if (progress < 1) line._grow = requestAnimationFrame(step);
    };
    line._grow = requestAnimationFrame(step);
  }

  hideLeg(id, leg) {
    const entry = this.entries.get(id);
    const line = leg === "return" ? entry?.inbound : entry?.outbound;
    if (!line) return;
    cancelAnimationFrame(line._grow);
    this.lines.removeLayer(line);
    this.replayShown.delete(`${id}:${leg}`);
  }

  /** Revient à l'affichage normal : tous les trajets, entiers, et les repères. */
  replayEnd() {
    this.replaying = false;
    for (const entry of this.entries.values()) {
      for (const [line, full] of [[entry.outbound, entry.path], [entry.inbound, entry.inboundPath]]) {
        if (!line) continue;
        cancelAnimationFrame(line._grow);
        line.setLatLngs(full);
        this.lines.addLayer(line);
      }
    }
    this.markers.addTo(this.map);
    this.restyle();
  }

  invalidate() {
    this.map.invalidateSize();
  }
}
