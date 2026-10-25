import { escapeHtml, locale, t } from "./i18n.js";

const DEBOUNCE_MS = 450;
const MIN_CHARS = 3;

/** Champ de lieu avec suggestions (modèle combobox ARIA 1.2). */
export class PlaceAutocomplete {
  /**
   * @param root élément [data-autocomplete] (data-lat, data-lon, data-country : sélecteurs des champs cachés)
   * @param scope formulaire portant data-geocode-url
   * @param onEdit appelé avec le champ quand sa valeur change (par ex. pour effacer une erreur)
   */
  constructor(root, { scope, onEdit = () => {} }) {
    this.root = root;
    this.scope = scope;
    this.onEdit = onEdit;
    this.input = root.querySelector('[role="combobox"]');
    this.list = root.querySelector('[role="listbox"]');
    this.status = root.querySelector('[role="status"]');
    this.spinner = root.querySelector(".input-spinner");
    this.check = root.querySelector(".input-check");
    this.lat = scope.querySelector(root.dataset.lat);
    this.lon = scope.querySelector(root.dataset.lon);
    this.country = scope.querySelector(root.dataset.country);
    this.results = [];
    this.active = -1;
    this.cache = new Map();

    this.input.addEventListener("input", () => this.onInput());
    this.input.addEventListener("keydown", (e) => this.onKeydown(e));
    this.input.addEventListener("blur", () => setTimeout(() => this.close(), 120));
    this.list.addEventListener("mousedown", (e) => e.preventDefault());
    this.list.addEventListener("click", (e) => {
      const option = e.target.closest('[role="option"]');
      if (option) this.select(Number(option.dataset.index));
    });
  }

  get hasCoords() {
    return this.lat.value !== "" && this.lon.value !== "";
  }

  setCoords(lat, lon, country = null) {
    this.lat.value = lat ?? "";
    this.lon.value = lon ?? "";
    // Sans code pays, le serveur le déduit des coordonnées.
    if (this.country) this.country.value = country ?? "";
    this.check.hidden = !this.hasCoords;
  }

  onInput() {
    this.setCoords(null, null);
    this.onEdit(this.input);
    clearTimeout(this.timer);
    const query = this.input.value.trim();
    if (query.length < MIN_CHARS) {
      this.close();
      this.status.textContent = query ? t("search_hint") : "";
      return;
    }
    this.timer = setTimeout(() => this.search(query), DEBOUNCE_MS);
  }

  async search(query) {
    const key = query.toLowerCase();
    if (this.cache.has(key)) return this.render(this.cache.get(key));
    this.controller?.abort();
    this.controller = new AbortController();
    this.spinner.hidden = false;
    this.status.textContent = t("search_searching");
    try {
      const url = `${this.scope.dataset.geocodeUrl}?${new URLSearchParams({ q: query, lang: locale })}`;
      const response = await fetch(url, { signal: this.controller.signal, headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(String(response.status));
      const { results } = await response.json();
      this.cache.set(key, results);
      if (this.input.value.trim() === query) this.render(results);
    } catch (error) {
      if (error.name !== "AbortError") this.renderMessage(t("search_error"));
    } finally {
      this.spinner.hidden = true;
    }
  }

  render(results) {
    this.results = results;
    this.active = -1;
    if (!results.length) return this.renderMessage(t("search_no_results"));
    this.list.innerHTML = results.map((r, i) => `
      <li role="option" id="${this.list.id}-opt-${i}" data-index="${i}" aria-selected="false">
        <i class="fa-solid fa-location-dot mt-1 text-body-secondary" aria-hidden="true"></i>
        <span><span class="ac-name">${escapeHtml(r.name)}</span><span class="ac-label">${escapeHtml(r.label)}</span></span>
      </li>`).join("");
    this.status.textContent = t("search_results", { count: results.length });
    this.open();
  }

  renderMessage(message) {
    this.results = [];
    this.list.innerHTML = `<li class="ac-empty" aria-disabled="true">${escapeHtml(message)}</li>`;
    this.status.textContent = message;
    this.open();
  }

  open() {
    this.list.hidden = false;
    this.input.setAttribute("aria-expanded", "true");
  }

  close() {
    this.list.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
    this.input.removeAttribute("aria-activedescendant");
    this.active = -1;
  }

  highlight(index) {
    const options = [...this.list.querySelectorAll('[role="option"]')];
    if (!options.length) return;
    this.active = (index + options.length) % options.length;
    options.forEach((o, i) => o.setAttribute("aria-selected", String(i === this.active)));
    const current = options[this.active];
    this.input.setAttribute("aria-activedescendant", current.id);
    current.scrollIntoView({ block: "nearest" });
  }

  select(index) {
    const result = this.results[index];
    if (!result) return;
    this.input.value = result.name;
    this.setCoords(result.lat, result.lon, result.country_code);
    this.onEdit(this.input);
    this.status.textContent = result.label;
    this.close();
  }

  onKeydown(event) {
    const isOpen = !this.list.hidden;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        if (!isOpen && this.results.length) this.open();
        this.highlight(this.active + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        this.highlight(this.active - 1);
        break;
      case "Enter":
        if (isOpen && this.active >= 0) {
          event.preventDefault();
          this.select(this.active);
        }
        break;
      case "Escape":
        if (isOpen) {
          event.preventDefault();
          this.close();
        }
        break;
      default:
    }
  }

  snapshot() {
    return { name: this.input.value, lat: this.lat.value, lon: this.lon.value, country: this.country?.value ?? "" };
  }

  restore({ name, lat, lon, country }) {
    this.input.value = name;
    this.setCoords(lat === "" ? null : lat, lon === "" ? null : lon, country || null);
  }
}
