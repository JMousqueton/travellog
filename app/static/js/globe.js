import { escapeHtml, modes, t } from "./i18n.js";
import { tripPopup } from "./trip-map.js";

const RAD = Math.PI / 180;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const MIN_ZOOM = 0.6;
const MAX_ZOOM = 12;
const HIT_PX = 8;           // distance de clic ou de survol d'un trajet, en pixels
const SPIN_DEG_PER_MS = 0.006;

const PALETTE = {
  light: {
    ocean: "#dfe7f5", land: "#ffffff", border: "rgba(15, 23, 42, .14)", graticule: "rgba(15, 23, 42, .05)",
    visited: "rgba(79, 70, 229, .30)", visitedBorder: "rgba(79, 70, 229, .55)", glow: "rgba(79, 70, 229, .16)",
    pinStroke: "#ffffff",
  },
  dark: {
    ocean: "#0f1724", land: "#1f2735", border: "rgba(255, 255, 255, .10)", graticule: "rgba(255, 255, 255, .04)",
    visited: "rgba(129, 140, 248, .24)", visitedBorder: "rgba(129, 140, 248, .6)", glow: "rgba(129, 140, 248, .22)",
    pinStroke: "#0d1117",
  },
};

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
const ease = (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2);

/** Distance d'un point à un segment, en pixels. */
function segmentDistance(px, py, [ax, ay], [bx, by]) {
  const dx = bx - ax, dy = by - ay;
  const f = dx === 0 && dy === 0 ? 0 : clamp(((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy), 0, 1);
  return Math.hypot(px - (ax + f * dx), py - (ay + f * dy));
}

/**
 * Globe (projection orthographique d3-geo sur un canevas) : mêmes trajets que la carte, vols en arcs
 * au-dessus de la surface, pays visités colorés. Expose la même interface que TripMap pour la relecture.
 */
export class Globe {
  constructor(wrapper, { theme = "light", worldUrl, onSelect = () => {} } = {}) {
    this.theme = theme;
    this.worldUrl = worldUrl;
    this.onSelect = onSelect;
    this.entries = new Map();
    this.visited = new Set();
    this.pins = [];
    this.selectedId = null;
    this.rotation = [-5, -35, 0];
    this.zoom = 1;
    this.spinning = !reducedMotion.matches;
    this.shown = null;   // relecture : trajets affichés (clé « id:aller|retour » -> progression 0..1)
    this.hits = [];

    this.el = document.createElement("div");
    this.el.className = "globe-view";
    this.el.hidden = true;
    this.el.innerHTML = `
      <canvas class="globe-canvas" tabindex="0" role="img" aria-label="${escapeHtml(t("globe_label"))}"></canvas>
      <div class="globe-tooltip" hidden></div>
      <div class="globe-zoom btn-group-vertical shadow-sm" role="group">
        <button type="button" class="btn" data-globe-zoom="1" aria-label="${escapeHtml(t("zoom_in"))}"><i class="fa-solid fa-plus" aria-hidden="true"></i></button>
        <button type="button" class="btn" data-globe-zoom="-1" aria-label="${escapeHtml(t("zoom_out"))}"><i class="fa-solid fa-minus" aria-hidden="true"></i></button>
      </div>
      <div class="globe-card shadow" hidden>
        <button type="button" class="btn-close" aria-label="${escapeHtml(t("close"))}"></button>
        <div data-globe-card-body></div>
      </div>
      <p class="globe-attribution"><a href="https://www.naturalearthdata.com/">Natural Earth</a></p>`;
    wrapper.append(this.el);
    this.canvas = this.el.querySelector("canvas");
    this.ctx = this.canvas.getContext("2d");
    this.tooltip = this.el.querySelector(".globe-tooltip");
    this.card = this.el.querySelector(".globe-card");
    this.projection = d3.geoOrthographic().clipAngle(90).precision(0.4);
    this.graticule = d3.geoGraticule10();

    new ResizeObserver(() => this.resize()).observe(this.el);
    this.bindPointer();
    this.bindKeyboard();
    this.el.querySelectorAll("[data-globe-zoom]").forEach((button) => {
      button.addEventListener("click", () => this.zoomBy(Number(button.dataset.globeZoom) > 0 ? 1.5 : 1 / 1.5));
    });
    this.card.querySelector(".btn-close").addEventListener("click", () => this.clearSelection());
  }

  /* --- Affichage ---------------------------------------------------------------------------- */

  get visible() {
    return !this.el.hidden;
  }

  async show() {
    this.el.hidden = false;
    this.resize();
    if (!this.world) {
      try {
        const response = await fetch(this.worldUrl);
        const world = await response.json();
        // d3-geo attend des anneaux extérieurs dans le sens horaire : un pays plus grand qu'un hémisphère
        // est en fait mal orienté.
        for (const feature of world.features) {
          if (d3.geoArea(feature) > 2 * Math.PI) {
            feature.geometry.coordinates = feature.geometry.coordinates.map((poly) => poly.map((ring) => ring.slice().reverse()));
          }
        }
        this.world = world;
      } catch {
        this.world = { features: [] };
      }
    }
    this.startSpin();
    this.requestDraw();
  }

  hide() {
    this.el.hidden = true;
    this.hideTooltip();
    cancelAnimationFrame(this.spinFrame);
    cancelAnimationFrame(this.flight);
  }

  resize() {
    if (!this.visible) return;
    const { width, height } = this.el.getBoundingClientRect();
    this.dpr = window.devicePixelRatio || 1;
    this.width = width;
    this.height = height;
    this.canvas.width = Math.round(width * this.dpr);
    this.canvas.height = Math.round(height * this.dpr);
    this.canvas.style.width = `${width}px`;
    this.canvas.style.height = `${height}px`;
    this.draw();
  }

  get radius() {
    return (Math.min(this.width, this.height) / 2) * 0.86 * this.zoom;
  }

  setTheme(theme) {
    this.theme = theme;
    this.requestDraw();
  }

  color(mode) {
    return this.theme === "dark" ? modes[mode].colorDark : modes[mode].color;
  }

  requestDraw() {
    if (this.drawFrame || !this.visible) return;
    this.drawFrame = requestAnimationFrame(() => {
      this.drawFrame = null;
      this.draw();
    });
  }

  /** Projette un point [lon, lat] à l'altitude h (en rayons) : [x, y] à l'écran, ou null s'il est caché. */
  project(point, h = 0) {
    const [λ, φ] = this.rotate(point);
    const cosφ = Math.cos(φ * RAD);
    const x = cosφ * Math.sin(λ * RAD), y = Math.sin(φ * RAD), z = cosφ * Math.cos(λ * RAD);
    // Visible devant le globe, ou derrière mais assez haut pour dépasser de sa silhouette.
    if (z < 0 && (1 + h) * Math.hypot(x, y) <= 1) return null;
    const k = (1 + h) * this.radius;
    return [this.width / 2 + k * x, this.height / 2 - k * y];
  }

  draw() {
    if (!this.visible || !this.width) return;
    const { ctx } = this;
    const palette = PALETTE[this.theme] || PALETTE.light;
    const r = this.radius;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.width, this.height);
    this.projection.rotate(this.rotation).scale(r).translate([this.width / 2, this.height / 2]);
    this.rotate = d3.geoRotation(this.rotation);
    const path = d3.geoPath(this.projection, ctx);

    // Halo, océan, méridiens et parallèles.
    const glow = ctx.createRadialGradient(this.width / 2, this.height / 2, r * 0.96, this.width / 2, this.height / 2, r * 1.12);
    glow.addColorStop(0, palette.glow);
    glow.addColorStop(1, "transparent");
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, this.width, this.height);
    ctx.beginPath();
    path({ type: "Sphere" });
    ctx.fillStyle = palette.ocean;
    ctx.fill();
    ctx.beginPath();
    path(this.graticule);
    ctx.strokeStyle = palette.graticule;
    ctx.lineWidth = 1;
    ctx.stroke();

    // Terres puis pays visités.
    const features = this.world?.features ?? [];
    ctx.beginPath();
    for (const feature of features) path(feature);
    ctx.fillStyle = palette.land;
    ctx.fill();
    ctx.strokeStyle = palette.border;
    ctx.lineWidth = 0.6;
    ctx.stroke();
    if (this.visited.size) {
      ctx.beginPath();
      for (const feature of features) if (this.visited.has(feature.properties.code)) path(feature);
      ctx.fillStyle = palette.visited;
      ctx.fill();
      ctx.strokeStyle = palette.visitedBorder;
      ctx.lineWidth = 0.8;
      ctx.stroke();
    }

    // Trajets : le trajet sélectionné en dernier, au-dessus des autres.
    this.hits = [];
    const ordered = [...this.entries.values()].sort((a, b) => (a.trip.id === this.selectedId) - (b.trip.id === this.selectedId));
    for (const entry of ordered) {
      for (const leg of entry.trip.is_round_trip ? ["outbound", "return"] : ["outbound"]) {
        const progress = this.shown ? this.shown.get(`${entry.trip.id}:${leg}`) : 1;
        if (progress) this.drawLeg(entry, leg, progress);
      }
    }

    // Repères aux extrémités des trajets affichés.
    for (const pin of this.pins) {
      if (this.shown && !pin.trips.some((id) => this.shown.has(`${id}:outbound`))) continue;
      const xy = this.project(pin.point);
      if (!xy) continue;
      ctx.beginPath();
      ctx.arc(xy[0], xy[1], 3.5, 0, 2 * Math.PI);
      ctx.fillStyle = this.color(pin.mode);
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = palette.pinStroke;
      ctx.stroke();
    }
  }

  drawLeg(entry, leg, progress) {
    const { ctx } = this;
    const { trip } = entry;
    const samples = leg === "return" ? entry.back : entry.samples;
    const last = Math.max(1, Math.ceil(progress * (samples.length - 1)));
    const state = this.selectedId === null ? "normal" : trip.id === this.selectedId ? "active" : "dim";
    const base = trip.status === "upcoming" ? 0.45 : 0.9;
    ctx.globalAlpha = state === "dim" ? 0.18 : state === "active" ? 1 : base;
    ctx.strokeStyle = this.color(trip.transport_mode);
    ctx.lineWidth = state === "active" ? 3.5 : 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.setLineDash(leg === "return" ? [2, 7] : []);
    ctx.beginPath();
    const points = [];
    let previous = null;
    for (let i = 0; i <= last; i += 1) {
      const xy = this.project(samples[i].point, samples[i].h);
      if (xy) {
        if (previous) ctx.lineTo(xy[0], xy[1]);
        else ctx.moveTo(xy[0], xy[1]);
        points.push(xy);
      } else if (points.length) {
        this.hits.push({ id: trip.id, leg, points: points.splice(0) });
      }
      previous = xy;
    }
    if (points.length) this.hits.push({ id: trip.id, leg, points });
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;
  }

  /* --- Données ------------------------------------------------------------------------------- */

  render(trips) {
    this.entries.clear();
    this.selectedId = null;
    this.hideCard();
    const pins = new Map();
    for (const trip of trips) {
      const a = [trip.origin.lon, trip.origin.lat];
      const b = [trip.destination.lon, trip.destination.lat];
      const distance = d3.geoDistance(a, b);
      const interpolate = d3.geoInterpolate(a, b);
      // Les vols montent au-dessus de la surface, d'autant plus haut qu'ils sont longs.
      const lift = trip.transport_mode === "plane" ? Math.min(0.22, 0.12 * distance + 0.02) : 0;
      const count = clamp(Math.ceil(distance / RAD / 1.5), 8, 120);
      const samples = [], back = [];
      for (let i = 0; i <= count; i += 1) {
        const f = i / count;
        const bump = Math.sin(Math.PI * f);
        samples.push({ point: interpolate(f), h: lift * bump });
        // Le retour passe un peu plus haut pour rester visible à côté de l'aller.
        back.push({ point: interpolate(1 - f), h: lift * bump + Math.min(0.03, 0.02 + distance * 0.02) * bump });
      }
      this.entries.set(trip.id, { trip, a, b, distance, midpoint: interpolate(0.5), samples, back });
      for (const point of [a, b]) {
        const key = `${point[0].toFixed(3)},${point[1].toFixed(3)}`;
        if (!pins.has(key)) pins.set(key, { point, mode: trip.transport_mode, trips: [] });
        pins.get(key).trips.push(trip.id);
      }
    }
    this.pins = [...pins.values()];
    this.requestDraw();
  }

  renderCountries(geojson) {
    this.visited = new Set((geojson?.features ?? []).map((feature) => feature.properties.code));
    this.requestDraw();
  }

  /* --- Mouvements ------------------------------------------------------------------------------ */

  stopSpin() {
    this.spinning = false;
    cancelAnimationFrame(this.spinFrame);
  }

  startSpin() {
    if (!this.spinning || this.selectedId !== null || this.shown) return;
    cancelAnimationFrame(this.spinFrame);
    let previous = performance.now();
    const step = (now) => {
      if (!this.spinning || !this.visible) return;
      this.rotation[0] += (now - previous) * SPIN_DEG_PER_MS;
      previous = now;
      this.draw();
      this.spinFrame = requestAnimationFrame(step);
    };
    this.spinFrame = requestAnimationFrame(step);
  }

  /** Tourne le globe vers [lon, lat] (et change le zoom), en animant si possible. */
  flyTo(center, zoom = this.zoom, done = () => {}) {
    cancelAnimationFrame(this.flight);
    const from = [-this.rotation[0], -this.rotation[1]];
    const path = d3.geoInterpolate(from, center);
    const startZoom = this.zoom;
    const apply = (f) => {
      const [lon, lat] = path(f);
      this.rotation = [-lon, -lat, 0];
      this.zoom = startZoom * (zoom / startZoom) ** f;
      this.draw();
    };
    if (reducedMotion.matches || !this.visible) {
      apply(1);
      done();
      return;
    }
    const duration = 650 + 500 * d3.geoDistance(from, center);
    const started = performance.now();
    const step = (now) => {
      const f = Math.min(1, (now - started) / duration);
      apply(ease(f));
      if (f < 1) this.flight = requestAnimationFrame(step);
      else done();
    };
    this.flight = requestAnimationFrame(step);
  }

  zoomBy(factor) {
    this.stopSpin();
    this.zoom = clamp(this.zoom * factor, MIN_ZOOM, MAX_ZOOM);
    this.requestDraw();
  }

  /** Centre le globe sur l'ensemble des trajets. */
  fitAll() {
    const entries = [...this.entries.values()];
    if (!entries.length) return;
    const centroid = d3.geoCentroid({
      type: "MultiPoint", coordinates: entries.flatMap((entry) => [entry.a, entry.b]),
    });
    const spread = Math.max(...entries.flatMap((entry) => [d3.geoDistance(centroid, entry.a), d3.geoDistance(centroid, entry.b)]));
    const zoom = clamp(1 / Math.max(Math.sin(Math.min(spread, Math.PI / 2)) * 1.15, 0.2), 1, 4);
    if (Number.isFinite(centroid[0])) this.flyTo(centroid, zoom);
  }

  /* --- Sélection ---------------------------------------------------------------------------------- */

  select(id, { notify = false } = {}) {
    const entry = this.entries.get(id);
    if (!entry) return;
    this.stopSpin();
    this.selectedId = id;
    this.hideCard();
    const zoom = clamp(0.9 / Math.sqrt(Math.max(entry.distance, 0.006)), 1, 10);
    this.flyTo(entry.midpoint, zoom, () => {
      if (this.selectedId === id) this.showCard(entry.trip);
    });
    if (notify) this.onSelect(id);
  }

  clearSelection() {
    this.hideCard();
    if (this.selectedId === null) return;
    this.selectedId = null;
    this.requestDraw();
    this.onSelect(null);
  }

  showCard(trip) {
    this.card.querySelector("[data-globe-card-body]").innerHTML = tripPopup(trip, "outbound");
    this.card.hidden = false;
  }

  hideCard() {
    this.card.hidden = true;
  }

  hitTest(x, y) {
    let best = null, bestDistance = HIT_PX;
    for (const hit of this.hits) {
      for (let i = 1; i < hit.points.length; i += 1) {
        const distance = segmentDistance(x, y, hit.points[i - 1], hit.points[i]);
        if (distance < bestDistance) [best, bestDistance] = [hit, distance];
      }
    }
    return best;
  }

  showTooltip(hit, x, y) {
    const { trip } = this.entries.get(hit.id);
    const [from, to] = hit.leg === "return" ? [trip.destination.name, trip.origin.name] : [trip.origin.name, trip.destination.name];
    this.tooltip.textContent = `${from} → ${to} · ${trip.depart_date_fmt}`;
    this.tooltip.style.transform = `translate(${Math.round(x + 14)}px, ${Math.round(y + 14)}px)`;
    this.tooltip.hidden = false;
  }

  hideTooltip() {
    this.tooltip.hidden = true;
  }

  /* --- Souris, doigts et clavier --------------------------------------------------------------- */

  bindPointer() {
    const pointers = new Map();
    let drag = null, pinch = null;
    const local = (event) => {
      const box = this.canvas.getBoundingClientRect();
      return [event.clientX - box.left, event.clientY - box.top];
    };
    this.canvas.addEventListener("pointerdown", (event) => {
      this.canvas.setPointerCapture(event.pointerId);
      pointers.set(event.pointerId, local(event));
      if (pointers.size === 1) drag = { start: local(event), last: local(event), moved: false };
      if (pointers.size === 2) {
        const [p, q] = [...pointers.values()];
        pinch = { distance: Math.hypot(p[0] - q[0], p[1] - q[1]), zoom: this.zoom };
        drag = null;
      }
    });
    this.canvas.addEventListener("pointermove", (event) => {
      const xy = local(event);
      if (!pointers.has(event.pointerId)) {
        if (event.pointerType !== "mouse") return;
        const hit = this.hitTest(...xy);
        this.canvas.style.cursor = hit ? "pointer" : "grab";
        if (hit) this.showTooltip(hit, ...xy);
        else this.hideTooltip();
        return;
      }
      pointers.set(event.pointerId, xy);
      if (pinch && pointers.size === 2) {
        const [p, q] = [...pointers.values()];
        this.zoom = clamp(pinch.zoom * (Math.hypot(p[0] - q[0], p[1] - q[1]) / pinch.distance), MIN_ZOOM, MAX_ZOOM);
        this.requestDraw();
        return;
      }
      if (!drag) return;
      if (!drag.moved && Math.hypot(xy[0] - drag.start[0], xy[1] - drag.start[1]) < 4) return;
      if (!drag.moved) {
        drag.moved = true;
        this.stopSpin();
        cancelAnimationFrame(this.flight);
        this.hideTooltip();
        this.canvas.style.cursor = "grabbing";
      }
      const degreesPerPixel = 1 / (this.radius * RAD);
      this.rotation[0] += (xy[0] - drag.last[0]) * degreesPerPixel;
      this.rotation[1] = clamp(this.rotation[1] - (xy[1] - drag.last[1]) * degreesPerPixel, -90, 90);
      drag.last = xy;
      this.requestDraw();
    });
    const release = (event) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.delete(event.pointerId);
      if (pointers.size < 2) pinch = null;
      if (event.type === "pointerup" && drag && !drag.moved) {
        const hit = this.hitTest(...local(event));
        if (hit) this.select(hit.id, { notify: true });
        else this.clearSelection();
      }
      if (!pointers.size) {
        drag = null;
        this.canvas.style.cursor = "grab";
      }
    };
    this.canvas.addEventListener("pointerup", release);
    this.canvas.addEventListener("pointercancel", release);
    this.canvas.addEventListener("pointerleave", () => this.hideTooltip());
    this.canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      this.zoomBy(Math.exp(-event.deltaY * 0.0015));
    }, { passive: false });
  }

  bindKeyboard() {
    this.canvas.addEventListener("keydown", (event) => {
      const step = 10 / this.zoom;
      const moves = {
        ArrowLeft: () => { this.rotation[0] += step; },
        ArrowRight: () => { this.rotation[0] -= step; },
        ArrowUp: () => { this.rotation[1] = clamp(this.rotation[1] - step, -90, 90); },
        ArrowDown: () => { this.rotation[1] = clamp(this.rotation[1] + step, -90, 90); },
        "+": () => { this.zoom = clamp(this.zoom * 1.25, MIN_ZOOM, MAX_ZOOM); },
        "=": () => { this.zoom = clamp(this.zoom * 1.25, MIN_ZOOM, MAX_ZOOM); },
        "-": () => { this.zoom = clamp(this.zoom / 1.25, MIN_ZOOM, MAX_ZOOM); },
      };
      if (event.key === "Escape") return this.clearSelection();
      if (!moves[event.key]) return;
      event.preventDefault();
      this.stopSpin();
      moves[event.key]();
      this.requestDraw();
    });
  }

  /* --- Rejouer ---------------------------------------------------------------------------------- */

  replayStart() {
    this.stopSpin();
    this.clearSelection();
    this.shown = new Map();
    this.fitAll();
    this.requestDraw();
  }

  showLeg(id, leg, animate) {
    const key = `${id}:${leg}`;
    if (!this.entries.has(id) || this.shown.has(key)) return;
    if (!animate) {
      this.shown.set(key, 1);
      this.requestDraw();
      return;
    }
    const started = performance.now();
    const step = (now) => {
      if (!this.shown?.has(key)) return;
      const progress = Math.min(1, (now - started) / 700);
      this.shown.set(key, Math.max(progress, 0.001));
      this.requestDraw();
      if (progress < 1) requestAnimationFrame(step);
    };
    this.shown.set(key, 0.001);
    requestAnimationFrame(step);
  }

  hideLeg(id, leg) {
    if (this.shown?.delete(`${id}:${leg}`)) this.requestDraw();
  }

  replayEnd() {
    this.shown = null;
    this.requestDraw();
  }

  invalidate() {
    this.resize();
  }
}
