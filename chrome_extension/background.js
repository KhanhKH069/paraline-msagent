/**
 * chrome_extension/background.js
 * Meeting AI Assistant v2.0 — Background Service Worker (Manifest V3)
 *
 * Nhiệm vụ:
 * 1. Tự động nhận diện tab Google Meet đang hoạt động (meet.google.com/xxx-xxxx-xxx).
 * 2. Giao tiếp hai chiều với Python Bridge (port 9877 mặc định):
 *    - Gửi sự kiện meeting_started / meeting_ended
 *    - Polling tin nhắn dịch từ hàng đợi và inject vào Meet Chat / Subtitle HUD
 * 3. Quản lý trạng thái, lịch sử tin nhắn và cấu hình linh hoạt qua chrome.storage.
 * 4. Chống service worker sleep bằng chrome.alarms và chu kỳ polling.
 */

const MEET_PATTERN = /meet\.google\.com\/([a-z]{3}-[a-z]{4}-[a-z]{3})/;

// Trạng thái runtime
let config = {
  bridgeUrl: "http://localhost:9877",
  autoChatEnabled: true,
  overlayEnabled: true,
  showBadge: true,
};

let activeMeetTabId   = null;
let activeMeetCode    = null;
let bridgeOk          = false;
let lastPingMs        = 0;
let pollBusy          = false;
let messagesSentCount = 0;
let messageHistory    = [];

// ─── Khởi tạo & Đọc cấu hình từ Storage ───────────────────────────────────

async function initSettings() {
  try {
    const data = await chrome.storage.local.get([
      "bridgeUrl",
      "autoChatEnabled",
      "overlayEnabled",
      "showBadge",
    ]);
    if (data.bridgeUrl) config.bridgeUrl = data.bridgeUrl.replace(/\/+$/, "");
    if (typeof data.autoChatEnabled === "boolean") config.autoChatEnabled = data.autoChatEnabled;
    if (typeof data.overlayEnabled === "boolean")  config.overlayEnabled  = data.overlayEnabled;
    if (typeof data.showBadge === "boolean")       config.showBadge       = data.showBadge;
  } catch (e) {
    console.warn("[Meeting AI BG] Storage load error:", e);
  }
}

initSettings();

// Đăng ký Alarm giữ worker không bị Chrome suspend
chrome.alarms.create("keepAlive", { periodInMinutes: 0.5 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepAlive") {
    checkBridge();
    ensureActiveMeetTab();
  }
});

// ─── Kiểm tra kết nối tới Python Bridge (Ping) ────────────────────────────

async function checkBridge() {
  const t0 = Date.now();
  try {
    const res = await fetch(`${config.bridgeUrl}/health`, {
      method: "GET",
      signal: AbortSignal.timeout(2000),
    });
    bridgeOk = res.ok;
    lastPingMs = Date.now() - t0;
  } catch {
    bridgeOk = false;
    lastPingMs = 0;
  }
  return { bridgeOk, lastPingMs };
}

// Kiểm tra ban đầu và lập chu kỳ
checkBridge();
setInterval(checkBridge, 4000);

// ─── Tìm và xác nhận Tab Google Meet đang mở ─────────────────────────────

async function ensureActiveMeetTab() {
  if (activeMeetTabId !== null) {
    try {
      const tab = await chrome.tabs.get(activeMeetTabId);
      if (tab && isMeetUrl(tab.url)) {
        return activeMeetTabId;
      }
    } catch {
      activeMeetTabId = null;
      activeMeetCode  = null;
    }
  }

  try {
    const tabs = await chrome.tabs.query({ url: "*://meet.google.com/*" });
    for (const t of tabs) {
      const code = getMeetCode(t.url || "");
      if (code) {
        if (activeMeetTabId !== t.id) {
          activeMeetTabId = t.id;
          activeMeetCode  = code;
          postEvent({
            type: "meeting_started",
            meet_url: `https://meet.google.com/${code}`,
            meet_code: code,
          });
        }
        return t.id;
      }
    }
  } catch (e) {
    console.warn("[Meeting AI BG] Query tabs error:", e);
  }
  return null;
}

function isMeetUrl(url) {
  return Boolean(url && MEET_PATTERN.test(url));
}

function getMeetCode(url) {
  const m = MEET_PATTERN.exec(url);
  return m ? m[1] : null;
}

// ─── Gửi sự kiện tới Python Bridge ────────────────────────────────────────

async function postEvent(payload) {
  try {
    await fetch(`${config.bridgeUrl}/event`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
      signal:  AbortSignal.timeout(3000),
    });
    bridgeOk = true;
  } catch (e) {
    bridgeOk = false;
    console.warn("[Meeting AI BG] Gửi event thất bại:", e.message);
  }
}

// ─── Polling tin nhắn từ Python Bridge và Inject vào Meet ─────────────────

async function pollChatQueue() {
  if (pollBusy || !bridgeOk) return;

  const tabId = await ensureActiveMeetTab();
  if (tabId === null) return;

  pollBusy = true;
  try {
    const r = await fetch(`${config.bridgeUrl}/poll`, {
      signal: AbortSignal.timeout(1800),
    });
    if (!r.ok) return;

    const data = await r.json();
    if (data && data.has && typeof data.text === "string" && data.text.trim()) {
      const text = data.text.trim();
      messagesSentCount++;

      // Ghi log lịch sử
      messageHistory.unshift({
        id: Date.now(),
        text: text,
        time: new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        meetCode: activeMeetCode,
      });
      if (messageHistory.length > 30) messageHistory.pop();

      // 1. Gửi vào Subtitle HUD nổi trên màn hình Meet
      if (config.overlayEnabled) {
        chrome.tabs.sendMessage(tabId, {
          action: "show_subtitle",
          text: text,
        }).catch(() => {});
      }

      // 2. Gửi tự động vào Chat Meet
      if (config.autoChatEnabled) {
        chrome.tabs.sendMessage(tabId, {
          action: "inject_chat",
          text: text,
        }).catch((err) => {
          console.warn("[Meeting AI BG] Lỗi inject chat:", err);
        });
      }
    }
  } catch (_e) {
    // lỗi fetch tạm thời bỏ qua
  } finally {
    pollBusy = false;
  }
}

setInterval(pollChatQueue, 600);

// ─── Theo dõi thay đổi Tabs ───────────────────────────────────────────────

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") return;

  const url = tab.url || "";
  const code = getMeetCode(url);

  if (code && tabId !== activeMeetTabId) {
    activeMeetTabId = tabId;
    activeMeetCode  = code;
    console.log("[Meeting AI BG] Phát hiện cuộc họp mới:", code);
    await postEvent({
      type: "meeting_started",
      meet_url: `https://meet.google.com/${code}`,
      meet_code: code,
    });
  } else if (!code && tabId === activeMeetTabId) {
    console.log("[Meeting AI BG] Cuộc họp kết thúc (tab chuyển trang)");
    activeMeetTabId = null;
    activeMeetCode  = null;
    await postEvent({ type: "meeting_ended" });
  }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  if (tabId === activeMeetTabId) {
    console.log("[Meeting AI BG] Cuộc họp kết thúc (tab đã đóng)");
    activeMeetTabId = null;
    activeMeetCode  = null;
    await postEvent({ type: "meeting_ended" });
  }
});

// ─── Xử lý Message từ Popup và Content Script ─────────────────────────────

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  switch (msg.action) {
    case "get_status": {
      ensureActiveMeetTab().then(() => {
        sendResponse({
          bridgeOk,
          lastPingMs,
          activeMeetCode,
          activeMeetTabId,
          messagesSentCount,
          config,
          history: messageHistory.slice(0, 12),
        });
      });
      return true;
    }

    case "test_connection": {
      checkBridge().then(result => sendResponse(result));
      return true;
    }

    case "save_settings": {
      if (msg.config) {
        config = { ...config, ...msg.config };
        chrome.storage.local.set(config).then(() => {
          // Gửi config mới cho content script nếu có tab meet
          if (activeMeetTabId) {
            chrome.tabs.sendMessage(activeMeetTabId, {
              action: "update_config",
              config: config,
            }).catch(() => {});
          }
          sendResponse({ ok: true, config });
        });
      }
      return true;
    }

    case "send_test_chat": {
      if (!activeMeetTabId) {
        sendResponse({ ok: false, error: "Chưa mở tab Google Meet nào." });
        return true;
      }
      chrome.tabs.sendMessage(activeMeetTabId, {
        action: "inject_chat",
        text: msg.text || "Xin chào từ Meeting AI Assistant!",
      }).then(res => {
        messagesSentCount++;
        messageHistory.unshift({
          id: Date.now(),
          text: msg.text,
          time: new Date().toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
          meetCode: activeMeetCode,
        });
        sendResponse({ ok: true, res });
      }).catch(err => {
        sendResponse({ ok: false, error: err.message });
      });
      return true;
    }

    case "clear_history": {
      messageHistory = [];
      messagesSentCount = 0;
      sendResponse({ ok: true });
      return true;
    }

    default:
      sendResponse({ ok: false, error: "unknown action" });
      return false;
  }
});

console.log("🟠 [Meeting AI] Background Service Worker v2.0 ready.");
