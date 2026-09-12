(() => {
  // Set this single value after creating the GitHub repository if an explicit URL is preferred.
  const PUBLIC_FEED_URL_OVERRIDE = "";
  const FEED_PATH = "europa.ics";

  const feedUrl = () => {
    if (PUBLIC_FEED_URL_OVERRIDE) return PUBLIC_FEED_URL_OVERRIDE;
    return new URL(FEED_PATH, window.location.href).href;
  };

  const webcalUrl = (httpsUrl) => {
    return httpsUrl.replace(/^https?:/i, "webcal:");
  };

  const modal = document.querySelector("#subscription-modal");
  const url = feedUrl();
  const urlElement = document.querySelector("#feed-url");
  const copyButton = document.querySelector("#copy-feed");
  const feedback = document.querySelector("#copy-feedback");
  const appleLink = document.querySelector("#apple-link");

  if (urlElement) urlElement.textContent = url;
  if (appleLink) appleLink.href = webcalUrl(url);

  const openModal = () => {
    if (modal && typeof modal.showModal === "function") modal.showModal();
    else if (modal) modal.setAttribute("open", "");
  };
  const closeModal = () => {
    if (modal && typeof modal.close === "function") modal.close();
    else if (modal) modal.removeAttribute("open");
  };

  document.querySelectorAll("[data-open-subscription]").forEach((button) => button.addEventListener("click", openModal));
  document.querySelectorAll("[data-close-subscription]").forEach((button) => button.addEventListener("click", closeModal));
  if (modal) modal.addEventListener("click", (event) => { if (event.target === modal) closeModal(); });

  if (copyButton) {
    copyButton.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(url);
        if (feedback) feedback.textContent = "Enllaç copiat.";
      } catch (_error) {
        if (feedback) feedback.textContent = "Selecciona i copia l'enllaç manualment.";
      }
    });
  }
})();
