/**
 * chrome_extension/popup.js
 * Meeting AI Assistant v2.0 — Popup Controller
 */

document.addEventListener("DOMContentLoaded", () => {
  // Elements
  const pillStatus      = document.getElementById("bridge-status-pill");
  const txtStatus       = document.getElementById("bridge-status-text");
  const badgeMeet       = document.getElementById("badge-meet-state");
  const txtMeetCode     = document.getElementById("meet-code");
  const btnCopyCode     = document.getElementById("btn-copy-code");
  const btnOpenMeet     = document.getElementById("btn-open-meet");
  const valSentCount    = document.getElementById("metric-sent-count");
  const valPing         = document.getElementById("metric-ping");

  const toggleAutoChat  = document.getElementById("toggle-auto-chat");
  const toggleOverlay   = document.getElementById("toggle-overlay");
  const toggleBadge     = document.getElementById("toggle-floating-badge");

  const inputBridgeUrl  = document.getElementById("input-bridge-url");
  const btnSaveBridge   = document.getElementById("btn-save-bridge");
  const tipBox          = document.getElementById("tip-box");

  const inputTestMsg    = document.getElementById("input-test-msg");
  const btnSendTest     = document.getElementById("btn-send-test");
  const historyList     = document.getElementById("history-list");
  const btnClearHistory = document.getElementById("btn-clear-history");
  const btnRefresh      = document.getElementById("btn-refresh");

  let activeCode = null;

  // ─── Tab Switching ────────────────────────────────────────────────────────
  document.querySelectorAll(".tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      btn.classList.add("active");
      const tabId = "tab-" + btn.getAttribute("data-tab");
      const target = document.getElementById(tabId);
      if (target) target.classList.add("active");
    });
  });

  // ─── Refresh Status ───────────────────────────────────────────────────────
  function refreshStatus() {
    chrome.runtime.sendMessage({ action: "get_status" }, (res) => {
      if (chrome.runtime.lastError || !res) {
        pillStatus.className = "bridge-status-pill offline";
        txtStatus.textContent = "Offline";
        valPing.textContent = "—";
        return;
      }

      // 1. Trạng thái Python Bridge & Ping
      if (res.bridgeOk) {
        pillStatus.className = "bridge-status-pill online";
        txtStatus.textContent = "Online";
        valPing.textContent = res.lastPingMs > 0 ? `${res.lastPingMs}ms` : "< 1ms";
        valPing.style.color = "#00e5a0";
      } else {
        pillStatus.className = "bridge-status-pill offline";
        txtStatus.textContent = "Chưa kết nối";
        valPing.textContent = "Timeout";
        valPing.style.color = "#ef4444";
      }

      // 2. Trạng thái Google Meet
      activeCode = res.activeMeetCode;
      if (res.activeMeetCode) {
        badgeMeet.textContent = "Đang trong phòng";
        badgeMeet.className = "badge active";
        txtMeetCode.textContent = res.activeMeetCode;
        btnCopyCode.style.display = "inline-flex";
      } else {
        badgeMeet.textContent = "Chưa có cuộc họp";
        badgeMeet.className = "badge";
        txtMeetCode.textContent = "—";
        btnCopyCode.style.display = "none";
      }

      // 3. Metrics
      valSentCount.textContent = res.messagesSentCount || 0;

      // 4. Config & Switches
      if (res.config) {
        toggleAutoChat.checked = Boolean(res.config.autoChatEnabled);
        toggleOverlay.checked  = Boolean(res.config.overlayEnabled);
        toggleBadge.checked    = Boolean(res.config.showBadge);
        if (document.activeElement !== inputBridgeUrl) {
          inputBridgeUrl.value = res.config.bridgeUrl || "http://localhost:9877";
        }
      }

      // 5. History Feed
      renderHistory(res.history || []);
    });
  }

  // ─── Render History ───────────────────────────────────────────────────────
  function renderHistory(items) {
    if (!items || items.length === 0) {
      historyList.innerHTML = `<div class="history-empty">Chưa có tin nhắn nào được gửi trong phiên này.</div>`;
      return;
    }

    historyList.innerHTML = items.map(item => `
      <div class="history-item">
        <div class="history-item-meta">
          <span>🕒 ${item.time || ''}</span>
          <span>${item.meetCode ? 'Meet: ' + item.meetCode : 'Meet'}</span>
        </div>
        <div class="history-item-text">${escapeHtml(item.text || '')}</div>
      </div>
    `).join('');
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ─── Event Handlers ───────────────────────────────────────────────────────

  // Lưu Config khi thay đổi toggle switches
  function onConfigChange() {
    const newConfig = {
      autoChatEnabled: toggleAutoChat.checked,
      overlayEnabled:  toggleOverlay.checked,
      showBadge:       toggleBadge.checked,
    };
    chrome.runtime.sendMessage({ action: "save_settings", config: newConfig });
  }

  toggleAutoChat.addEventListener("change", onConfigChange);
  toggleOverlay.addEventListener("change", onConfigChange);
  toggleBadge.addEventListener("change", onConfigChange);

  // Lưu Bridge URL
  btnSaveBridge.addEventListener("click", () => {
    let url = inputBridgeUrl.value.trim().replace(/\/+$/, "");
    if (!url) url = "http://localhost:9877";
    inputBridgeUrl.value = url;

    tipBox.textContent = "Đang kiểm tra kết nối tới " + url + "...";
    tipBox.style.color = "#38bdf8";

    chrome.runtime.sendMessage({ action: "save_settings", config: { bridgeUrl: url } }, () => {
      chrome.runtime.sendMessage({ action: "test_connection" }, (res) => {
        if (res && res.bridgeOk) {
          tipBox.textContent = `✅ Kết nối thành công! Độ trễ: ${res.lastPingMs}ms`;
          tipBox.style.color = "#00e5a0";
        } else {
          tipBox.textContent = "❌ Không thể kết nối. Hãy chắc chắn Meeting AI app đang mở.";
          tipBox.style.color = "#ef4444";
        }
        refreshStatus();
      });
    });
  });

  // Gửi test message
  btnSendTest.addEventListener("click", () => {
    const text = inputTestMsg.value.trim();
    if (!text) return;

    btnSendTest.disabled = true;
    btnSendTest.textContent = "Đang gửi...";

    chrome.runtime.sendMessage({ action: "send_test_chat", text }, (res) => {
      btnSendTest.disabled = false;
      btnSendTest.textContent = "Gửi";

      if (res && res.ok) {
        refreshStatus();
      } else {
        alert(res?.error || "Không thể gửi vào Meet. Hãy kiểm tra xem tab Google Meet có đang mở không.");
      }
    });
  });

  // Copy mã cuộc họp
  btnCopyCode.addEventListener("click", () => {
    if (!activeCode) return;
    navigator.clipboard.writeText(activeCode).then(() => {
      btnCopyCode.textContent = "✓";
      setTimeout(() => btnCopyCode.textContent = "📋", 1500);
    });
  });

  // Mở tab Google Meet
  btnOpenMeet.addEventListener("click", () => {
    if (activeCode) {
      chrome.tabs.create({ url: `https://meet.google.com/${activeCode}` });
    } else {
      chrome.tabs.create({ url: "https://meet.google.com" });
    }
  });

  // Xóa lịch sử
  btnClearHistory.addEventListener("click", () => {
    chrome.runtime.sendMessage({ action: "clear_history" }, () => {
      refreshStatus();
    });
  });

  // Nút làm mới
  btnRefresh.addEventListener("click", () => {
    refreshStatus();
  });

  // Tự động làm mới mỗi 2.5s khi popup đang mở
  refreshStatus();
  setInterval(refreshStatus, 2500);
});
