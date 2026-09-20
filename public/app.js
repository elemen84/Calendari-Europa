(() => {
  // Set this single value after creating the GitHub repository if an explicit URL is preferred.
  const PUBLIC_FEED_URL_OVERRIDE = "";
  const FEED_PATH = "europa.ics";
  const STANDINGS_PATH = "standings/primera-federacion-grupo-2-2026-2027.json";

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
  const standingsTable = document.querySelector("#standings-table");
  const standingsBody = document.querySelector("#standings-body");
  const standingsStatus = document.querySelector("#standings-status");

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

  const standingsValue = (row, field) => {
    const value = row[field];
    return value === null || value === undefined ? "—" : String(value);
  };

  const loadStandings = async () => {
    if (!standingsTable || !standingsBody) return;
    try {
      const response = await fetch(new URL(STANDINGS_PATH, window.location.href), { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.rows)) throw new Error("Resposta invàlida");

      standingsBody.replaceChildren();
      payload.rows.forEach((row) => {
        const tr = document.createElement("tr");
        ["position", "team", "played", "won", "drawn", "lost", "goal_difference", "points"].forEach((field) => {
          const cell = document.createElement("td");
          cell.textContent = standingsValue(row, field);
          if (field === "team") cell.className = "standing-team";
          tr.appendChild(cell);
        });
        standingsBody.appendChild(tr);
      });

      if (standingsStatus) {
        const retrieved = payload.retrieved_at ? new Date(payload.retrieved_at) : null;
        const date = retrieved && !Number.isNaN(retrieved.getTime())
          ? retrieved.toLocaleDateString("ca-ES")
          : null;
        standingsStatus.textContent = date
          ? `Actualitzada el ${date} · Font oficial RFEF.`
          : "Font oficial RFEF.";
      }
    } catch (_error) {
      standingsTable.hidden = true;
      if (standingsStatus) standingsStatus.textContent = "Classificació temporalment no disponible.";
    }
  };

  loadStandings();
})();
