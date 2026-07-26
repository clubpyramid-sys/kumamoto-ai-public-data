(() => {
  "use strict";

  const POSTS_PER_ACCOUNT = 6;
  const CACHE_WINDOW_MS = 5 * 60 * 1000;
  const REQUEST_TIMEOUT_MS = 12000;
  const ACCOUNT_ORDER = [
    "club_kumamoto",
    "kumamonsupport",
    "kumamoto_luna",
    "k_ero_gentleman",
  ];
  const ALLOWED_HANDLES = new Set(ACCOUNT_ORDER);
  const X_HOSTS = new Set(["x.com", "www.x.com", "twitter.com", "www.twitter.com"]);
  const MEDIA_HOSTS = new Set(["pbs.twimg.com", "video.twimg.com"]);

  const textValue = (value, fallback = "") => {
    const text = String(value ?? "")
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "")
      .replace(/\r\n?/g, "\n")
      .trim();
    return text || fallback;
  };

  const normalizedHandle = (value) => textValue(value).replace(/^@/, "").toLowerCase();

  const displayHandle = (value) => {
    const handle = normalizedHandle(value);
    return handle === "k_ero_gentleman" ? "K_Ero_Gentleman" : handle;
  };

  const validDate = (value) => {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  };

  const formatJst = (value) => {
    const date = validDate(value);
    if (!date) return "";
    return new Intl.DateTimeFormat("ja-JP", {
      timeZone: "Asia/Tokyo",
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  };

  const safeUrl = (value, allowedHosts, fallback = "") => {
    try {
      const url = new URL(String(value || ""), window.location.href);
      return url.protocol === "https:" && allowedHosts.has(url.hostname.toLowerCase()) ? url.href : fallback;
    } catch (_) {
      return fallback;
    }
  };

  const profileUrl = (handle) => `https://x.com/${handle}`;
  const safeXUrl = (value, handle) => safeUrl(value, X_HOSTS, profileUrl(handle));
  const safeMediaUrl = (value) => safeUrl(value, MEDIA_HOSTS, "");

  const makeExternalLink = (href, label, className = "") => {
    const link = document.createElement("a");
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = label;
    if (className) link.className = className;
    return link;
  };

  const appendLinkedText = (container, value) => {
    const text = textValue(value);
    const tokenPattern = /(https?:\/\/[^\s]+|@[A-Za-z0-9_]{1,15}|#[\p{L}\p{N}_ー]+)/gu;
    let cursor = 0;

    for (const match of text.matchAll(tokenPattern)) {
      const index = match.index ?? 0;
      if (index > cursor) container.append(document.createTextNode(text.slice(cursor, index)));

      const token = match[0];
      if (token.startsWith("http")) {
        const trailing = token.match(/[。、，．.!?！？)）\]]+$/u)?.[0] || "";
        const rawUrl = trailing ? token.slice(0, -trailing.length) : token;
        try {
          const url = new URL(rawUrl);
          if (url.protocol === "https:" || url.protocol === "http:") {
            container.append(makeExternalLink(url.href, rawUrl));
          } else {
            container.append(document.createTextNode(rawUrl));
          }
        } catch (_) {
          container.append(document.createTextNode(rawUrl));
        }
        if (trailing) container.append(document.createTextNode(trailing));
      } else if (token.startsWith("@")) {
        container.append(makeExternalLink(profileUrl(token.slice(1)), token));
      } else {
        container.append(makeExternalLink(`https://x.com/hashtag/${encodeURIComponent(token.slice(1))}`, token));
      }
      cursor = index + token.length;
    }

    if (cursor < text.length) container.append(document.createTextNode(text.slice(cursor)));
  };

  const firstMedia = (item) => {
    if (!Array.isArray(item?.media)) return null;
    for (const entry of item.media) {
      const url = safeMediaUrl(entry?.url);
      if (!url) continue;
      const type = textValue(entry?.type, "image").toLowerCase();
      const imageLike = ["image", "photo", "thumbnail"].includes(type)
        || url.includes("pbs.twimg.com")
        || /\.(?:avif|gif|jpe?g|png|webp)(?:\?|$)/i.test(url);
      return { type, url, imageLike };
    }
    return null;
  };

  const makePostCard = (item, expectedHandle) => {
    const handle = displayHandle(item.handle) || displayHandle(expectedHandle);
    const displayName = textValue(item.display_name, `@${handle}`);
    const postUrl = safeXUrl(item.url, handle);
    const publishedAt = validDate(item.published_at);
    const media = firstMedia(item);

    const card = document.createElement("article");
    card.className = "post-card";

    const body = document.createElement("div");
    body.className = "post-card__body";

    const identity = document.createElement("div");
    identity.className = "post-card__identity";
    const mark = document.createElement("span");
    mark.className = "post-card__mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = "X";
    const account = document.createElement("div");
    const name = document.createElement("strong");
    name.className = "post-card__name";
    name.textContent = displayName;
    account.append(name, makeExternalLink(profileUrl(handle), `@${handle}`, "post-card__handle"));
    identity.append(mark, account);
    body.append(identity);

    if (publishedAt) {
      const time = document.createElement("time");
      time.dateTime = publishedAt.toISOString();
      time.textContent = formatJst(publishedAt);
      body.append(time);
    }

    if (item.is_repost || item.is_reply || (media && !media.imageLike)) {
      const flags = document.createElement("p");
      flags.className = "post-card__flags";
      flags.textContent = item.is_repost ? "リポスト" : item.is_reply ? "返信" : "動画付き投稿";
      body.append(flags);
    }

    const postText = document.createElement("p");
    postText.className = "post-card__text";
    appendLinkedText(postText, item.text || item.title || "最新情報は元のX投稿をご確認ください。");
    body.append(postText, makeExternalLink(postUrl, "Xで見る", "post-card__source"));
    card.append(body);

    if (media?.imageLike) {
      const mediaLink = makeExternalLink(postUrl, "", "post-card__media");
      mediaLink.setAttribute("aria-label", `${displayName}の画像付きX投稿を見る`);
      const image = document.createElement("img");
      image.src = media.url;
      image.alt = `${displayName}のX投稿に添付された画像`;
      image.loading = "lazy";
      image.decoding = "async";
      image.addEventListener("error", () => mediaLink.remove(), { once: true });
      mediaLink.append(image);
      card.append(mediaLink);
    }

    return card;
  };

  const showColumnError = (column, handle) => {
    const feed = column.querySelector("[data-account-feed]");
    if (!feed) return;
    const message = document.createElement("p");
    message.className = "account-feed__error";
    message.append("現在、このアカウントの最新投稿を取得できませんでした。", document.createElement("br"));
    message.append(makeExternalLink(profileUrl(handle), "Xで直接ご確認ください。"));
    feed.replaceChildren(message);
    feed.setAttribute("aria-busy", "false");
  };

  const renderColumn = (column, items) => {
    const handle = normalizedHandle(column.dataset.handle);
    const feed = column.querySelector("[data-account-feed]");
    if (!feed || !ALLOWED_HANDLES.has(handle)) return 0;

    const selected = items
      .filter((item) => normalizedHandle(item.handle) === handle)
      .sort((a, b) => validDate(b.published_at) - validDate(a.published_at))
      .slice(0, POSTS_PER_ACCOUNT);

    if (!selected.length) {
      showColumnError(column, displayHandle(handle));
      return 0;
    }

    feed.replaceChildren(...selected.map((item) => makePostCard(item, handle)));
    feed.setAttribute("aria-busy", "false");
    const latest = column.querySelector("[data-account-updated]");
    const latestText = formatJst(selected[0].published_at);
    if (latest && latestText) {
      latest.textContent = `最新投稿：${latestText}（日本時間）`;
      latest.dateTime = validDate(selected[0].published_at)?.toISOString() || "";
      latest.hidden = false;
    }
    return selected.length;
  };

  const load = async () => {
    const root = document.querySelector("[data-xhub-feed]");
    const status = document.querySelector("[data-xhub-status]");
    const updated = document.querySelector("[data-xhub-updated]");
    const columns = [...document.querySelectorAll("[data-account-column]")];
    if (!root || !status || !updated || columns.length !== ACCOUNT_ORDER.length) return;

    const source = textValue(root.dataset.feedUrl, "all_latest.json");
    const cacheKey = Math.floor(Date.now() / CACHE_WINDOW_MS);
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    root.setAttribute("aria-busy", "true");

    try {
      const response = await fetch(`${source}?v=${cacheKey}`, {
        cache: "no-store",
        credentials: "omit",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data || !Array.isArray(data.items)) throw new Error("Invalid feed schema");

      const seen = new Set();
      const items = data.items.filter((item) => {
        const handle = normalizedHandle(item?.handle);
        const key = `${handle}:${textValue(item?.id, textValue(item?.url))}`;
        if (!ALLOWED_HANDLES.has(handle) || !validDate(item?.published_at) || seen.has(key)) return false;
        seen.add(key);
        return true;
      });

      const counts = columns.map((column) => renderColumn(column, items));
      const total = counts.reduce((sum, count) => sum + count, 0);
      status.textContent = `4アカウント・合計${total}件を表示しています。`;
      const generatedAt = formatJst(data.generated_at);
      if (generatedAt) {
        updated.textContent = `公開データ更新：${generatedAt}（日本時間）`;
        updated.hidden = false;
      }
    } catch (error) {
      console.warn("[KSC X Hub] feed unavailable", error);
      columns.forEach((column) => showColumnError(column, displayHandle(column.dataset.handle)));
      status.textContent = "現在、最新投稿データを取得できませんでした。各アカウントのXリンクは引き続きご利用いただけます。";
    } finally {
      root.setAttribute("aria-busy", "false");
      window.clearTimeout(timeoutId);
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => load().catch((error) => console.warn("[KSC X Hub] unexpected error", error)), { once: true });
  } else {
    load().catch((error) => console.warn("[KSC X Hub] unexpected error", error));
  }
})();
