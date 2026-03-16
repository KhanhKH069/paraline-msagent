/**
 * chrome_extension/background.js
 * Paraline Meet Bridge — Service Worker (Manifest V3)
 *
 * Theo dõi tabs thay đổi URL:
 *   ✅ URL match meet.google.com/xxx-xxxx-xxx → POST meeting_started
 *   🚪 Rời khỏi URL đó                        → POST meeting_ended
 *
 * Bridge endpoint: http://localhost:9877
 */

const BRIDGE_BASE   = "http://localhost:9877";
const MEET_PATTERN  = /meet\.google\.com\/([a-z]{3}-[a-z]{4}-[a-z]{3})/;

// Trạng thái
let activeMeetTabId = null;
let activeMeetCode  = null;
let bridgeOk        = false;
let pollBusy        = false;

// ─── Kiểm tra bridge còn sống không ───────────────────────────────────────

async function checkBridge() {
  try {
    const r = await fetch(`${BRIDGE_BASE}/health`, { signal: AbortSignal.timeout(1500) });
    bridgeOk = r.ok;
  } catch {
    bridgeOk = false;
  }
}

// Kiểm tra bridge mỗi 5 giây
setInterval(checkBridge, 5000);
checkBridge();

// ─── Poll chat queue từ Python bridge ──────────────────────────────────────
async function pollChatQueue() {
  if (pollBusy) return;
  if (!bridgeOk) return;
  if (activeMeetTabId === null) return;

  pollBusy = true;
  try {
    const r = await fetch(`${BRIDGE_BASE}/poll`, { signal: AbortSignal.timeout(1500) });
    if (!r.ok) return;
    const data = await r.json();
    if (data && data.has && typeof data.text === "string" && data.text.trim()) {
      chrome.tabs.sendMessage(activeMeetTabId, {
        action: "inject_chat",
        text:   data.text,
      });
    }
  } catch (_e) {
    // ignore; checkBridge will flip bridgeOk if needed
  } finally {
    pollBusy = false;
  }
}

setInterval(pollChatQueue, 800);

// ─── Gửi event đến Python bridge ──────────────────────────────────────────

async function postEvent(payload) {
  try {
    await fetch(`${BRIDGE_BASE}/event`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
      signal:  AbortSignal.timeout(3000),
    });
    bridgeOk = true;
  } catch (e) {
    bridgeOk = false;
    console.warn("[Paraline] Bridge không phản hồi:", e.message);
  }
}

// ─── Detect meeting bắt đầu / kết thúc ────────────────────────────────────

function isMeetUrl(url) {
  return url && MEET_PATTERN.test(url);
}

function getMeetCode(url) {
  const m = MEET_PATTERN.exec(url);
  return m ? m[1] : null;
}

async function onTabUpdated(tabId, changeInfo, tab) {
  if (changeInfo.status !== "complete") return;

  const url  = tab.url || "";
  const code = getMeetCode(url);

  if (code && tabId !== activeMeetTabId) {
    // Meeting mới bắt đầu
    console.log("[Paraline] Meeting bắt đầu:", code);
    activeMeetTabId = tabId;
    activeMeetCode  = code;
    await postEvent({
      type:     "meeting_started",
      meet_url: `https://meet.google.com/${code}`,
      meet_code: code,
    });
  } else if (!code && tabId === activeMeetTabId) {
    // Rời khỏi meet tab
    console.log("[Paraline] Meeting kết thúc (tab navigated away)");
    activeMeetTabId = null;
    activeMeetCode  = null;
    await postEvent({ type: "meeting_ended" });
  }
}

async function onTabRemoved(tabId) {
  if (tabId === activeMeetTabId) {
    console.log("[Paraline] Meeting kết thúc (tab closed)");
    activeMeetTabId = null;
    activeMeetCode  = null;
    await postEvent({ type: "meeting_ended" });
  }
}

chrome.tabs.onUpdated.addListener(onTabUpdated);
chrome.tabs.onRemoved.addListener(onTabRemoved);

// ─── Expose bridge status + message queue cho popup / content.js ──────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.action) {
    case "get_status":
      sendResponse({
        bridgeOk,
        activeMeetCode,
        activeMeetTabId,
      });
      break;

    case "send_chat":
      // Popup hoặc Python (qua native messaging tương lai) yêu cầu gửi chat
      if (activeMeetTabId !== null) {
        chrome.tabs.sendMessage(activeMeetTabId, {
          action: "inject_chat",
          text:   msg.text,
        });
      }
      sendResponse({ ok: true });
      break;

    default:
      sendResponse({ ok: false, error: "unknown action" });
  }
  return true; // keep channel open for async
});
