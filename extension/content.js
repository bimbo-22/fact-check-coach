// Instagram feed helper: a local red-flag score on every post + an on-demand, guess-first fact-check.
// Privacy: the red-flag score is computed here in the browser. Nothing leaves the page until the user
// clicks "Fact-check this post", and then only that post's caption (and image address) is sent.
(() => {
  const DONE = "data-fcc";
  const YEAR = new Date().getFullYear();
  const CLAIMS = /\b(is|are|was|were|will|cause[sd]?|confirm(ed|s)?|prove[sd]?|found|shows?|study|report(s|ed)?|died|kill(s|ed)?|ban(ned)?|law|government|vaccines?|cures?|scientists|doctors|police|migrants?|election)\b|\d+ ?%|\b\d{2,}\b/i;
  const FLAGS = [
    { id: "nosource", label: "No source named", why: "It doesn't say where the information comes from.",
      // Only for posts that assert something: a sunset photo doesn't need a source.
      test: (t) => CLAIMS.test(t) && !/https?:\/\/(?!(www\.)?instagram\.com)|according to|source:|study (published|in)|reuters|associated press|\bap\b|bbc|afp|\bwho\b|cdc|nhs|ministry|university/i.test(t) },
    { id: "shock", label: "Built to shock", why: "ALL CAPS, “!!!” or emotional words push you to react before you think.",
      test: (t) => /!!!|\b(shocking|outrage|disgusting|terrifying|unbelievable|insane|horrifying)\b|😱|🤯|😡/i.test(t) || (t.match(/\b[A-Z]{4,}\b/g) || []).length >= 2 },
    { id: "urgency", label: "Pressure to share", why: "“Share before they delete this” is a classic misinformation tactic.",
      test: (t) => /share (this )?before|before (they|it gets) delete|they don'?t want you to know|wake up|spread the word|must (see|watch)|breaking/i.test(t) },
    { id: "bio", label: "“Link in bio”", why: "The evidence is hidden somewhere else. Check it before you trust it.",
      test: (t) => /link in (my )?bio/i.test(t) },
    { id: "miracle", label: "Too sure, too good", why: "Words like “cure”, “100%” or “scientists confirm” with no study named.",
      test: (t) => /\b(miracle|cures?|100 ?%|guaranteed|scientists (confirm|prove)|doctors (hate|don'?t want)|secret)\b/i.test(t) },
    { id: "hashtags", label: "Hashtag pile-on", why: "Lots of hashtags spread a post; they don't prove it.",
      test: (t) => (t.match(/(^|\s)#\w+/g) || []).length >= 4 },
    { id: "old", label: "Old date inside", why: "Old stories get reshared as if they're new.",
      test: (t) => (t.match(/\b(19[5-9]\d|20[0-4]\d)\b/g) || []).some((y) => Number(y) <= YEAR - 2) },
  ];

  let enabled = true;

  function captionOf(article) {
    // Instagram's markup changes often: the caption is the longest text block in the post.
    let best = "";
    for (const n of article.querySelectorAll("h1, span, div[dir='auto']")) {
      if (n.children.length > 3) continue;
      const t = (n.innerText || "").trim();
      if (t.length > best.length && t.length < 2200) best = t;
    }
    return best;
  }

  function imageOf(article) {
    const imgs = [...article.querySelectorAll("img")].filter((i) => /cdninstagram\.com|fbcdn\.net/.test(i.src));
    imgs.sort((a, b) => (b.width * b.height) - (a.width * a.height));
    return imgs[0] && imgs[0].width >= 150 ? imgs[0].src : null;
  }

  function scoreOf(text) {
    if (!text || text.length < 12) return null;
    return FLAGS.filter((f) => f.test(text));
  }

  function el(tag, text, cls) {
    const n = document.createElement(tag);
    if (text != null) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  }

  function send(type, payload) {
    return new Promise((resolve) => chrome.runtime.sendMessage({ type, ...payload }, resolve));
  }

  function badgeLevel(n) {
    if (n === 0) return ["fcc-ok", "🧭 No red flags spotted"];
    if (n <= 2) return ["fcc-some", `🚩 ${n} red flag${n > 1 ? "s" : ""}`];
    return ["fcc-many", `🚩 ${n} red flags`];
  }

  function attach(article) {
    if (article.hasAttribute(DONE)) return;
    const caption = captionOf(article);
    const flags = scoreOf(caption);
    if (!flags) return;
    article.setAttribute(DONE, "1");

    const host = el("div");
    host.className = "fcc-host";
    const root = host.attachShadow({ mode: "open" });
    const style = el("link");
    style.rel = "stylesheet";
    style.href = chrome.runtime.getURL("content.css");
    root.append(style);

    const [cls, text] = badgeLevel(flags.length);
    const badge = el("button", text, `fcc-badge ${cls}`);
    badge.title = "Warning signs in how this post is written. Not a verdict: tap to see them, or fact-check it.";
    const panel = el("div", null, "fcc-panel");
    panel.hidden = true;
    root.append(badge, panel);

    badge.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      panel.hidden = !panel.hidden;
      article.style.zIndex = panel.hidden ? "" : "10000"; // keep the open panel above the next post
      if (!panel.hidden && !panel.childElementCount) renderFlags(panel, flags, caption, imageOf(article));
    });
    article.style.position = article.style.position || "relative";
    article.prepend(host);
  }

  function renderFlags(panel, flags, caption, imageUrl) {
    panel.replaceChildren();
    panel.append(el("p", flags.length ? "Warning signs in how it's written" : "No obvious warning signs, which doesn't mean it's true.", "fcc-kicker"));
    if (flags.length) {
      const ul = el("ul", null, "fcc-flags");
      for (const f of flags) {
        const li = el("li");
        li.append(el("b", f.label), el("span", ` · ${f.why}`));
        ul.append(li);
      }
      panel.append(ul);
    }
    const go = el("button", "Fact-check this post", "fcc-btn");
    go.addEventListener("click", () => startCheck(panel, caption, imageUrl));
    panel.append(go, el("p", "Nothing is sent until you click. Only this post's text and image address.", "fcc-fine"));
  }

  async function startCheck(panel, caption, imageUrl) {
    panel.replaceChildren(el("p", "Checking the named outlets… (10–20 s)", "fcc-kicker"));
    const res = await send("fcc-start", { text: caption, image_url: imageUrl });
    panel.replaceChildren();
    if (!res || res.error) {
      panel.append(el("p", res && res.error ? res.error : "The checker isn't reachable. Is the API running?", "fcc-err"));
      return;
    }
    const p = res.data;
    if (p.needs_text || !p.check_id) { panel.append(el("p", p.note || "I couldn't read this post.")); return; }
    if (!p.checkable) { panel.append(el("p", `💬 ${p.note}`)); return; }
    panel.append(el("p", "The claim", "fcc-kicker"), el("p", p.claim, "fcc-claim"), el("p", `🤔 ${p.question}`, "fcc-q"),
      el("p", "Your guess first", "fcc-kicker"));
    const row = el("div", null, "fcc-guesses");
    for (const [g, label] of [["true", "True"], ["false", "False"], ["not_sure", "Not sure"]]) {
      const b = el("button", label, "fcc-guess");
      b.addEventListener("click", () => reveal(panel, p.check_id, g));
      row.append(b);
    }
    panel.append(row);
  }

  async function reveal(panel, checkId, guess) {
    const res = await send("fcc-reveal", { check_id: checkId, guess });
    panel.replaceChildren();
    if (!res || res.error) { panel.append(el("p", res?.error || "Something went wrong.", "fcc-err")); return; }
    const r = res.data;
    const V = { false: ["❌", "False"], true: ["✅", "True"], misleading: ["⚠️", "Misleading"],
      unverified: ["❓", "Unverified"], developing: ["⏳", "Still developing"], opinion: ["💬", "Opinion"] };
    const [emoji, label] = V[r.verdict] || ["•", r.verdict];
    const v = el("div", null, `fcc-verdict fcc-v-${r.verdict}`);
    v.append(el("b", `${emoji} ${label}`), el("span", ` · confidence ${r.confidence}`));
    panel.append(v);
    if (r.guess_feedback) panel.append(el("p", `🎯 ${r.guess_feedback}`, "fcc-feedback"));
    if (r.what_is_true) {
      const k = el("div", null, `fcc-known fcc-known-${r.what_is_true.kind}`);
      k.append(el("b", r.what_is_true.heading), el("p", r.what_is_true.text));
      panel.append(k);
    }
    panel.append(el("p", r.explanation));
    for (const s of r.sources.slice(0, 3)) {
      const a = el("a", s.outlet);
      a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer";
      const li = el("div", null, "fcc-src");
      li.append(a, el("span", ` · ${s.stance === "contradicts" ? "says it's false" : "backs it up"}`));
      if (s.quote) li.append(el("q", s.quote));
      panel.append(li);
    }
    panel.append(el("p", `💡 ${r.tip}`, "fcc-tip"), el("p", r.disclaimer, "fcc-fine"));
  }

  function scan() {
    if (!enabled) return;
    document.querySelectorAll("article").forEach(attach);
  }

  function removeAll() {
    document.querySelectorAll(".fcc-host").forEach((h) => h.remove());
    document.querySelectorAll(`[${DONE}]`).forEach((a) => a.removeAttribute(DONE));
  }

  chrome.storage.local.get("autoBadges").then((s) => {
    enabled = s.autoBadges !== false;
    scan();
  }).catch(scan);
  chrome.storage.onChanged.addListener((c) => {
    if (!c.autoBadges) return;
    enabled = c.autoBadges.newValue !== false;
    enabled ? scan() : removeAll();
  });
  let pending = null;
  new MutationObserver(() => {
    clearTimeout(pending);
    pending = setTimeout(scan, 400); // Instagram adds posts as you scroll
  }).observe(document.body, { childList: true, subtree: true });
})();
