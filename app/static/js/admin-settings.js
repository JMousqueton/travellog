// Paramètres d'administration : confirmation avant de rendre toutes les fonctions gratuites.
const form = document.getElementById("settingsForm");
const freeMode = document.getElementById("free_mode");
const modalEl = document.getElementById("freeModeModal");

if (form && freeMode && modalEl) {
  const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
  let confirmed = false;

  form.addEventListener("submit", (event) => {
    // Seulement quand on passe de désactivé à activé.
    if (confirmed || !freeMode.checked || freeMode.dataset.wasOn === "1") return;
    event.preventDefault();
    modal.show();
  });

  document.getElementById("freeModeConfirm").addEventListener("click", () => {
    confirmed = true;
    modal.hide();
    form.requestSubmit();
  });
}
