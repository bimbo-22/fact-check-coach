// Fact-Check Coach popup: start → guess → reveal. All API data is rendered with textContent (no innerHTML).
const DEFAULT_API = "http://localhost:8000";
const IG_POST_RE = /^https?:\/\/(www\.|m\.)?instagram\.com\/([\w.]+\/)?(p|reel|reels|tv)\/[\w-]+/i;
const VERDICTS = {
  false: ["❌", "False"],
  true: ["✅", "True"],
  misleading: ["⚠️", "Misleading"],
  unverified: ["❓", "Unverified"],
  developing: ["⏳", "Still developing"],
  opinion: ["💬", "Opinion"],
};

const $ = (id) => document.getElementById(id);
let apiBase = DEFAULT_API;
let checkId = null;
let pendingUrl = null; // Instagram link waiting for a pasted caption

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function show(view) {
  for (const id of ["input-view", "start-view", "reveal-view"]) $(id).hidden = id !== view;
}

function status(msg) {
  $("status").textContent = msg || "";
}

async function api(path, body) {
  const r = await fetch(`${apiBase}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const err = new Error(`HTTP ${r.status}`);
    err.status = r.status;
    throw err;
  }
  return r.json();
}

async function startCheck(text, url) {
  status("Checking six outlets…");
  try {
    const p = await api("/check/start", { text: text || "", url: url || null, client: "extension" });
    status("");
    if (p.needs_text) {
      pendingUrl = url;
      show("input-view");
      status(p.note);
      $("post-text").focus();
      return;
    }
    pendingUrl = null;
    if (!p.checkable) {
      show("input-view");
      status(`💬 ${p.note}`);
      return;
    }
    checkId = p.check_id;
    $("claim").textContent = p.claim;
    $("question").textContent = `🤔 ${p.question}`;
    show("start-view");
  } catch (e) {
    status(e.status === 422 ? "Paste some text to check." : `Can't reach the checker at ${apiBase}. Is the API running?`);
  }
}

function agreementText(verdict, a) {
  const covering = a.supports + a.contradicts;
  if (covering === 0) return `None of the ${a.outlets_checked} outlets we checked cover it yet.`;
  const say = (n) => (n === 1 ? `${n} says` : `${n} say`);
  const head = `${covering} of ${a.outlets_checked} outlets checked cover it`;
  if ((verdict === "false" || verdict === "true") && Math.min(a.supports, a.contradicts) === 0) {
    return `${head}; ${covering > 1 ? "all " : ""}${say(covering)} it's ${verdict}.`;
  }
  return `${head}: ${say(a.contradicts)} it's false, ${say(a.supports)} it's true.`;
}

function renderReveal(p, guess) {
  const view = $("reveal-view");
  view.replaceChildren();
  const [emoji, label] = VERDICTS[p.verdict] || ["•", p.verdict];

  const badge = el("div", null, `badge verdict-${p.verdict}`);
  badge.append(el("span", emoji, "badge-emoji"), el("strong", label), el("span", `confidence: ${p.confidence}`, "conf"));
  view.append(badge);

  view.append(el("p", `You guessed: ${guess.replace("_", " ")}`, "muted"));
  if (p.guess_feedback) view.append(el("p", `🎯 ${p.guess_feedback}`, "feedback"));
  view.append(el("p", p.explanation));
  if (p.verdict !== "opinion") view.append(el("p", `📊 ${agreementText(p.verdict, p.agreement)}`, "agreement"));

  if (p.sources.length) {
    view.append(el("p", "Sources", "label"));
    const list = el("ul", null, "sources");
    for (const s of p.sources) {
      const li = el("li");
      const a = el("a", s.outlet);
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      li.append(a, el("span", ` · ${s.stance}${s.is_claimreview ? " · published fact-check" : ""}`, "muted"));
      if (s.quote) li.append(el("blockquote", s.quote));
      else if (s.rating) li.append(el("blockquote", `Rated: ${s.rating}`));
      list.append(li);
    }
    view.append(list);
  }

  const rejected = p.agreement.rejected_quotes;
  if (rejected) {
    view.append(el("p", `🛡 ${rejected} AI-suggested quote${rejected > 1 ? "s" : ""} didn't match the source and ${rejected > 1 ? "were" : "was"} thrown out.`, "muted"));
  }
  view.append(el("p", `💡 Tip: ${p.tip}`, "tip"));
  view.append(el("p", p.disclaimer, "disclaimer"));

  const again = el("button", "Check another post", "secondary");
  again.addEventListener("click", () => {
    $("post-text").value = "";
    show("input-view");
  });
  view.append(again);
  show("reveal-view");
}

// "Needs you less" tracker: only right/wrong flags are kept, in this browser. No post content.
const HISTORY_SIZE = 10;
const SKILLED_AT = 0.8; // ≥ 8 of the last 10 right → nudge the user to check sources first themselves

function guessWasRight(guess, verdict) {
  if (verdict === "opinion") return null; // no right answer, not scored
  if (verdict === "true" || verdict === "false") return guess === verdict;
  return guess === "not_sure"; // misleading / unverified / developing: caution was the right call
}

async function recordGuess(guess, verdict) {
  const right = guessWasRight(guess, verdict);
  let history = [];
  try { history = (await chrome.storage.local.get("history")).history || []; } catch (_) {}
  if (right !== null) {
    history = [...history, right].slice(-HISTORY_SIZE);
    try { await chrome.storage.local.set({ history }); } catch (_) {}
  }
  return history;
}

function renderProgress(history) {
  if (!history.length) return null;
  const right = history.filter(Boolean).length;
  const box = el("div", null, "progress");
  box.append(el("strong", `Your last ${history.length} guess${history.length > 1 ? "es" : ""}: ${right} right`));
  const dots = el("div", null, "dots");
  for (const h of history) dots.append(el("span", h ? "●" : "○", h ? "dot-right" : "dot-wrong"));
  box.append(dots);
  if (history.length >= HISTORY_SIZE && right / history.length >= SKILLED_AT) {
    box.append(el("p", "You're getting good at this. Next time, try opening a source yourself before you ask me.", "muted"));
  }
  return box;
}

async function reveal(guess) {
  status("");
  try {
    const p = await api("/check/reveal", { check_id: checkId, guess });
    renderReveal(p, guess);
    const progress = renderProgress(await recordGuess(guess, p.verdict));
    if (progress) $("reveal-view").insertBefore(progress, $("reveal-view").lastChild);
  } catch (e) {
    show("input-view");
    status(e.status === 410 || e.status === 404 ? "That check expired. Please check it again." : "Something went wrong. Please try again.");
  }
}

async function init() {
  try {
    const stored = await chrome.storage.local.get("apiBase");
    if (stored.apiBase) apiBase = stored.apiBase;
  } catch (_) { /* storage unavailable: use default */ }
  $("api-base").value = apiBase;

  $("save-api").addEventListener("click", async () => {
    apiBase = $("api-base").value.replace(/\/+$/, "") || DEFAULT_API;
    try { await chrome.storage.local.set({ apiBase }); } catch (_) {}
    status("Saved.");
  });
  $("check-btn").addEventListener("click", () => {
    const text = $("post-text").value.trim();
    if (!text && !pendingUrl) return status("Paste some text to check.");
    startCheck(text, pendingUrl);
  });
  for (const b of document.querySelectorAll("[data-guess]")) {
    b.addEventListener("click", () => reveal(b.dataset.guess));
  }

  // Offer a one-click check when the active tab is an Instagram post (activeTab permission, URL only).
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab && tab.url && IG_POST_RE.test(tab.url)) {
      const btn = $("check-ig");
      btn.hidden = false;
      btn.addEventListener("click", () => startCheck("", tab.url.match(IG_POST_RE)[0]));
    }
  } catch (_) { /* opened as a context-menu window: no active-tab access needed */ }

  const text = new URLSearchParams(location.search).get("text");
  if (text) {
    $("post-text").value = text;
    startCheck(text, null);
  }
}

init();
