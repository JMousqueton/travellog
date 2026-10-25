/* Aperçu de l'import : sélection rapide (tout, rien, par année) et nombre de trajets cochés. */

const form = document.getElementById("importPreview");
const boxes = [...form.querySelectorAll('input[name="rows"]')];
const yearOf = (box) => box.closest("tr").dataset.year;

function refresh() {
  document.getElementById("selectedCount").textContent = String(boxes.filter((box) => box.checked).length);
  form.querySelectorAll("[data-select-year]").forEach((button) => {
    const year = boxes.filter((box) => yearOf(box) === button.dataset.selectYear);
    button.setAttribute("aria-pressed", String(year.some((box) => box.checked)));
  });
}

form.addEventListener("change", refresh);
form.querySelectorAll("[data-select]").forEach((button) => button.addEventListener("click", () => {
  boxes.forEach((box) => { box.checked = button.dataset.select === "all"; });
  refresh();
}));
form.querySelectorAll("[data-select-year]").forEach((button) => button.addEventListener("click", () => {
  const year = boxes.filter((box) => yearOf(box) === button.dataset.selectYear);
  const check = !year.some((box) => box.checked);
  year.forEach((box) => { box.checked = check; });
  refresh();
}));
refresh();
