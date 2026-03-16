/**
 * chrome_extension/popup.js
 * Lấy status từ background.js và hiển thị
 */

document.addEventListener("DOMContentLoaded", () => {
    const badgeBridge = document.getElementById("badge-bridge");
    const badgeMeet   = document.getElementById("badge-meet");
    const rowCode     = document.getElementById("meet-code-row");
    const txtCode     = document.getElementById("meet-code");
    const tipText     = document.getElementById("tip-text");
  
    // Gửi message tới background để lấy trạng thái
    chrome.runtime.sendMessage({ action: "get_status" }, (res) => {
      if (chrome.runtime.lastError || !res) {
        badgeBridge.textContent = "Error";
        badgeBridge.className = "badge badge-err";
        return;
      }
  
      // Trạng thái Bridge
      if (res.bridgeOk) {
        badgeBridge.textContent = "Connected";
        badgeBridge.className = "badge badge-ok";
      } else {
        badgeBridge.textContent = "Disconnected";
        badgeBridge.className = "badge badge-err";
        tipText.textContent = "Không thể kết nối Python app. Hãy chắc chắn Paraline MS Agent đang chạy.";
        tipText.style.color = "#ff9800";
      }
  
      // Trạng thái Meet
      if (res.activeMeetCode) {
        badgeMeet.textContent = "Active";
        badgeMeet.className = "badge badge-meeting";
        rowCode.style.display = "flex";
        txtCode.textContent = res.activeMeetCode;
        if (res.bridgeOk) {
            tipText.textContent = "Đang trong phiên dịch. Phụ đề sẽ hiển thị ở cửa sổ Paraline MS Agent.";
            tipText.style.color = "#4caf50";
        }
      } else {
        badgeMeet.textContent = "Idle";
        badgeMeet.className = "badge badge-idle";
        rowCode.style.display = "none";
      }
    });
  });
