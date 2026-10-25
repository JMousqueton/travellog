import { showToast } from "./ui.js";
import { t } from "./i18n.js";

/** Bouton « Partager » : partage le fichier PNG via la feuille de partage du système (mobile surtout). */
const button = document.querySelector("[data-share-image]");

async function imageFile() {
  const response = await fetch(button.dataset.shareImage);
  if (!response.ok) throw new Error(String(response.status));
  const blob = await response.blob();
  const name = new URL(button.dataset.shareImage, window.location.href).pathname.split("/").pop();
  return new File([blob], name.endsWith(".png") ? name : "review.png", { type: "image/png" });
}

if (button && navigator.canShare) {
  const probe = new File([new Blob()], "probe.png", { type: "image/png" });
  if (navigator.canShare({ files: [probe] })) {
    button.hidden = false;
    button.addEventListener("click", async () => {
      try {
        await navigator.share({ files: [await imageFile()], title: button.dataset.shareTitle });
      } catch (error) {
        if (error.name !== "AbortError") showToast(t("share_failed"), "danger");
      }
    });
  }
}
