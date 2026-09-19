(() => {
  // Set this single value after creating the GitHub repository if an explicit URL is preferred.
  const PUBLIC_FEED_URL_OVERRIDE = "";
  const FEED_PATH = "europa.ics";
  const STANDINGS_PATH = "./standings/primera-federacion-grupo-2-2026-2027.json";

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
  const standingsStatus = document.querySelector("#standings-status");
  const standingsTable = document.querySelector("#standings-table-wrap");
  const standingsBody = document.querySelector("#standings-body");

  if (urlElement) urlElement.textContent = url;
  if (appleLink) appleLink.href = webcalUrl(url);

  const isInteger = (value) => Number.isInteger(value);
  const validStandings = (payload) => {
    if (!payload || !Array.isArray(payload.rows) || payload.rows.length !== 20) return false;
    const positions = payload.rows.map((row) => row && row.position);
    return payload.rows.every((row) => (
      row && typeof row.team === "string" && row.team.trim() &&
      isInteger(row.position) && isInteger(row.played) && isInteger(row.points) &&
      isInteger(row.won) && isInteger(row.drawn) && isInteger(row.lost) &&
      isInteger(row.goals_for) && isInteger(row.goals_against) &&
      isInteger(row.goal_difference)
    )) && new Set(positions).size === 20 && positions.every((position) => position >= 1 && position <= 20);
  };
  const formatGoalDifference = (value) => (value > 0 ? `+${value}` : `${value}`);
  const normaliseTeam = (value) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

  const renderStandings = (payload) => {
    if (!standingsBody || !standingsTable || !standingsStatus) return;
    standingsBody.replaceChildren();
    payload.rows.forEach((row) => {
      const tableRow = document.createElement("tr");
      if (normaliseTeam(row.team).includes("europa")) tableRow.className = "standings-row-europa";
      [
        row.position,
        row.team,
        row.played,
        row.won,
        row.drawn,
        row.lost,
        row.goals_for,
        row.goals_against,
        formatGoalDifference(row.goal_difference),
        row.points,
      ].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = String(value);
        tableRow.appendChild(cell);
      });
      standingsBody.appendChild(tableRow);
    });
    standingsStatus.hidden = true;
    standingsTable.hidden = false;
  };

  const loadStandings = async () => {
    if (!standingsStatus || !standingsTable) return;
    try {
      const response = await fetch(STANDINGS_PATH, { cache: "no-store" });
      if (!response.ok) throw new Error("No s'ha pogut carregar la classificació");
      const payload = await response.json();
      if (!validStandings(payload)) throw new Error("Classificació invàlida");
      renderStandings(payload);
    } catch (_error) {
      standingsTable.hidden = true;
      standingsStatus.hidden = false;
      standingsStatus.textContent = "Classificació no disponible.";
    }
  };

  void loadStandings();

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
