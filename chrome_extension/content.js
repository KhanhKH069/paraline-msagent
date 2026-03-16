/**
 * chrome_extension/content.js
 * Paraline Meet Bridge — Content Script
 *
 * Chạy trong trang meet.google.com.
 * Lắng nghe message "inject_chat" từ background.js
 * → Tự động điền text vào ô chat Google Meet và nhấn Send.
 *
 * Lưu ý: Google Meet dùng React/Custom Elements, selector có thể thay đổi.
 * Script thử nhiều selector theo thứ tự ưu tiên.
 */

(function () {
  "use strict";

  // ─── Selectors (thứ tự ưu tiên) ──────────────────────────────────────────
  const CHAT_INPUT_SELECTORS = [
    // Selector hiện tại của Google Meet (2024-2025)
    'textarea[aria-label*="Send a message"]',
    'textarea[aria-label*="message"]',
    'div[contenteditable="true"][aria-label*="message"]',
    'div[contenteditable="true"][data-placeholder]',
    // Fallback generic
    '[data-message-text]',
  ];

  const SEND_BTN_SELECTORS = [
    'button[aria-label*="Send message"]',
    'button[aria-label*="Send"]',
    'button[jsname="r8qRAd"]',   // Google Meet internal name (may change)
    'button[data-tooltip*="Send"]',
  ];

  // ─── Helpers ─────────────────────────────────────────────────────────────

  function findEl(selectors) {
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) return el;
    }
    return null;
  }

  function openChatPanel() {
    // Nếu panel chat chưa mở, thử click nút chat
    const chatToggles = [
      'button[aria-label*="Chat with everyone"]',
      'button[aria-label*="Open chat"]',
      'button[jsname="A5il2e"]',
    ];
    const btn = findEl(chatToggles);
    if (btn) {
      btn.click();
      return true;
    }
    return false;
  }

  async function injectChat(text) {
    // Bước 1: đảm bảo chat panel đang mở
    openChatPanel();

    // Bước 2: đợi input xuất hiện (tối đa 3s)
    const input = await waitForEl(CHAT_INPUT_SELECTORS, 3000);
    if (!input) {
      console.warn("[Paraline] Không tìm thấy ô chat Meet");
      return false;
    }

    // Bước 3: set text
    if (input.tagName === "TEXTAREA" || input.tagName === "INPUT") {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, "value"
      )?.set ||
        Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype, "value"
        )?.set;

      if (nativeInputValueSetter) {
        nativeInputValueSetter.call(input, text);
      } else {
        input.value = text;
      }
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      // contenteditable div
      input.focus();
      input.textContent = text;
      input.dispatchEvent(new InputEvent("input", { bubbles: true, data: text }));
    }

    // Bước 4: delay nhỏ để React state cập nhật
    await sleep(300);

    // Bước 5: nhấn Enter hoặc click Send button
    const sendBtn = findEl(SEND_BTN_SELECTORS);
    if (sendBtn && !sendBtn.disabled) {
      sendBtn.click();
    } else {
      input.dispatchEvent(new KeyboardEvent("keydown", {
        key: "Enter", code: "Enter", keyCode: 13, bubbles: true
      }));
    }

    console.log("[Paraline] Chat injected:", text.substring(0, 60));
    return true;
  }

  // ─── Utils ────────────────────────────────────────────────────────────────

  function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
  }

  function waitForEl(selectors, timeout = 3000) {
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

  // ─── Inject Paraline badge vào Meet toolbar ───────────────────────────────

  function injectBadge() {
    if (document.getElementById("paraline-badge")) return;

    const badge = document.createElement("div");
    badge.id = "paraline-badge";
    badge.style.cssText = `
      position: fixed;
      top: 12px;
      right: 12px;
      z-index: 999999;
      background: rgba(18,18,31,0.92);
      color: #ff6b35;
      font-family: 'Google Sans', sans-serif;
      font-size: 11px;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 20px;
      border: 1px solid #ff6b35;
      backdrop-filter: blur(4px);
      letter-spacing: 0.5px;
      pointer-events: none;
    `;
    badge.textContent = "🟠 Paraline Active";
    document.body.appendChild(badge);
  }

  // Inject badge sau khi trang load xong
  if (document.readyState === "complete") {
    setTimeout(injectBadge, 2000);
  } else {
    window.addEventListener("load", () => setTimeout(injectBadge, 2000));
  }

  // ─── Listen messages từ background.js ────────────────────────────────────

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.action === "inject_chat") {
      injectChat(msg.text)
        .then(ok => sendResponse({ ok }))
        .catch(e  => sendResponse({ ok: false, error: e.message }));
      return true; // async response
    }
  });

  console.log("[Paraline] Content script loaded on", location.href);
})();
