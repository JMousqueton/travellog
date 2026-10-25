import { escapeHtml, locale, t } from "./i18n.js";

const DAY = 86_400_000;
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const monthFormat = new Intl.DateTimeFormat(locale, { month: "long", year: "numeric", timeZone: "UTC" });
const dayFormat = new Intl.DateTimeFormat(locale, { dateStyle: "long", timeZone: "UTC" });
const toTime = (iso) => Date.parse(`${iso}T00:00:00Z`);

/**
 * Rejoue les trajets dans l'ordre chronologique : chaque trajet se dessine à sa date de départ,
 * le retour d'un aller-retour à sa date de retour. Le curseur permet de se placer à n'importe quelle date.
 */
export class Replay {
  constructor(mapWrapper, tripMap, getTrips, { onClose = () => {} } = {}) {
    this.tripMap = tripMap;
    this.getTrips = getTrips;
    this.onClose = onClose;
    this.panel = this.buildPanel(mapWrapper);
    this.slider = this.panel.querySelector("input[type=range]");
    this.playButton = this.panel.querySelector("[data-replay-play]");
    this.label = this.panel.querySelector("[data-replay-date]");
    this.slider.addEventListener("input", () => {
      const day = Number(this.slider.value);  // lu avant pause(), qui replace le curseur sur la position courante
      this.pause();
      this.seek(day, false);
    });
    this.playButton.addEventListener("click", () => (this.timer ? this.pause() : this.play()));
    this.panel.querySelector("[data-replay-close]").addEventListener("click", () => this.close());
    this.panel.addEventListener("keydown", (event) => {
      if (event.key === "Escape") this.close();
    });
  }

  buildPanel(wrapper) {
    const panel = document.createElement("div");
    panel.className = "replay-panel shadow";
    panel.hidden = true;
    panel.setAttribute("role", "region");
    panel.setAttribute("aria-label", t("replay_title"));
    panel.innerHTML = `
      <button type="button" class="btn btn-primary btn-icon-round" data-replay-play aria-label="${escapeHtml(t("replay_play"))}">
        <i class="fa-solid fa-play" aria-hidden="true"></i></button>
      <div class="replay-track">
        <div class="replay-date" data-replay-date aria-hidden="true"></div>
        <input type="range" class="form-range" min="0" max="0" step="1" value="0" aria-label="${escapeHtml(t("replay_date"))}">
        <div class="replay-years" aria-hidden="true"></div>
      </div>
      <button type="button" class="btn-close" data-replay-close aria-label="${escapeHtml(t("replay_close"))}"></button>`;
    wrapper.append(panel);
    return panel;
  }

  /** Événements (date, trajet, aller ou retour), triés. */
  events() {
    const events = [];
    for (const trip of this.getTrips()) {
      events.push({ time: toTime(trip.depart_date), id: trip.id, leg: "outbound" });
      if (trip.is_round_trip && trip.return_date) events.push({ time: toTime(trip.return_date), id: trip.id, leg: "return" });
    }
    return events.sort((a, b) => a.time - b.time || a.id - b.id);
  }

  open() {
    this.list = this.events();
    if (!this.list.length) return;
    this.start = this.list[0].time;
    this.span = Math.max(1, Math.round((this.list[this.list.length - 1].time - this.start) / DAY));
    this.slider.max = String(this.span);
    this.renderYears();
    this.panel.hidden = false;
    this.tripMap.replayStart();
    this.seek(0, false);
    this.playButton.focus();
    this.play();
  }

  renderYears() {
    const first = new Date(this.start).getUTCFullYear();
    const last = new Date(this.start + this.span * DAY).getUTCFullYear();
    const marks = [];
    for (let year = first; year <= last; year += 1) {
      const offset = (Date.UTC(year, 0, 1) - this.start) / DAY;
      const percent = year === first ? 0 : (100 * offset) / this.span;
      if (percent <= 100) marks.push(`<span style="left:${percent.toFixed(2)}%">${year}</span>`);
    }
    this.panel.querySelector(".replay-years").innerHTML = marks.join("");
  }

  /** Se place au jour `day` : affiche les trajets passés, masque les suivants. */
  seek(day, animate) {
    this.day = day;
    const now = this.start + day * DAY;
    for (const event of this.list) {
      if (event.time <= now) this.tripMap.showLeg(event.id, event.leg, animate && !reducedMotion.matches);
      else this.tripMap.hideLeg(event.id, event.leg);
    }
    this.slider.value = String(day);
    const text = monthFormat.format(now);
    this.label.textContent = text;
    this.slider.setAttribute("aria-valuetext", dayFormat.format(now));
  }

  play() {
    if (this.day >= this.span) this.seek(0, false);
    // Environ une seconde par trajet, entre 8 et 40 secondes au total.
    const duration = Math.min(40_000, Math.max(8_000, this.list.length * 900));
    const daysPerMs = this.span / duration;
    let previous = performance.now();
    const tick = (now) => {
      const next = Math.min(this.span, this.day + (now - previous) * daysPerMs);
      previous = now;
      this.seek(next, true);
      if (next >= this.span) return this.pause();
      this.timer = requestAnimationFrame(tick);
    };
    this.timer = requestAnimationFrame(tick);
    this.setPlaying(true);
  }

  pause() {
    cancelAnimationFrame(this.timer);
    this.timer = null;
    this.seek(Math.round(this.day), false);
    this.setPlaying(false);
  }

  setPlaying(playing) {
    this.playButton.innerHTML = `<i class="fa-solid ${playing ? "fa-pause" : "fa-play"}" aria-hidden="true"></i>`;
    this.playButton.setAttribute("aria-label", t(playing ? "replay_pause" : "replay_play"));
  }

  close() {
    if (this.panel.hidden) return;
    cancelAnimationFrame(this.timer);
    this.timer = null;
    this.panel.hidden = true;
    this.tripMap.replayEnd();
    this.onClose();
  }

  get active() {
    return !this.panel.hidden;
  }
}
