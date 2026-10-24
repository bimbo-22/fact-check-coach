// Right-click selected text → open the coach in a small window.
// The selection is passed in the window URL only; nothing is stored.
const MENU_ID = "fcc-check";
const IMAGE_MENU_ID = "fcc-check-image";
const MAX_CHARS = 2000;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: "Check with Fact-Check Coach",
    contexts: ["selection"],
  });
  chrome.contextMenus.create({
    id: IMAGE_MENU_ID,
    title: "Check this image with Fact-Check Coach",
    contexts: ["image"],
  });
});

function openCoach(query) {
  chrome.windows.create({
    url: chrome.runtime.getURL(`popup.html?${query}`),
    type: "popup",
    width: 440,
    height: 720,
  });
}

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === MENU_ID && info.selectionText) {
    openCoach(`text=${encodeURIComponent(info.selectionText.slice(0, MAX_CHARS))}`);
  } else if (info.menuItemId === IMAGE_MENU_ID && info.srcUrl) {
    // Only the image address is passed; the API downloads it (Instagram/Facebook CDNs only).
    openCoach(`imageUrl=${encodeURIComponent(info.srcUrl)}`);
  }
});

// Fact-checks requested from the Instagram feed (content.js). The API call is made here, from the
// extension's origin, so the API only has to allow the extension, not instagram.com.
const DEFAULT_API = "http://localhost:8000";

async function apiBase() {
  try { return (await chrome.storage.local.get("apiBase")).apiBase || DEFAULT_API; } catch (_) { return DEFAULT_API; }
}

async function post(path, body) {
  const r = await fetch(`${await apiBase()}${path}`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(r.status === 410 || r.status === 404 ? "That check expired. Try again." : `The checker said ${r.status}.`);
  return r.json();
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  const run = msg.type === "fcc-start"
    ? post("/check/start", { text: msg.text || "", image_url: msg.image_url || null, client: "extension" })
    : msg.type === "fcc-reveal"
      ? post("/check/reveal", { check_id: msg.check_id, guess: msg.guess })
      : null;
  if (!run) return false;
  run.then((data) => reply({ data })).catch((e) => reply({ error: e.message || "The checker isn't reachable." }));
  return true; // keep the channel open for the async reply
});
