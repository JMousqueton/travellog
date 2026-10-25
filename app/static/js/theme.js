import { t } from "./i18n.js";
import { csrfToken, showToast } from "./ui.js";

const root = document.documentElement;
const media = window.matchMedia("(prefers-color-scheme: dark)");

export const currentTheme = () => root.getAttribute("data-bs-theme") || "light";

function storedTheme() {
  try { return localStorage.getItem("theme"); } catch { return null; }
}

function apply(theme) {
  root.setAttribute("data-bs-theme", theme);
  const button = document.getElementById("themeToggle");
  if (button) {
    button.setAttribute("aria-pressed", String(theme === "dark"));
    button.setAttribute("aria-label", theme === "dark" ? t("theme_light") : t("theme_dark"));
    button.title = button.getAttribute("aria-label");
  }
  document.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
}

export function initTheme() {
  apply(currentTheme());
  // Suit le système tant qu'aucun choix explicite n'a été fait.
  media.addEventListener("change", (event) => {
    if (!root.dataset.themePref && !storedTheme()) apply(event.matches ? "dark" : "light");
  });
  document.getElementById("themeToggle")?.addEventListener("click", async () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    try { localStorage.setItem("theme", next); } catch { /* stockage indisponible */ }
    if (root.dataset.themePref) root.dataset.themePref = next;
    apply(next);
    if (document.body.dataset.authenticated === "true") {
      try {
        const response = await fetch("/theme", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
          body: JSON.stringify({ theme: next }),
        });
        if (!response.ok) throw new Error(response.statusText);
        root.dataset.themePref = next;
      } catch {
        showToast(t("theme_saved_error"), "warning");
      }
    }
  });
}
