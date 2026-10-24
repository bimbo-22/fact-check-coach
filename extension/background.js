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
