import { escapeHtml, locale, modes, t } from "./i18n.js";
import { currentTheme } from "./theme.js";
import { Replay } from "./replay.js";
import { TripMap } from "./trip-map.js";

const $ = (id) => document.getElementById(id);
const mapEl = $("map");
const filtersForm = $("filters");
const list = $("tripList");
const sortSelect = $("sortSelect");
const sidebar = $("sidebar");
const isCompact = window.matchMedia("(max-width: 991.98px)");
const collator = new Intl.Collator(locale, { sensitivity: "base" });

let trips = [];
let controller = null;
let focusId = Number(mapEl.dataset.focus) || null;
let firstLoad = true;

const tripMap = new TripMap(mapEl, {
  theme: currentTheme(),
  tiles: JSON.parse(mapEl.dataset.tiles),
  onSelect: (id) => markActive(id, true),
});
document.addEventListener("themechange", (event) => tripMap.setTheme(event.detail.theme));

/* --- Rejouer ------------------------------------------------------------------- */

const replay = new Replay(mapEl.parentElement, tripMap, () => trips, {
  onClose: () => replayButton?.focus(),
});
let replayButton = null;
const ReplayControl = L.Control.extend({
  options: { position: "topleft" },
  onAdd: () => {
    const button = L.DomUtil.create("button", "btn replay-toggle shadow-sm");
    button.type = "button";
    button.innerHTML = `<i class="fa-solid fa-clock-rotate-left me-1" aria-hidden="true"></i>${escapeHtml(t("replay"))}`;
    button.title = t("replay_title");
    L.DomEvent.disableClickPropagation(button);
    L.DomEvent.on(button, "click", () => (replay.active ? replay.close() : replay.open()));
    replayButton = button;
    return button;
  },
});
new ReplayControl().addTo(tripMap.map);

/* --- Filtres <-> URL ----------------------------------------------------- */

function readUrl() {
  const params = new URLSearchParams(window.location.search);
  filtersForm.elements.from.value = params.get("from") || "";
  filtersForm.elements.to.value = params.get("to") || "";
  for (const name of ["modes", "tags"]) {
    const selected = (params.get(name) || "").split(",");
    filtersForm.querySelectorAll(`input[name="${name}"]`).forEach((box) => { box.checked = selected.includes(box.value); });
  }
  for (const name of ["kind", "when"]) {
    const radio = filtersForm.querySelector(`input[name="${name}"][value="${CSS.escape(params.get(name) || "all")}"]`);
    if (radio) radio.checked = true;
  }
  if (params.get("sort") && sortSelect.querySelector(`option[value="${CSS.escape(params.get("sort"))}"]`)) {
    sortSelect.value = params.get("sort");
  }
}

function filterParams() {
  const params = new URLSearchParams();
  const { from, to } = filtersForm.elements;
  if (from.value) params.set("from", from.value);
  if (to.value) params.set("to", to.value);
  for (const name of ["modes", "tags"]) {
    const selected = [...filtersForm.querySelectorAll(`input[name="${name}"]:checked`)].map((box) => box.value);
    if (selected.length) params.set(name, selected.join(","));
  }
  for (const name of ["kind", "when"]) {
    const value = filtersForm.querySelector(`input[name="${name}"]:checked`)?.value;
    if (value && value !== "all") params.set(name, value);
  }
  return params;
}

function writeUrl(params) {
  const url = new URLSearchParams(params);
  if (sortSelect.value !== "date_desc") url.set("sort", sortSelect.value);
  const query = url.toString();
  history.replaceState(null, "", window.location.pathname + (query ? `?${query}` : ""));
}

function updateFilterBadge(params) {
  const count = ["from", "to", "modes", "tags", "kind", "when"].filter((key) => params.has(key)).length;
  $("activeFilters").hidden = count === 0;
  $("activeFilters").textContent = count;
  $("resetFilters").hidden = count === 0;
  return count;
}

function datesValid() {
  const { from, to } = filtersForm.elements;
  const invalid = from.value && to.value && from.value > to.value;
  [from, to].forEach((input) => input.classList.toggle("is-invalid", Boolean(invalid)));
  const error = $("filterDateError");
  error.textContent = invalid ? t("filter_dates_invalid") : "";
  error.classList.toggle("d-block", Boolean(invalid));
  return !invalid;
}

/* --- Chargement ---------------------------------------------------------- */

function setLoading(loading) {
  $("mapLoading").classList.toggle("is-hidden", !loading);
  list.setAttribute("aria-busy", String(loading));
  $("stats").setAttribute("aria-busy", String(loading));
}

async function fetchJson(url, signal) {
  const response = await fetch(url, { signal, headers: { Accept: "application/json" } });
  if (response.status === 401) {
    window.location.reload();
    throw new Error("unauthorized");
  }
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
}

async function load() {
  if (!datesValid()) return;
  const params = filterParams();
  writeUrl(params);
  const activeFilters = updateFilterBadge(params);
  controller?.abort();
  controller = new AbortController();
  setLoading(true);
  try {
    const query = params.toString();
    // Tableau de bord : année en cours, quelle que soit la période filtrée (les autres filtres s'appliquent).
    const yearQuery = new URLSearchParams(params);
    yearQuery.delete("from");
    yearQuery.delete("to");
    yearQuery.set("year", mapEl.dataset.year);
    const optional = (url) => fetchJson(url, controller.signal).catch((error) => {
      if (error.name === "AbortError") throw error;
      return null; // couches facultatives
    });
    const [tripData, stats, countries, places] = await Promise.all([
      fetchJson(`${mapEl.dataset.tripsUrl}?${query}`, controller.signal),
      fetchJson(`${mapEl.dataset.statsUrl}?${yearQuery}`, controller.signal),
      optional(`${mapEl.dataset.countriesUrl}?${query}`),
      optional(`${mapEl.dataset.placesUrl}?${query}`),
    ]);
    trips = tripData.trips;
    replay.close();  // un nouvel affichage remplace la relecture en cours
    tripMap.render(trips);
    if (replayButton) replayButton.disabled = trips.length === 0;
    tripMap.renderCountries(countries);
    tripMap.renderPlaces(places);
    renderList(activeFilters > 0);
    renderStats(stats);
    $("listCount").textContent = `· ${tripData.count_label}`;
    $("fabCount").textContent = new Intl.NumberFormat(locale).format(tripData.count);
    if (!firstLoad) $("listStatus").textContent = `${t("results_updated")} : ${tripData.count_label}`;
    if (focusId && trips.some((trip) => trip.id === focusId)) {
      tripMap.select(focusId);
      markActive(focusId, true);
    } else {
      tripMap.fitAll();
    }
    focusId = null;
  } catch (error) {
    if (error.name !== "AbortError") renderError();
  } finally {
    firstLoad = false;
    setLoading(false);
  }
}

/* --- Rendu de la liste ----------------------------------------------------- */

const SORTERS = {
  date_desc: (a, b) => b.depart_date.localeCompare(a.depart_date) || b.id - a.id,
  date_asc: (a, b) => a.depart_date.localeCompare(b.depart_date) || a.id - b.id,
  distance_desc: (a, b) => b.total_distance_km - a.total_distance_km,
  distance_asc: (a, b) => a.total_distance_km - b.total_distance_km,
  origin_asc: (a, b) => collator.compare(a.origin.name, b.origin.name),
  dest_asc: (a, b) => collator.compare(a.destination.name, b.destination.name),
};

function emptyState(icon, title, text, action) {
  return `<li class="empty-state compact">
    <div class="empty-illustration" aria-hidden="true"><i class="fa-solid ${icon}"></i></div>
    <p class="fw-semibold mb-1">${escapeHtml(title)}</p>
    <p class="small text-body-secondary">${escapeHtml(text)}</p>${action}</li>`;
}

function renderError() {
  list.innerHTML = emptyState("fa-triangle-exclamation", t("error_loading"), "",
    `<button type="button" class="btn btn-outline-primary btn-sm rounded-pill px-3" data-action="retry">
      <i class="fa-solid fa-rotate-right me-1" aria-hidden="true"></i>${escapeHtml(t("retry"))}</button>`);
}

function renderList(filtered) {
  if (!trips.length) {
    list.innerHTML = filtered
      ? emptyState("fa-filter-circle-xmark", t("empty_filtered_title"), t("empty_filtered_text"),
        `<button type="button" class="btn btn-outline-primary btn-sm rounded-pill px-3" data-action="reset">
          <i class="fa-solid fa-rotate-left me-1" aria-hidden="true"></i>${escapeHtml(t("reset_filters"))}</button>`)
      : mapEl.dataset.createUrl
        ? emptyState("fa-suitcase-rolling", t("empty_title"), t("empty_text"),
          `<a class="btn btn-primary btn-sm rounded-pill px-3" href="${escapeHtml(mapEl.dataset.createUrl)}">
            <i class="fa-solid fa-plus me-1" aria-hidden="true"></i>${escapeHtml(t("add_trip"))}</a>`)
        : emptyState("fa-suitcase-rolling", t("empty_shared_title"), "", "");
    return;
  }
  const sorted = [...trips].sort(SORTERS[sortSelect.value] || SORTERS.date_desc);
  list.innerHTML = sorted.map((trip, index) => {
    const m = modes[trip.transport_mode];
    const route = `${trip.origin.name} → ${trip.destination.name}`;
    const dates = trip.is_round_trip ? `${trip.depart_date_fmt} – ${trip.return_date_fmt}` : trip.depart_date_fmt;
    return `<li class="trip-item" data-trip-id="${trip.id}" style="--mode-color:${m.color};--mode-color-dark:${m.colorDark};animation-delay:${Math.min(index, 12) * 25}ms">
      <button type="button" class="trip-main" data-action="zoom" title="${escapeHtml(t("zoom_to_trip", { route }))}">
        <span class="mode-dot" aria-hidden="true"><i class="fa-solid ${m.icon}"></i></span>
        <span class="d-block" style="min-width:0">
          <span class="trip-route d-block">${escapeHtml(trip.origin.name)} <span aria-hidden="true">→</span><span class="visually-hidden">,</span> ${escapeHtml(trip.destination.name)}</span>
          ${trip.journey ? `<span class="trip-journey d-block"><i class="fa-solid fa-route me-1" aria-hidden="true"></i>${escapeHtml(t("journey_label", { name: trip.journey.name }))}</span>` : ""}
          ${trip.tags?.length ? `<span class="tag-chips d-block">${trip.tags.map((tag) => `<span class="tag-chip">${escapeHtml(tag)}</span>`).join("")}</span>` : ""}
          ${trip.status !== "past" ? `<span class="badge rounded-pill status-badge status-${trip.status} mt-1">${escapeHtml(trip.countdown)}</span>` : ""}
          <span class="trip-meta">
            <span><span class="visually-hidden">${escapeHtml(trip.mode_label)}, </span>${escapeHtml(dates)}</span>
            <span>${escapeHtml(trip.distance_fmt)}</span>
            ${trip.is_round_trip ? `<span><i class="fa-solid fa-rotate me-1" aria-hidden="true"></i>${escapeHtml(t("round_trip"))}</span>` : ""}
          </span>
        </span>
      </button>
      ${trip.edit_url ? `<div class="trip-actions">
        <a class="btn btn-icon btn-sm" href="${escapeHtml(trip.detail_url)}" aria-label="${escapeHtml(t("trip_details", { route }))}" title="${escapeHtml(t("details"))}">
          <i class="fa-solid fa-circle-info" aria-hidden="true"></i></a>
        <a class="btn btn-icon btn-sm" href="${escapeHtml(trip.edit_url)}" aria-label="${escapeHtml(t("edit_trip", { route }))}" title="${escapeHtml(t("edit"))}">
          <i class="fa-solid fa-pen" aria-hidden="true"></i></a>
        <button type="button" class="btn btn-icon btn-sm text-danger" data-bs-toggle="modal" data-bs-target="#deleteModal"
          data-delete-url="${escapeHtml(trip.delete_url)}" data-delete-label="${escapeHtml(route)}"
          aria-label="${escapeHtml(t("delete_trip", { route }))}" title="${escapeHtml(t("delete"))}">
          <i class="fa-solid fa-trash-can" aria-hidden="true"></i></button>
      </div>` : ""}
    </li>`;
  }).join("");
  if (tripMap.selectedId) markActive(tripMap.selectedId, false);
}

function renderStats(stats) {
  const update = (key, value) => {
    const el = document.querySelector(`[data-stat="${key}"]`);
    if (el.textContent === value) return;
    el.textContent = value;
    el.classList.remove("updated");
    void el.offsetWidth;
    el.classList.add("updated");
  };
  update("count", stats.count_fmt);
  update("distance", stats.total_distance_fmt);
  update("countries", stats.countries_fmt);
  update("co2", stats.co2_fmt);
  renderNextTrip(stats.next_trip);
  const breakdown = $("modeBreakdown");
  breakdown.innerHTML = stats.by_mode.map((item) => {
    const m = modes[item.mode];
    return `<li style="--mode-color:${m.color};--mode-color-dark:${m.colorDark}">
      <i class="fa-solid ${m.icon}" aria-hidden="true"></i>
      <span>${escapeHtml(item.label)}</span>
      <span class="num">${escapeHtml(item.count_fmt)} · ${escapeHtml(item.share_fmt)}</span>
      <span class="bar" aria-hidden="true"><span data-width="${(item.share * 100).toFixed(1)}%"></span></span>
    </li>`;
  }).join("");
  requestAnimationFrame(() => breakdown.querySelectorAll("[data-width]").forEach((bar) => {
    bar.style.width = bar.dataset.width;
  }));
}

function renderNextTrip(next) {
  const card = $("nextTrip");
  card.hidden = !next;
  if (!next) return;
  card.querySelector("[data-next-route]").textContent = next.route;
  card.querySelector("[data-next-countdown]").textContent = next.countdown;
  card.dataset.tripId = next.id;
  card.href = "#";
}

$("nextTrip").addEventListener("click", (event) => {
  event.preventDefault();
  const id = Number(event.currentTarget.dataset.tripId);
  if (trips.some((trip) => trip.id === id)) {
    markActive(id, true);
    tripMap.select(id);
  }
});

function markActive(id, scroll) {
  list.querySelectorAll(".trip-item").forEach((item) => {
    const active = Number(item.dataset.tripId) === id;
    item.classList.toggle("is-active", active);
    const button = item.querySelector(".trip-main");
    if (active) button.setAttribute("aria-current", "true");
    else button.removeAttribute("aria-current");
    if (active && scroll) item.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
}

/* --- Interactions ---------------------------------------------------------- */

list.addEventListener("click", (event) => {
  const action = event.target.closest("[data-action]")?.dataset.action;
  if (action === "retry") return load();
  if (action === "reset") return resetFilters();
  if (action !== "zoom") return;
  const id = Number(event.target.closest(".trip-item").dataset.tripId);
  markActive(id, false);
  const trip = trips.find((item) => item.id === id);
  $("listStatus").textContent = t("selected_trip", { route: `${trip.origin.name} → ${trip.destination.name}` });
  const offcanvas = isCompact.matches ? bootstrap.Offcanvas.getInstance(sidebar) : null;
  if (offcanvas && sidebar.classList.contains("show")) {
    sidebar.addEventListener("hidden.bs.offcanvas", () => tripMap.select(id), { once: true });
    offcanvas.hide();
  } else {
    tripMap.select(id);
  }
});

let debounce = null;
filtersForm.addEventListener("change", () => {
  clearTimeout(debounce);
  debounce = setTimeout(load, 150);
});
filtersForm.addEventListener("submit", (event) => event.preventDefault());

function resetFilters() {
  filtersForm.reset();
  load();
}
$("resetFilters").addEventListener("click", resetFilters);

sortSelect.addEventListener("change", () => {
  writeUrl(filterParams());
  renderList(updateFilterBadge(filterParams()) > 0);
});

readUrl();
load();
