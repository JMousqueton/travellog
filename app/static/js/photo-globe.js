// Globe de « Mes photos » : le globe de la carte (rotation, zoom, thèmes), avec les photos en vignettes
// à la place des trajets. Les photos proches à l'écran sont regroupées, avec leur nombre.
import { Globe } from "./globe.js";

const THUMB = 44;        // côté d'une vignette, en pixels
const GROUP_PX = 40;     // distance à l'écran sous laquelle deux photos sont regroupées

export class PhotoGlobe extends Globe {
  constructor(wrapper, { popup, ...options }) {
    super(wrapper, options);
    this.popup = popup;
    this.photos = [];
    this.groups = new Map();
    this.photoHits = [];
  }

  setPhotos(photos) {
    this.photos = photos.map((photo) => {
      const image = new Image();
      image.decoding = "async";
      image.onload = () => this.requestDraw();
      image.src = photo.thumb;
      return { ...photo, point: [photo.lon, photo.lat], image };
    });
    this.requestDraw();
  }

  draw() {
    super.draw();
    if (!this.visible || !this.width || !this.photos?.length) return;
    // Regroupement à l'écran : chaque photo visible rejoint le premier groupe assez proche.
    const groups = [];
    for (const photo of this.photos) {
      const xy = this.project(photo.point);
      if (!xy) continue;
      const near = groups.find((g) => Math.hypot(g.x - xy[0], g.y - xy[1]) < GROUP_PX);
      if (near) near.photos.push(photo);
      else groups.push({ x: xy[0], y: xy[1], photos: [photo] });
    }
    this.groups = new Map();
    this.photoHits = groups.map((group, index) => {
      const id = `g${index}`;
      this.groups.set(id, group);
      this.drawThumb(group);
      return { id, x: group.x, y: group.y, group };
    });
  }

  drawThumb({ x, y, photos }) {
    const { ctx } = this;
    const dark = this.theme === "dark";
    const left = x - THUMB / 2, top = y - THUMB / 2;
    ctx.save();
    ctx.shadowColor = "rgba(15, 23, 42, .45)";
    ctx.shadowBlur = 10;
    ctx.shadowOffsetY = 4;
    ctx.beginPath();
    ctx.roundRect(left - 3, top - 3, THUMB + 6, THUMB + 6, 12);
    ctx.fillStyle = dark ? "#e2e8f0" : "#ffffff";
    ctx.fill();
    ctx.restore();
    ctx.save();
    ctx.beginPath();
    ctx.roundRect(left, top, THUMB, THUMB, 9);
    ctx.clip();
    const image = photos[0].image;
    if (image.complete && image.naturalWidth) {
      const side = Math.min(image.naturalWidth, image.naturalHeight);
      ctx.drawImage(image, (image.naturalWidth - side) / 2, (image.naturalHeight - side) / 2, side, side,
        left, top, THUMB, THUMB);
    } else {
      ctx.fillStyle = dark ? "#334155" : "#e2e8f0";
      ctx.fillRect(left, top, THUMB, THUMB);
    }
    ctx.restore();
    if (photos.length > 1) {
      const label = String(photos.length);
      ctx.font = "700 12px Inter, system-ui, sans-serif";
      const w = Math.max(22, ctx.measureText(label).width + 12);
      const bx = left + THUMB + 3 - w / 2 - 2, by = top - 9;
      ctx.beginPath();
      ctx.roundRect(bx, by, w, 22, 11);
      ctx.fillStyle = dark ? "#818cf8" : "#4f46e5";
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#ffffff";
      ctx.stroke();
      ctx.fillStyle = "#ffffff";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, bx + w / 2, by + 11.5);
    }
  }

  hitTest(x, y) {
    let best = null, bestDistance = THUMB / 2 + 4;
    for (const hit of this.photoHits) {
      const distance = Math.max(Math.abs(hit.x - x), Math.abs(hit.y - y));
      if (distance < bestDistance) [best, bestDistance] = [hit, distance];
    }
    return best;
  }

  showTooltip(hit, x, y) {
    const { photos } = hit.group;
    this.tooltip.textContent = photos.length > 1
      ? `${photos.length} · ${[...new Set(photos.map((p) => p.label))].slice(0, 2).join(" · ")}`
      : [photos[0].label, photos[0].taken].filter(Boolean).join(" · ");
    this.tooltip.style.transform = `translate(${Math.round(x + 14)}px, ${Math.round(y + 14)}px)`;
    this.tooltip.hidden = false;
  }

  /** Clic : une photo s'ouvre dans la carte du globe ; un groupe rapproche le globe pour séparer ses photos. */
  select(id) {
    const group = this.groups.get(id);
    if (!group) return;
    this.stopSpin();
    this.hideCard();
    const center = d3.geoCentroid({ type: "MultiPoint", coordinates: group.photos.map((p) => p.point) });
    if (group.photos.length > 1) {
      this.flyTo(center, Math.min(this.zoom * 2.5, 12));
      return;
    }
    const [photo] = group.photos;
    this.selectedId = photo.id;
    this.flyTo(photo.point, Math.max(this.zoom, 2.5), () => {
      if (this.selectedId === photo.id) this.showPhotoCard(photo);
    });
  }

  showPhotoCard(photo) {
    this.card.querySelector("[data-globe-card-body]").innerHTML = this.popup(photo);
    this.card.classList.add("globe-card-photo");
    this.card.hidden = false;
  }

  fitAll() {
    if (!this.photos.length) return;
    const points = this.photos.map((p) => p.point);
    const centroid = d3.geoCentroid({ type: "MultiPoint", coordinates: points });
    const spread = Math.max(...points.map((p) => d3.geoDistance(centroid, p)));
    const zoom = Math.min(Math.max(1 / Math.max(Math.sin(Math.min(spread, Math.PI / 2)) * 1.15, 0.2), 1), 4);
    if (Number.isFinite(centroid[0])) this.flyTo(centroid, zoom);
  }
}
