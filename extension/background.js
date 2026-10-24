// Right-click selected text → open the coach in a small window.
// The selection is passed in the window URL only; nothing is stored.
const MENU_ID = "fcc-check";
const MAX_CHARS = 2000;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: MENU_ID,
    title: "Check with Fact-Check Coach",
    contexts: ["selection"],
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId !== MENU_ID || !info.selectionText) return;
  const text = info.selectionText.slice(0, MAX_CHARS);
  chrome.windows.create({
    url: chrome.runtime.getURL(`popup.html?text=${encodeURIComponent(text)}`),
    type: "popup",
    width: 440,
    height: 720,
  });
});
