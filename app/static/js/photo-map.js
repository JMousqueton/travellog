// Mini-carte de la page d'une photo : le lieu de prise de vue relevé dans ses données GPS.
import { escapeHtml, t } from "./i18n.js";
import { currentTheme } from "./theme.js";

const element = document.getElementById("photoMap");
if (element && window.L) {
  const tiles = JSON.parse(element.dataset.tiles);
  const position = [Number(element.dataset.lat), Number(element.dataset.lon)];
  const map = L.map(element, { scrollWheelZoom: false }).setView(position, 14);
  const layer = L.tileLayer(tiles.light, {
    attribution: [`&copy; <a href="https://www.openstreetmap.org/copyright">${escapeHtml(t("osm_contributors"))}</a>`,
      tiles.attribution].filter(Boolean).join(" "),
    subdomains: tiles.subdomains,
    maxZoom: tiles.maxZoom,
  }).addTo(map);
  L.circleMarker(position, { radius: 8, weight: 3, color: "#fff", fillColor: "#2563eb", fillOpacity: 1 }).addTo(map);

  const applyTheme = (theme) => {
    const url = (theme === "dark" && tiles.dark) || tiles.light;
    if (layer._url !== url) layer.setUrl(url);
    element.classList.toggle("tiles-filter-dark", theme === "dark" && !tiles.dark);
  };
  applyTheme(currentTheme());
  document.addEventListener("themechange", (event) => applyTheme(event.detail.theme));
}
