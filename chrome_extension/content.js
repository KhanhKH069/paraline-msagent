/**
 * chrome_extension/content.js
 * Meeting AI Assistant v2.0 — Content Script for Google Meet
 *
 * Tính năng:
 * 1. Inject tin nhắn dịch tự động vào Google Meet chat với selector nâng cao.
 * 2. Hiển thị Cinema Subtitle HUD (phụ đề nổi thời gian thực) trên màn hình video.
 * 3. Hiển thị Floating Status Bar với nút điều khiển nhanh (Bật/Tắt chat, Bật/Tắt phụ đề).
 */

(function () {
  "use strict";

  // Cấu hình cục bộ
  let localConfig = {
    autoChatEnabled: true,
    overlayEnabled: true,
    showBadge: true,
  };

  let subtitleTimer = null;

  // ─── Selectors Google Meet (Cập nhật 2024 - 2026) ─────────────────────────
  const CHAT_INPUT_SELECTORS = [
    'textarea[name="chatTextInput"]',
    'textarea[aria-label*="Send a message" i]',
    'textarea[aria-label*="Gửi tin nhắn" i]',
    'textarea[aria-label*="message" i]',
    'textarea[aria-label*="tin nhắn" i]',
    'textarea[placeholder*="Send a message" i]',
    'textarea[placeholder*="Gửi tin nhắn" i]',
    'div[contenteditable="true"][aria-label*="message" i]',
    'div[contenteditable="true"][aria-label*="tin nhắn" i]',
    'div[contenteditable="true"][data-placeholder]',
    'textarea[jsname="YPqjbf"]',
    'div[data-side-panel-id="2"] textarea',
    'div[data-panel-id="2"] textarea',
    'div[role="region"] textarea',
    'textarea',
  ];

  const SEND_BTN_SELECTORS = [
    'button[aria-label*="Send a message" i]',
    'button[aria-label*="Send message" i]',
    'button[aria-label*="Send" i]',
    'button[aria-label*="Gửi tin nhắn" i]',
    'button[aria-label*="Gửi" i]',
    'button[data-tooltip*="Send" i]',
    'button[data-tooltip*="Gửi" i]',
    'button[jsname="r8qRAd"]',
    'div[data-side-panel-id="2"] button[aria-label*="Send" i]',
    'div[data-side-panel-id="2"] button[aria-label*="Gửi" i]',
  ];

  const CHAT_TOGGLE_SELECTORS = [
    'button[aria-label*="Chat with everyone" i]',
    'button[aria-label*="Trò chuyện với mọi người" i]',
    'button[aria-label*="Open chat" i]',
    'button[aria-label*="Trò chuyện" i]',
    'button[aria-label*="Chat" i]',
    'button[aria-label*="tin nhắn" i]',
    'button[data-panel-id="2"]',
    'button[jsname="A5il2e"]',
  ];

  // ─── Helpers DOM ──────────────────────────────────────────────────────────

  function findEl(selectors) {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.offsetParent !== null) return el;
    }
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  function isChatOpen() {
    const input = findEl(CHAT_INPUT_SELECTORS);
    if (input && input.offsetParent !== null) return true;

    for (const sel of CHAT_TOGGLE_SELECTORS) {
      const btn = document.querySelector(sel);
      if (btn && (btn.getAttribute("aria-pressed") === "true" || btn.classList.contains("qs41qe"))) {
        return true;
      }
    }
    return false;
  }

  function openChatPanel() {
    if (isChatOpen()) return true;
    for (const sel of CHAT_TOGGLE_SELECTORS) {
      const btn = document.querySelector(sel);
      if (btn) {
        btn.click();
        return true;
      }
    }
    return false;
  }

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function waitForEl(selectors, timeout = 3500) {
    return new Promise(resolve => {
      const found = findEl(selectors);
      if (found) return resolve(found);

      const observer = new MutationObserver(() => {
        const el = findEl(selectors);
        if (el) {
          observer.disconnect();
          resolve(el);
        }
      });
      observer.observe(document.body, { childList: true, subtree: true });
      setTimeout(() => {
        observer.disconnect();
        resolve(null);
      }, timeout);
    });
  }

  // ─── Inject Chat Logic ───────────────────────────────────────────────────

  async function injectChat(text) {
    if (!text || !text.trim()) return false;

    // Đảm bảo chat panel đã mở
    if (!isChatOpen()) {
      openChatPanel();
      await sleep(350);
    }

    const input = await waitForEl(CHAT_INPUT_SELECTORS, 3000);
    if (!input) {
      console.warn("[Meeting AI] Không tìm thấy ô nhập chat Google Meet.");
      return false;
    }

    input.focus();

    if (input.tagName === "TEXTAREA" || input.tagName === "INPUT") {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, "value"
      )?.set ||
      Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, "value"
      )?.set;

      if (setter) {
        setter.call(input, text);
      } else {
        input.value = text;
      }
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      // Contenteditable div
      input.textContent = text;
      input.dispatchEvent(new InputEvent("input", { bubbles: true, data: text }));
    }

    await sleep(250);

    const sendBtn = findEl(SEND_BTN_SELECTORS);
    if (sendBtn && !sendBtn.disabled && sendBtn.offsetParent !== null) {
      sendBtn.click();
    } else {
      input.dispatchEvent(new KeyboardEvent("keydown", {
        key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true, composed: true
      }));
      input.dispatchEvent(new KeyboardEvent("keyup", {
        key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true, composed: true
      }));
    }

    console.log("[Meeting AI] Đã inject chat thành công:", text.substring(0, 50));
    return true;
  }

  // ─── Subtitle HUD (Phụ đề nổi trên màn hình video) ─────────────────────────

  function createSubtitleOverlay() {
    let overlay = document.getElementById("meeting-ai-subtitle-overlay");
    if (overlay) return overlay;

    overlay = document.createElement("div");
    overlay.id = "meeting-ai-subtitle-overlay";
    overlay.className = "hidden";
    overlay.innerHTML = `
      <div class="meeting-ai-sub-header">
        <span class="meeting-ai-sub-tag">🟠 AI Live Subtitle</span>
        <button class="meeting-ai-sub-close" id="meeting-ai-sub-close-btn" title="Đóng phụ đề">✕</button>
      </div>
      <div class="meeting-ai-sub-body" id="meeting-ai-sub-body"></div>
    `;

    document.body.appendChild(overlay);

    const closeBtn = document.getElementById("meeting-ai-sub-close-btn");
    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        overlay.classList.remove("visible");
        overlay.classList.add("hidden");
      });
    }

    return overlay;
  }

  function showSubtitle(text) {
    if (!localConfig.overlayEnabled) return;

    const overlay = createSubtitleOverlay();
    const body = document.getElementById("meeting-ai-sub-body");
    if (!body) return;

    // Clean text format nếu có tag tiền tố
    let cleanText = text.replace(/^\[Meeting AI\]\s*/i, "").replace(/^\[Meeting Chat\]\s*/i, "");
    body.textContent = cleanText;

    overlay.classList.remove("hidden");
    overlay.classList.add("visible");

    if (subtitleTimer) clearTimeout(subtitleTimer);
    subtitleTimer = setTimeout(() => {
      overlay.classList.remove("visible");
      overlay.classList.add("hidden");
    }, 7000);
  }

  // ─── Floating Top Status Badge & Quick Actions ─────────────────────────────

  function createFloatingBadge() {
    if (document.getElementById("meeting-ai-hud-container")) return;

    const container = document.createElement("div");
    container.id = "meeting-ai-hud-container";
    container.innerHTML = `
      <div class="meeting-ai-pulse-dot"></div>
      <div class="meeting-ai-hud-title">Meeting <span>AI</span></div>
      <div class="meeting-ai-hud-actions">
        <button class="meeting-ai-btn-icon ${localConfig.autoChatEnabled ? 'active' : ''}" id="mai-btn-chat" title="Tự động gửi chat (Bật/Tắt)">💬</button>
        <button class="meeting-ai-btn-icon ${localConfig.overlayEnabled ? 'active' : ''}" id="mai-btn-sub" title="Phụ đề nổi trên video (Bật/Tắt)">📺</button>
        <button class="meeting-ai-btn-icon" id="mai-btn-hide" title="Thu gọn">✕</button>
      </div>
    `;

    document.body.appendChild(container);

    const btnChat = document.getElementById("mai-btn-chat");
    const btnSub  = document.getElementById("mai-btn-sub");
    const btnHide = document.getElementById("mai-btn-hide");

    btnChat?.addEventListener("click", () => {
      localConfig.autoChatEnabled = !localConfig.autoChatEnabled;
      btnChat.classList.toggle("active", localConfig.autoChatEnabled);
      chrome.storage.local.set({ autoChatEnabled: localConfig.autoChatEnabled });
    });

    btnSub?.addEventListener("click", () => {
      localConfig.overlayEnabled = !localConfig.overlayEnabled;
      btnSub.classList.toggle("active", localConfig.overlayEnabled);
      chrome.storage.local.set({ overlayEnabled: localConfig.overlayEnabled });
      if (!localConfig.overlayEnabled) {
        const overlay = document.getElementById("meeting-ai-subtitle-overlay");
        if (overlay) overlay.className = "hidden";
      }
    });

    btnHide?.addEventListener("click", () => {
      container.style.display = "none";
    });
  }

  // ─── Khởi tạo & Lắng nghe Messages ────────────────────────────────────────

  async function init() {
    try {
      const data = await chrome.storage.local.get(["autoChatEnabled", "overlayEnabled", "showBadge"]);
      if (typeof data.autoChatEnabled === "boolean") localConfig.autoChatEnabled = data.autoChatEnabled;
      if (typeof data.overlayEnabled === "boolean")  localConfig.overlayEnabled  = data.overlayEnabled;
      if (typeof data.showBadge === "boolean")       localConfig.showBadge       = data.showBadge;
    } catch (_e) {}

    if (localConfig.showBadge) {
      createFloatingBadge();
    }
  }

  if (document.readyState === "complete") {
    setTimeout(init, 1500);
  } else {
    window.addEventListener("load", () => setTimeout(init, 1500));
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    switch (msg.action) {
      case "inject_chat": {
        injectChat(msg.text)
          .then(ok => sendResponse({ ok }))
          .catch(e  => sendResponse({ ok: false, error: e.message }));
        return true;
      }

      case "show_subtitle": {
        showSubtitle(msg.text);
        sendResponse({ ok: true });
        return false;
      }

      case "update_config": {
        if (msg.config) {
          localConfig = { ...localConfig, ...msg.config };
          const btnChat = document.getElementById("mai-btn-chat");
          const btnSub  = document.getElementById("mai-btn-sub");
          if (btnChat) btnChat.classList.toggle("active", localConfig.autoChatEnabled);
          if (btnSub)  btnSub.classList.toggle("active", localConfig.overlayEnabled);
        }
        sendResponse({ ok: true });
        return false;
      }
    }
  });

  console.log("🟠 [Meeting AI] Content Script v2.0 active on", location.href);
})();
