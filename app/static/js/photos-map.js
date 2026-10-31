// Mes photos : chaque photo localisée en vignette sur la carte, regroupées quand elles sont proches.
import { escapeHtml, t } from "./i18n.js";
import { currentTheme } from "./theme.js";
import { PhotoGlobe } from "./photo-globe.js";

const element = document.getElementById("photosMap");
const data = JSON.parse(document.getElementById("photosData")?.textContent || "null");
if (element && data && window.L) {
  const tiles = JSON.parse(element.dataset.tiles);
  const map = L.map(element, { worldCopyJump: true });
  const layer = L.tileLayer(tiles.light, {
    attribution: [`&copy; <a href="https://www.openstreetmap.org/copyright">${escapeHtml(t("osm_contributors"))}</a>`,
      tiles.attribution].filter(Boolean).join(" "),
    subdomains: tiles.subdomains,
    maxZoom: tiles.maxZoom,
  }).addTo(map);

  const thumbIcon = (src, count) => L.divIcon({
    className: "photo-pin",
    html: `<img src="${escapeHtml(src)}" alt="" loading="lazy">${count ? `<span class="photo-pin-count">${count}</span>` : ""}`,
    iconSize: [52, 52],
    iconAnchor: [26, 26],
    popupAnchor: [0, -24],
  });

  // Groupe : vignette de la première photo et nombre de photos.
  const cluster = L.markerClusterGroup({
    maxClusterRadius: 56,
    showCoverageOnHover: false,
    iconCreateFunction: (group) => {
      const markers = group.getAllChildMarkers();
      return thumbIcon(markers[0].options.photo.thumb, markers.length);
    },
  });

  const popup = (photo) => `
    <div class="photo-popup">
      <a href="${escapeHtml(photo.url)}"><img src="${escapeHtml(photo.thumb)}" alt="" width="240" height="240"></a>
      <div class="photo-popup-body">
        <a class="fw-semibold d-block text-truncate" href="${escapeHtml(photo.owner_url)}">${escapeHtml(photo.label)}</a>
        ${photo.taken ? `<span class="small text-body-secondary"><i class="fa-regular fa-calendar me-1" aria-hidden="true"></i>${escapeHtml(photo.taken)}</span>` : ""}
        <a class="btn btn-primary btn-sm rounded-pill w-100 mt-2" href="${escapeHtml(photo.url)}">
          <i class="fa-solid fa-image me-1" aria-hidden="true"></i>${escapeHtml(data.strings.open)}</a>
      </div>
    </div>`;

  const bounds = [];
  for (const photo of data.photos) {
    const marker = L.marker([photo.lat, photo.lon], { icon: thumbIcon(photo.thumb), photo, title: photo.label });
    marker.bindPopup(popup(photo), { minWidth: 240, maxWidth: 240, className: "photo-popup-wrap" });
    cluster.addLayer(marker);
    bounds.push([photo.lat, photo.lon]);
  }
  map.addLayer(cluster);
  if (bounds.length === 1) map.setView(bounds[0], 13);
  else map.fitBounds(bounds, { padding: [48, 48], maxZoom: 14 });

  // Globe : mêmes photos, vue choisie par le sélecteur Carte / Globe (retenue dans le navigateur).
  const globe = window.d3 ? new PhotoGlobe(element.parentElement, {
    theme: currentTheme(), worldUrl: element.dataset.worldUrl, popup,
  }) : null;
  globe?.setPhotos(data.photos);

  const applyTheme = (theme) => {
    const url = (theme === "dark" && tiles.dark) || tiles.light;
    if (layer._url !== url) layer.setUrl(url);
    element.classList.toggle("tiles-filter-dark", theme === "dark" && !tiles.dark);
    globe?.setTheme(theme);
  };
  applyTheme(currentTheme());
  document.addEventListener("themechange", (event) => applyTheme(event.detail.theme));

  if (globe) {
    const VIEW_PREF = "photos:view";
    const viewSwitch = document.createElement("div");
    viewSwitch.className = "view-switch shadow-sm";
    viewSwitch.setAttribute("role", "group");
    viewSwitch.setAttribute("aria-label", t("view_choice"));
    viewSwitch.innerHTML = [["map", "fa-map", t("view_map")], ["globe", "fa-earth-americas", t("view_globe")]]
      .map(([value, icon, label]) => `<button type="button" data-view="${value}" aria-pressed="${value === "map"}">
        <i class="fa-solid ${icon}" aria-hidden="true"></i><span>${escapeHtml(label)}</span></button>`).join("");
    element.parentElement.append(viewSwitch);

    const setView = (name, save = true) => {
      const toGlobe = name === "globe";
      if (toGlobe === globe.visible) return;
      map.closePopup();
      if (toGlobe) {
        element.style.visibility = "hidden";
        globe.show().then(() => globe.fitAll());
      } else {
        globe.hide();
        element.style.visibility = "";
        map.invalidateSize();
      }
      viewSwitch.querySelectorAll("[data-view]").forEach((button) => {
        button.setAttribute("aria-pressed", String(button.dataset.view === name));
      });
      if (save) {
        try { localStorage.setItem(VIEW_PREF, name); } catch { /* stockage indisponible */ }
      }
    };
    viewSwitch.addEventListener("click", (event) => {
      const button = event.target.closest("[data-view]");
      if (button) setView(button.dataset.view);
    });
    let saved = "map";
    try { saved = localStorage.getItem(VIEW_PREF) || "map"; } catch { /* stockage indisponible */ }
    if (saved === "globe") setView("globe", false);
  }
}
