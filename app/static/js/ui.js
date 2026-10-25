import { escapeHtml, t } from "./i18n.js";

export const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content ?? "";

const ICONS = { success: "fa-circle-check", danger: "fa-circle-exclamation", warning: "fa-triangle-exclamation", info: "fa-circle-info" };

export function showToast(message, variant = "info") {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const el = document.createElement("div");
  el.className = `toast app-toast toast-${variant}`;
  el.setAttribute("role", variant === "danger" ? "alert" : "status");
  el.innerHTML = `<div class="d-flex align-items-center gap-2 p-3">
      <i class="fa-solid ${ICONS[variant] ?? ICONS.info} toast-icon" aria-hidden="true"></i>
      <div class="flex-grow-1">${escapeHtml(message)}</div>
      <button type="button" class="btn-close" data-bs-dismiss="toast"></button></div>`;
  container.append(el);
  el.addEventListener("hidden.bs.toast", () => el.remove());
  bootstrap.Toast.getOrCreateInstance(el, { delay: 5000 }).show();
}

function initFlashToasts() {
  document.querySelectorAll(".toast[data-autoshow]").forEach((el) => {
    bootstrap.Toast.getOrCreateInstance(el, { delay: 5000 }).show();
  });
}

/** Modale de confirmation partagée : alimentée par les attributs data-delete-*. */
function initDeleteModal() {
  const modal = document.getElementById("deleteModal");
  if (!modal) return;
  const title = modal.querySelector("#deleteModalTitle");
  const defaultTitle = title.textContent;
  modal.addEventListener("show.bs.modal", (event) => {
    const trigger = event.relatedTarget;
    if (!trigger) return;
    const form = modal.querySelector("form");
    form.action = trigger.dataset.deleteUrl;
    form.elements.next.value = trigger.dataset.deleteNext || window.location.pathname + window.location.search;
    modal.querySelector("[data-delete-label]").textContent = trigger.dataset.deleteLabel || "";
    title.textContent = trigger.dataset.deleteTitle || defaultTitle;
  });
}

/** Indicateur de chargement sur les boutons de soumission. */
function initSubmitSpinners() {
  document.addEventListener("submit", (event) => {
    if (event.defaultPrevented) return;
    const button = event.submitter ?? event.target.querySelector('[type="submit"]');
    if (!button || button.disabled) return;
    const text = button.dataset.loadingText;
    // Différé pour ne pas retirer le bouton du formulaire avant l'envoi.
    setTimeout(() => {
      button.disabled = true;
      button.innerHTML = `<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>${escapeHtml(text || button.textContent.trim())}`;
    }, 0);
  });
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });
}

/** Le sélecteur de langue renvoie vers l'URL courante complète (filtres compris). */
function initLanguageLinks() {
  document.querySelectorAll("[data-lang-link]").forEach((link) => {
    link.addEventListener("click", () => {
      const url = new URL(link.href, window.location.origin);
      url.searchParams.set("next", window.location.pathname + window.location.search + window.location.hash);
      link.href = url.toString();
      document.dispatchEvent(new CustomEvent("languagechange"));
    });
  });
}

/** Boutons « Copier » : data-copy contient le texte à placer dans le presse-papiers. */
function initCopyButtons() {
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy]");
    if (!button) return;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      showToast(t("copied"), "success");
    } catch {
      showToast(t("copy_failed"), "danger");
    }
  });
}

export function initUI() {
  initCopyButtons();
  initFlashToasts();
  initDeleteModal();
  initSubmitSpinners();
  initLanguageLinks();
}
