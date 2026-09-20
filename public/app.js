(() => {
  // Set this single value after creating the GitHub repository if an explicit URL is preferred.
  const PUBLIC_FEED_URL_OVERRIDE = "";
  const FEED_PATH = "europa.ics";
  const STANDINGS_PATH = "standings/primera-federacion-grupo-2-2026-2027.json";

  const pageBaseUrl = () => {
    const base = new URL(window.location.href);
    let path = base.pathname;
    // Keep assets under the project page directory on GitHub Pages.
    if (path.endsWith("/index.html")) path = path.slice(0, -"index.html".length);
    else if (!path.endsWith("/")) path = `${path}/`;
    base.pathname = path;
    return base;
  };

  const feedUrl = () => {
    if (PUBLIC_FEED_URL_OVERRIDE) return PUBLIC_FEED_URL_OVERRIDE;
    return new URL(FEED_PATH, pageBaseUrl()).href;
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

  const standingsSubtitle = (payload) => {
    const competition = typeof payload.competition === "string" ? payload.competition.trim() : "";
    const group = typeof payload.group === "string"
      ? payload.group.trim().replace(/^Grupo\b/i, "Grup")
      : "";
    if (competition && group) return `${competition} · ${group}`;
    if (competition) return competition;
    if (group) return group;
    return "Font oficial RFEF.";
  };

  const loadStandings = async () => {
    if (!standingsTable || !standingsBody) return;
    try {
      const response = await fetch(new URL(STANDINGS_PATH, pageBaseUrl()), { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.rows)) throw new Error("Resposta invàlida");

      const rows = document.createDocumentFragment();
      payload.rows.forEach((row) => {
        const tr = document.createElement("tr");
        if (row.team === "CE Europa") tr.className = "is-europa";
        ["position", "team", "played", "won", "drawn", "lost", "goal_difference", "points"].forEach((field) => {
          const cell = document.createElement("td");
          cell.textContent = standingsValue(row, field);
          if (field === "team") cell.className = "standing-team";
          tr.appendChild(cell);
        });
        rows.appendChild(tr);
      });
      standingsBody.replaceChildren(rows);

      if (standingsStatus) standingsStatus.textContent = standingsSubtitle(payload);
    } catch (_error) {
      standingsTable.hidden = true;
      if (standingsStatus) standingsStatus.textContent = "Classificació temporalment no disponible.";
    }
  };

  loadStandings();
})();
