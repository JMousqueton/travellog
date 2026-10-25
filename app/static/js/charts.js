/* Graphiques des statistiques (Chart.js, chargé par la page).
 *
 * Chaque <canvas data-chart="id"> lit sa description dans <script type="application/json" id="id"> :
 *   { "type": "stacked", "labels": [...], "series": {"plane": [...], ...}, "unit": "km" | null }
 *   { "type": "doughnut", "series": {"plane": 1234, ...}, "unit": "km" }
 * Les couleurs sont celles des modes de transport, claires ou sombres selon le thème.
 */
import { locale, modes } from "./i18n.js";

const { Chart } = window;
const charts = [];
const isDark = () => document.documentElement.getAttribute("data-bs-theme") === "dark";
const cssVar = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
const colorOf = (mode) => (isDark() ? modes[mode].colorDark : modes[mode].color);
const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 0 });
const format = (value, unit) => (unit ? `${number.format(value)} ${unit}` : number.format(value));

function config(spec) {
  const text = cssVar("--text-muted", "#5b6475");
  const grid = cssVar("--border-soft", "rgba(15, 23, 42, .08)");
  const order = Object.keys(spec.series);
  const tooltip = { callbacks: { label: (item) => ` ${item.dataset.label || item.label} : ${format(item.raw, spec.unit)}` } };
  if (spec.type === "doughnut") {
    return {
      type: "doughnut",
      data: {
        labels: order.map((mode) => modes[mode].label),
        datasets: [{ data: order.map((mode) => spec.series[mode]), backgroundColor: order.map(colorOf), borderWidth: 0 }],
      },
      options: {
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: { legend: { position: "bottom", labels: { color: text, boxWidth: 12 } }, tooltip },
      },
    };
  }
  return {
    type: "bar",
    data: {
      labels: spec.labels,
      datasets: order.map((mode) => ({
        label: modes[mode].label, data: spec.series[mode], backgroundColor: colorOf(mode), borderRadius: 4,
      })),
    },
    options: {
      maintainAspectRatio: false,
      scales: {
        x: { stacked: true, ticks: { color: text }, grid: { display: false } },
        y: { stacked: true, beginAtZero: true, ticks: { color: text, precision: 0, callback: (v) => format(v, spec.unit) },
             grid: { color: grid } },
      },
      plugins: { legend: { position: "bottom", labels: { color: text, boxWidth: 12 } }, tooltip },
    },
  };
}

function drawAll() {
  charts.splice(0).forEach((chart) => chart.destroy());
  document.querySelectorAll("canvas[data-chart]").forEach((canvas) => {
    const source = document.getElementById(canvas.dataset.chart);
    if (source) charts.push(new Chart(canvas, config(JSON.parse(source.textContent))));
  });
}

if (Chart) {
  drawAll();
  // Changement de thème : couleurs des modes et du texte à jour.
  new MutationObserver(drawAll).observe(document.documentElement, { attributes: true, attributeFilter: ["data-bs-theme"] });
}
