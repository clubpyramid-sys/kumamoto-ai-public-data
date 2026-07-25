(() => {
  "use strict";

  const DEFAULT_FEED = "https://clubpyramid-sys.github.io/kumamoto-ai-public-data/x/all_latest.json";

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("ja-JP", {
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    }).format(date);
  }

  function renderItem(item) {
    const media = Array.isArray(item.media) && item.media.length
      ? `<img class="cnj-x-feed__image" src="${escapeHtml(item.media[0].url)}" alt="" loading="lazy">`
      : "";
    return `
      <article class="cnj-x-feed__card">
        <div class="cnj-x-feed__meta">
          <strong>${escapeHtml(item.display_name || item.handle)}</strong>
          <span>@${escapeHtml(item.handle)}</span>
          <time datetime="${escapeHtml(item.published_at)}">${escapeHtml(formatDate(item.published_at))}</time>
        </div>
        <p>${escapeHtml(item.text)}</p>
        ${media}
        <a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">Xで投稿を見る →</a>
      </article>`;
  }

  async function mount(container) {
    const feedUrl = container.dataset.feedUrl || DEFAULT_FEED;
    const limit = Math.max(1, Math.min(12, Number(container.dataset.limit || 6)));
    const handles = (container.dataset.handles || "")
      .split(",")
      .map(value => value.trim().replace(/^@/, "").toLowerCase())
      .filter(Boolean);

    try {
      const response = await fetch(`${feedUrl}?v=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      let items = Array.isArray(data.items) ? data.items : [];
      if (handles.length) {
        items = items.filter(item => handles.includes(String(item.handle || "").toLowerCase()));
      }
      items = items.slice(0, limit);
      if (!items.length) throw new Error("表示できる投稿がありません");
      container.innerHTML = items.map(renderItem).join("");
    } catch (error) {
      console.error("CNJ X feed error", error);
      container.innerHTML = '<p class="cnj-x-feed__error">最新情報はXをご覧ください。</p>';
    }
  }

  document.querySelectorAll("[data-cnj-x-feed]").forEach(mount);
})();
