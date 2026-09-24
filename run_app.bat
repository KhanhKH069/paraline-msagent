@echo off
chcp 65001 >nul
echo ===================================================
echo   Meeting AI Assistant — Starting Client GUI...
echo ===================================================

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Không tìm thấy môi trường ảo .venv!
    echo Vui lòng tạo venv hoặc cài đặt thư viện trước.
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m client.ui.main_app
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Ứng dụng thoát với mã lỗi: %errorlevel%
    pause
)
