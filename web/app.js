// Fact-Check Coach landing page: same-origin calls to the API. All API text is rendered with textContent.
const $ = (id) => document.getElementById(id);
const VERDICTS = {
  false: ["❌", "False"], true: ["✅", "True"], misleading: ["⚠️", "Misleading"],
  unverified: ["❓", "Unverified"], developing: ["⏳", "Still developing"], opinion: ["💬", "Opinion"],
};
const COMMENT_ICONS = { opinion: "💬", question: "❔", other: "▫️" };
const VERDICT_ICONS = { false: "🚩", true: "✅", misleading: "⚠️", unverified: "❓", developing: "⏳" };
const MAX_SIDE = 1600; // screenshots are downscaled in the browser (also drops photo metadata)

let mode = "post";
let imageB64 = null;
let checkId = null;
let workTimer = null;
let lastOpinion = null; // start payload of an opinion post: what we read, red flags, questions

function el(tag, text, className) {
  const n = document.createElement(tag);
  if (text != null) n.textContent = text;
  if (className) n.className = className;
  return n;
}

function show(pane) {
  for (const id of ["pane-input", "pane-working", "pane-guess", "pane-result"]) $(id).hidden = id !== pane;
}

function status(msg, isError = false) {
  $("status").textContent = msg || "";
  $("status").classList.toggle("is-error", isError);
}

async function api(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    let detail = `HTTP ${r.status}`;
    try { const j = await r.json(); detail = typeof j.detail === "string" ? j.detail : detail; } catch (_) {}
    const e = new Error(detail); e.status = r.status; throw e;
  }
  return r.json();
}

/* ---------- images ---------- */
function readRaw(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",")[1]);
    r.onerror = () => reject(new Error("Couldn't read that image."));
    r.readAsDataURL(blob);
  });
}

function blobToB64(blob) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(blob);
    img.onload = () => {
      const scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
      if (scale === 1 && blob.size <= 1.5 * 1024 * 1024) {  // small enough: send as is
        URL.revokeObjectURL(url);
        return readRaw(blob).then(resolve, reject);
      }
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * scale);
      c.height = Math.round(img.height * scale);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      resolve(c.toDataURL("image/jpeg", 0.88).split(",")[1]);
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("That file isn't an image we can read.")); };
    img.src = url;
  });
}

async function useImage(blob) {
  if (!blob || !blob.type.startsWith("image/")) return status("Please choose a PNG, JPEG or WebP image.", true);
  try {
    imageB64 = await blobToB64(blob);
  } catch (e) {
    return status(e.message, true);
  }
  $("preview").src = URL.createObjectURL(blob);
  $("preview").hidden = false;
  $("drop-inner").hidden = true;
  $("clear").hidden = false;
  status("");
}

function clearInput() {
  imageB64 = null;
  $("file").value = "";
  $("preview").hidden = true;
  $("preview").removeAttribute("src");
  $("drop-inner").hidden = false;
  $("clear").hidden = true;
  $("text").value = "";
  status("");
}

/* ---------- progress ---------- */
function startWorking(steps) {
  show("pane-working");
  const list = $("work-steps");
  list.replaceChildren(...steps.map((s) => el("li", s)));
  let i = 0;
  const tick = () => {
    [...list.children].forEach((li, j) => {
      li.classList.toggle("is-done", j < i);
      li.classList.toggle("is-now", j === i);
    });
    if (i < steps.length - 1) i += 1;
  };
  tick();
  workTimer = setInterval(tick, 2600);
}

function stopWorking() {
  clearInterval(workTimer);
}

/* ---------- post check ---------- */
async function checkPost(text) {
  const steps = [
    ...(imageB64 ? ["Reading the text in your screenshot"] : []),
    "Finding the claim",
    "Searching the named fact-checkers and newsrooms",
    "Checking every quote against its source",
    "Applying the verdict rules",
  ];
  startWorking(steps);
  status("");
  try {
    const p = await api("/check/start", { text: text || "", image_base64: imageB64, client: "extension" });
    stopWorking();
    if (p.needs_text) return renderNote(p.note);
    checkId = p.check_id;
    if (!p.checkable) {
      // Opinions skip the guess: show the result straight away, with what we read and what to ask.
      lastOpinion = p;
      return reveal("not_sure", true);
    }
    lastOpinion = null;
    $("claim").textContent = p.claim;
    $("read").hidden = !p.read_text;
    if (p.read_text) $("read").textContent = `📝 We read: “${p.read_text}”`;
    $("question").textContent = `🤔 ${p.question}`;
    show("pane-guess");
  } catch (e) {
    stopWorking();
    show("pane-input");
    status(e.status === 422 ? e.message : "The checker isn't reachable right now. Is the API running?", true);
  }
}

async function reveal(guess, skippedGuess = false) {
  try {
    const p = await api("/check/reveal", { check_id: checkId, guess });
    renderReveal(p, skippedGuess ? null : guess);
  } catch (e) {
    show("pane-input");
    status(e.status === 410 || e.status === 404 ? "That check expired. Please run it again." : "Something went wrong. Please try again.", true);
  }
}

function agreementText(v, a) {
  const covering = a.supports + a.contradicts;
  if (covering === 0) return `None of the ${a.outlets_checked} outlets we checked cover it yet.`;
  const say = (n) => (n === 1 ? `${n} says` : `${n} say`);
  const head = `${covering} of ${a.outlets_checked} outlets checked cover it`;
  if ((v === "false" || v === "true") && Math.min(a.supports, a.contradicts) === 0) {
    return `${head}; ${covering > 1 ? "all " : ""}${say(covering)} it's ${v}.`;
  }
  return `${head}: ${say(a.contradicts)} it's false, ${say(a.supports)} it's true.`;
}

function sourceLink(s) {
  const a = el("a", s.outlet);
  a.href = s.url; a.target = "_blank"; a.rel = "noopener noreferrer";
  return a;
}

function whatIsTrueCard(w) {
  const card = el("div", null, `known known-${w.kind}`);
  card.append(el("p", w.heading, "known-heading"), el("p", w.text, "known-text"));
  if (w.sources.length) {
    const refs = el("p", "Source: ", "known-refs");
    w.sources.forEach((s, i) => { if (i) refs.append(", "); refs.append(sourceLink(s)); });
    card.append(refs);
  }
  return card;
}

function renderReveal(p, guess) {
  const out = $("pane-result");
  out.replaceChildren();
  const [emoji, label] = VERDICTS[p.verdict] || ["•", p.verdict];
  const v = el("div", null, `verdict v-${p.verdict}`);
  const conf = el("div", null, "verdict-conf");
  conf.append(el("div", `confidence: ${p.confidence}`));
  if (guess) conf.append(el("div", `you guessed: ${guess.replace("_", " ")}`));
  v.append(el("span", emoji, "verdict-emoji"), el("span", label, "verdict-label"), conf);
  out.append(v);

  if (p.guess_feedback && guess) out.append(el("p", `🎯 ${p.guess_feedback}`, "feedback"));
  if (p.claim) out.append(el("p", `Claim: ${p.claim}`, "kicker"));
  if (p.what_is_true) out.append(whatIsTrueCard(p.what_is_true));
  out.append(el("p", p.explanation, "explain"));
  if (p.verdict === "opinion" && lastOpinion) {
    if (lastOpinion.read_text) out.append(el("p", `📝 We read: “${lastOpinion.read_text}”`, "read-text"));
    const box = el("div", null, "known known-context");
    box.append(el("p", "Worth asking yourself", "known-heading"));
    const ul = el("ul");
    [...(lastOpinion.red_flags || []).map((f) => `🚩 ${f}`), ...(lastOpinion.opinion_questions || [])]
      .forEach((q) => ul.append(el("li", q)));
    box.append(ul);
    out.append(box);
  }

  if (p.verdict !== "opinion") {
    const a = p.agreement;
    const meter = el("div", null, "meter");
    for (let i = 0; i < a.outlets_checked; i += 1) {
      meter.append(el("span", null, i < a.contradicts ? "m-con" : i < a.contradicts + a.supports ? "m-sup" : ""));
    }
    meter.setAttribute("aria-hidden", "true");
    out.append(meter, el("p", `📊 ${agreementText(p.verdict, a)}`, "meter-text"));
  }

  if (p.sources.length) {
    out.append(el("p", "The evidence", "kicker"));
    const list = el("ul", null, "sources");
    for (const s of p.sources) {
      const li = el("li");
      const head = el("div", null, "src-head");
      head.append(sourceLink(s), el("span", s.stance === "contradicts" ? "says it's false" : "backs it up",
        `tag ${s.stance === "contradicts" ? "tag-con" : "tag-sup"}`));
      if (s.is_claimreview) head.append(el("span", "published fact-check", "tag"));
      li.append(head);
      if (s.quote) li.append(el("blockquote", `“${s.quote}”`));
      else if (s.rating) li.append(el("blockquote", `Rated: ${s.rating}`));
      list.append(li);
    }
    out.append(list);
  }
  const rejected = p.agreement.rejected_quotes;
  if (rejected) out.append(el("p", `🛡️ ${rejected} AI-suggested quote${rejected > 1 ? "s" : ""} didn't match the source and ${rejected > 1 ? "were" : "was"} thrown out.`, "shield"));
  out.append(el("p", `💡 Tip: ${p.tip}`, "tip"));
  out.append(el("p", p.disclaimer, "disclaimer"));

  const actions = el("div", null, "result-actions");
  const again = el("button", "Check another post", "btn btn-primary");
  again.addEventListener("click", () => { clearInput(); show("pane-input"); });
  const comments = el("button", "Now check its comments", "btn btn-ghost");
  comments.addEventListener("click", () => { clearInput(); setMode("comments"); show("pane-input"); $("text").focus(); });
  actions.append(again, comments);
  out.append(actions);
  show("pane-result");
  out.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderNote(note) {
  // Not an error: the checker explains why it can't check this and how to check it yourself.
  const out = $("pane-result");
  out.replaceChildren();
  const card = el("div", null, "note-card");
  card.append(el("p", "🧭 Your turn to check", "kicker"));
  const [first, ...rest] = note.split(/(?=\d\) )/);
  card.append(el("p", first.trim(), "note-lead"));
  if (rest.length) {
    const list = el("ol", null, "note-steps");
    rest.forEach((r) => list.append(el("li", r.replace(/^\d\)\s*/, "").replace(/,\s*$/, "").trim())));
    card.append(list);
  }
  const back = el("button", "Type what the post claims", "btn btn-primary");
  back.addEventListener("click", () => { clearInput(); show("pane-input"); $("text").focus(); });
  out.append(card, back);
  show("pane-result");
}

/* ---------- comments ---------- */
async function checkComments(text) {
  startWorking([
    ...(imageB64 ? ["Reading the comments in your screenshot"] : []),
    "Sorting opinions, questions and claims",
    "Checking each claim against the named outlets",
    "Flagging misinformation",
  ]);
  status("");
  try {
    const p = await api("/comments/check", { text: text || "", image_base64: imageB64, client: "extension" });
    stopWorking();
    renderComments(p);
  } catch (e) {
    stopWorking();
    show("pane-input");
    status(e.status === 422 ? e.message : "The checker isn't reachable right now. Is the API running?", true);
  }
}

function renderComments(p) {
  const out = $("pane-result");
  out.replaceChildren();
  if (!p.comments.length) {
    out.append(el("p", p.note || "I couldn't find any comments in that."));
  } else {
    const s = p.summary;
    const chips = el("div", null, "summary-chips");
    chips.append(el("span", `💬 ${s.opinions} opinion${s.opinions === 1 ? "" : "s"}`),
      el("span", `❔ ${s.questions} question${s.questions === 1 ? "" : "s"}`),
      el("span", `🔎 ${s.claims} factual claim${s.claims === 1 ? "" : "s"}`));
    if (s.misinformation) chips.append(el("span", `🚩 ${s.misinformation} misinformation`, "s-bad"));
    if (s.backed) chips.append(el("span", `✅ ${s.backed} backed by sources`, "s-good"));
    out.append(chips);
    const list = el("ul", null, "comment-list");
    for (const c of p.comments) {
      const li = el("li", null, `comment c-${c.verdict || c.kind}`);
      li.append(el("div", `${VERDICT_ICONS[c.verdict] || COMMENT_ICONS[c.kind] || "▫️"} “${c.text}”`));
      li.append(el("div", c.label, "comment-label"));
      if (c.what_is_true) li.append(el("div", `What's actually true: ${c.what_is_true}`, "comment-true"));
      if (c.source && ["false", "true", "misleading"].includes(c.verdict)) {
        const a = sourceLink(c.source);
        a.textContent = `↳ ${c.source.outlet}`;
        li.append(a);
      }
      list.append(li);
    }
    out.append(list, el("p", `💡 Tip: ${p.tip}`, "tip"), el("p", p.disclaimer, "disclaimer"));
  }
  const again = el("button", "Check something else", "btn btn-primary");
  again.addEventListener("click", () => { clearInput(); show("pane-input"); });
  out.append(again);
  show("pane-result");
}

/* ---------- wiring ---------- */
function setMode(next) {
  mode = next;
  document.querySelectorAll(".tab").forEach((t) => {
    const on = t.dataset.mode === mode;
    t.classList.toggle("is-active", on);
    t.setAttribute("aria-selected", String(on));
  });
  $("drop-title").textContent = mode === "post" ? "Drop a screenshot here" : "Drop a screenshot of the comments";
  $("text").placeholder = mode === "post"
    ? "Paste a caption, e.g. “Scientists CONFIRM 5G towers make people sick!!! link in bio”"
    : "Paste the comments, one per line, e.g.\nThis is so scary\nFake, Reuters says there's no evidence\nIs this real??";
  show("pane-input");
  status("");
}

function go() {
  const text = $("text").value.trim();
  if (!text && !imageB64) return status("Add a screenshot or paste some text first.", true);
  if (mode === "comments") checkComments(text);
  else checkPost(text);
}

async function loadSources() {
  try {
    const r = await fetch("/sources");
    const data = await r.json();
    const grid = $("outlets");
    for (const o of data.outlets) {
      const card = el("div", null, "outlet");
      card.append(el("h3", o.name), el("p", `${o.type.replace("_", " ")} · ${o.domains.join(", ")}`));
      const b = el("span", `Bias: ${o.bias_label}${o.bias_status === "confirmed" ? "" : " (unconfirmed)"}`,
        `bias ${o.bias_status === "confirmed" ? "" : "unconfirmed"}`);
      b.title = o.bias_note || "";
      card.append(b);
      grid.append(card);
    }
    document.querySelectorAll("[data-outlet-count]").forEach((n) => { n.textContent = String(data.outlets.length); });
    $("bias-note").textContent = `Bias labels from ${data.outlets[0]?.bias_source || "AllSides"} (perceived political lean, not accuracy), checked ${data.bias_checked}.`;
  } catch (_) { /* section stays empty if the API is down */ }
}

async function loadConfig() {
  try {
    const cfg = await (await fetch("/app-config")).json();
    if (!cfg.telegram_bot) return;
    document.querySelectorAll("[data-telegram]").forEach((a) => {
      a.href = `https://t.me/${cfg.telegram_bot}`; a.target = "_blank"; a.rel = "noopener noreferrer";
    });
    document.querySelectorAll("[data-telegram-name]").forEach((s) => { s.textContent = cfg.telegram_bot; });
  } catch (_) {}
}

function init() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => setMode(t.dataset.mode)));
  $("file").addEventListener("change", (e) => useImage(e.target.files[0]));
  const drop = $("drop");
  drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file").click(); } });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("is-over"); }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("is-over"); }));
  drop.addEventListener("drop", (e) => useImage(e.dataTransfer.files[0]));
  document.addEventListener("paste", (e) => {
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (item) { e.preventDefault(); useImage(item.getAsFile()); }
  });
  $("clear").addEventListener("click", clearInput);
  $("go").addEventListener("click", go);
  document.querySelectorAll("[data-guess]").forEach((b) => b.addEventListener("click", () => reveal(b.dataset.guess)));
  document.querySelectorAll(".example").forEach((b) => b.addEventListener("click", async () => {
    setMode("post");
    clearInput();
    const blob = await (await fetch(b.dataset.example)).blob();
    await useImage(blob);
    $("try").scrollIntoView({ behavior: "smooth" });
    checkPost("");
  }));
  loadSources();
  loadConfig();
}

init();
