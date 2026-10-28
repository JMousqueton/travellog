import { t } from "./i18n.js";
import { PlaceAutocomplete } from "./place-autocomplete.js";

const form = document.getElementById("tripForm");

/* --- Messages d'erreur côté client ------------------------------------- */

function feedbackFor(input) {
  let el = document.getElementById(`${input.id}-error`);
  if (!el) {
    el = document.createElement("div");
    el.className = "invalid-feedback";
    el.id = `${input.id}-error`;
    input.closest(".mb-3").append(el);
    const describedBy = new Set((input.getAttribute("aria-describedby") || "").split(" ").filter(Boolean));
    describedBy.add(el.id);
    input.setAttribute("aria-describedby", [...describedBy].join(" "));
  }
  return el;
}

function setError(input, message) {
  input.classList.add("is-invalid");
  input.setAttribute("aria-invalid", "true");
  const el = feedbackFor(input);
  el.textContent = message;
  el.classList.add("d-block");
}

function clearError(input) {
  input.classList.remove("is-invalid");
  input.setAttribute("aria-invalid", "false");
  const el = document.getElementById(`${input.id}-error`);
  if (el) {
    el.textContent = "";
    el.classList.remove("d-block");
  }
}

/* --- Compagnie, numéro et appareil (avion et train) --------------------- */

const serviceWrapper = document.getElementById("serviceWrapper");

function syncService() {
  const mode = form.elements.transport_mode.value;
  const open = serviceWrapper.querySelector(`label[data-label-${mode}]`) !== null;
  serviceWrapper.classList.toggle("is-open", open);
  serviceWrapper.toggleAttribute("inert", !open);
  serviceWrapper.setAttribute("aria-hidden", String(!open));
  form.querySelectorAll("[data-plane-only]").forEach((el) => { el.hidden = mode !== "plane"; });
  if (!open) return;
  form.elements.carrier.setAttribute("list", `carriers-${mode}`);
  const suffix = `${mode[0].toUpperCase()}${mode.slice(1)}`;
  serviceWrapper.querySelectorAll("label").forEach((label) => {
    const used = label.dataset[`label${suffix}`] !== undefined;  // numéro et type : avion seulement
    label.parentElement.hidden = !used;
    if (!used) return;
    label.textContent = label.dataset[`label${suffix}`];
    document.getElementById(label.htmlFor).placeholder = label.dataset[`example${suffix}`];
  });
}

form.querySelectorAll('input[name="transport_mode"]').forEach((input) => input.addEventListener("change", syncService));

/* --- Aller-retour ------------------------------------------------------- */

const roundTrip = form.elements.is_round_trip;
const departInput = form.elements.depart_date;
const returnInput = form.elements.return_date;
const returnWrapper = document.getElementById("returnDateWrapper");

function syncRoundTrip() {
  const open = roundTrip.checked;
  returnWrapper.classList.toggle("is-open", open);
  returnWrapper.toggleAttribute("inert", !open);
  returnWrapper.setAttribute("aria-hidden", String(!open));
  roundTrip.setAttribute("aria-expanded", String(open));
  returnInput.required = open;
  if (!open) clearError(returnInput);
}

function syncMinReturn() {
  returnInput.min = departInput.value || "";
}

roundTrip.addEventListener("change", () => {
  syncRoundTrip();
  if (roundTrip.checked) setTimeout(() => returnInput.focus({ preventScroll: true }), 200);
});
departInput.addEventListener("change", () => {
  syncMinReturn();
  clearError(departInput);
});
returnInput.addEventListener("change", () => clearError(returnInput));

function validate() {
  const errors = [];
  for (const input of [form.elements.origin_name, form.elements.dest_name, departInput]) {
    if (!input.value.trim()) errors.push([input, t("field_required")]);
  }
  if (roundTrip.checked) {
    if (!returnInput.value) errors.push([returnInput, t("return_required")]);
    else if (departInput.value && returnInput.value < departInput.value) {
      errors.push([returnInput, t("return_before_departure")]);
    }
  }
  errors.forEach(([input, message]) => setError(input, message));
  return errors;
}

form.addEventListener("submit", (event) => {
  const errors = validate();
  if (errors.length) {
    event.preventDefault();
    errors[0][0].focus();
  }
});

/* --- Inversion origine / destination ------------------------------------ */

const [origin, dest] = [...form.querySelectorAll("[data-autocomplete]")]
  .map((el) => new PlaceAutocomplete(el, { scope: form, onEdit: clearError }));
const swapButton = document.getElementById("swapPlaces");

/* --- Numéro de vol : compagnie, départ et arrivée pré-remplis ------------- */

const flightStatus = document.getElementById("flightLookupStatus");
let flightRequest = null;

async function lookupFlight() {
  const number = form.elements.service_number.value.trim();
  if (form.elements.transport_mode.value !== "plane" || number.length < 3 || !form.dataset.flightUrl) return;
  flightRequest?.abort();
  flightRequest = new AbortController();
  flightStatus.textContent = t("flight_searching");
  try {
    const response = await fetch(`${form.dataset.flightUrl}?number=${encodeURIComponent(number)}`,
      { signal: flightRequest.signal, headers: { Accept: "application/json" } });
    if (!response.ok) {
      flightStatus.textContent = response.status === 404 ? t("flight_unknown") : "";
      return;
    }
    const flight = await response.json();
    // Ne remplit que ce qui est vide : une saisie n'est jamais écrasée.
    form.elements.service_number.value = flight.service_number;
    if (flight.carrier && !form.elements.carrier.value.trim()) form.elements.carrier.value = flight.carrier;
    const places = flight.origin && flight.dest && !origin.snapshot().name.trim() && !dest.snapshot().name.trim();
    if (places) {
      origin.restore({ name: flight.origin.name, lat: flight.origin.lat, lon: flight.origin.lon, country: flight.origin.country });
      dest.restore({ name: flight.dest.name, lat: flight.dest.lat, lon: flight.dest.lon, country: flight.dest.country });
    }
    flightStatus.textContent = places ? t("flight_found_route") : (flight.origin ? t("flight_found_kept") : t("flight_found_airline"));
  } catch (error) {
    if (error.name !== "AbortError") flightStatus.textContent = "";
  }
}

form.elements.service_number.addEventListener("change", lookupFlight);
swapButton?.addEventListener("click", () => {
  const a = origin.snapshot();
  origin.restore(dest.snapshot());
  dest.restore(a);
  swapButton.classList.toggle("spin");
});

/* --- Brouillon conservé lors d'un changement de langue -------------------- */

const draftKey = form.dataset.draftKey;
document.addEventListener("languagechange", () => {
  const draft = {
    origin: origin.snapshot(),
    dest: dest.snapshot(),
    depart: departInput.value,
    mode: form.elements.transport_mode.value,
    round: roundTrip.checked,
    ret: returnInput.value,
    notes: form.elements.notes.value,
    carrier: form.elements.carrier.value,
    service_number: form.elements.service_number.value,
    return_service_number: form.elements.return_service_number.value,
    vehicle: form.elements.vehicle.value,
  };
  try { sessionStorage.setItem(draftKey, JSON.stringify(draft)); } catch { /* ignoré */ }
});

(function restoreDraft() {
  let draft = null;
  try {
    draft = JSON.parse(sessionStorage.getItem(draftKey) || "null");
    sessionStorage.removeItem(draftKey);
  } catch { /* ignoré */ }
  if (!draft) return;
  origin.restore(draft.origin);
  dest.restore(draft.dest);
  departInput.value = draft.depart;
  const mode = form.querySelector(`input[name="transport_mode"][value="${CSS.escape(draft.mode)}"]`);
  if (mode) mode.checked = true;
  roundTrip.checked = draft.round;
  returnInput.value = draft.ret;
  if (draft.notes !== undefined) form.elements.notes.value = draft.notes;
  for (const key of ["carrier", "service_number", "return_service_number", "vehicle"]) {
    if (draft[key] !== undefined) form.elements[key].value = draft[key];
  }
})();

syncRoundTrip();
syncMinReturn();
syncService();
