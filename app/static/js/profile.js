import { PlaceAutocomplete } from "./place-autocomplete.js";

// Recherche de lieu pour le domicile (même composant que le formulaire de trajet).
const homeForm = document.getElementById("homeForm");
homeForm?.querySelectorAll("[data-autocomplete]").forEach((el) => {
  new PlaceAutocomplete(el, {
    scope: homeForm,
    onEdit: (input) => {
      input.classList.remove("is-invalid");
      document.getElementById("home-error").classList.remove("d-block");
    },
  });
});
