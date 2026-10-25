import { t } from "./i18n.js";
import { initTheme } from "./theme.js";
import { initUI, showToast } from "./ui.js";

initUI();
initTheme();

/* --- Hors ligne (service worker /sw.js) ---------------------------------- */

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => { /* hors ligne indisponible : sans conséquence */ });
}
if (document.body.dataset.authenticated === "false" && "caches" in window) {
  // Déconnecté (ou session expirée) : les pages du compte ne restent pas sur l'appareil.
  caches.delete("pages").catch(() => {});
}
window.addEventListener("offline", () => showToast(t("offline"), "warning"));
window.addEventListener("online", () => showToast(t("online"), "success"));
if (!navigator.onLine) showToast(t("offline"), "warning");
