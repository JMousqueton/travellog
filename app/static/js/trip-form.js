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
})();

syncRoundTrip();
syncMinReturn();
