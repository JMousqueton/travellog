// Chaînes traduites injectées par le serveur (bloc #i18n-data) : aucun texte en dur ici.
const node = document.getElementById("i18n-data");
const data = node ? JSON.parse(node.textContent) : { locale: "fr", strings: {}, modes: {} };

export const locale = data.locale;
export const modes = data.modes;
/** Modes dans l'ordre défini côté serveur (le JSON injecté a ses clés triées). */
export const modeEntries = (data.modeOrder || Object.keys(modes)).map((key) => [key, modes[key]]);

/** Traduit une clé et remplace les variables %(nom)s. */
export function t(key, vars = {}) {
  const template = data.strings[key] ?? key;
  return template.replace(/%\((\w+)\)s/g, (_, name) => (name in vars ? String(vars[name]) : ""));
}

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}
