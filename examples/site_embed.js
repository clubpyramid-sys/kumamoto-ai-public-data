/**
 * 利用例:
 * <div id="cnj-note-feed"></div>
 * <script src="/path/to/site_embed.js" defer></script>
 */
(() => {
  "use strict";
  const FEED_URL = "https://clubpyramid-sys.github.io/kumamoto-ai-public-data/sites/cosanostra.json";
  const FALLBACK = [
    { title: "最新情報はnoteでご覧ください", url: "https://note.com/club_pyramid/" }
  ];

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  }[char]));

  function render(items) {
    const root = document.getElementById("cnj-note-feed");
    if (!root) return;
    root.innerHTML = items.map((item) => `
      <article class="public-feed-card">
        ${item.thumbnail_url ? `<img src="${escapeHtml(item.thumbnail_url)}" alt="" loading="lazy">` : ""}
        <h3><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a></h3>
        ${item.summary ? `<p>${escapeHtml(item.summary)}</p>` : ""}
      </article>`).join("");
  }

  fetch(FEED_URL, { cache: "no-store" })
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => render(Array.isArray(data.note_items) && data.note_items.length ? data.note_items : FALLBACK))
    .catch(() => render(FALLBACK));
})();
