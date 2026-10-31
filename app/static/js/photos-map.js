// Mes photos : chaque photo localisée en vignette sur la carte, regroupées quand elles sont proches.
import { escapeHtml, t } from "./i18n.js";
import { currentTheme } from "./theme.js";

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

  const applyTheme = (theme) => {
    const url = (theme === "dark" && tiles.dark) || tiles.light;
    if (layer._url !== url) layer.setUrl(url);
    element.classList.toggle("tiles-filter-dark", theme === "dark" && !tiles.dark);
  };
  applyTheme(currentTheme());
  document.addEventListener("themechange", (event) => applyTheme(event.detail.theme));
}
