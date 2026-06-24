@echo off
chcp 65001 >nul
echo.
echo   =====================================
echo     🎓 downloader
echo   =====================================
echo.
echo   1. 下载默认课程 (95383)
echo   2. 输入课程 ID 下载
echo   3. 列出我已注册的课程
echo   4. 扫描发现课程 (95000-100000)
echo.
set /p choice="  请选择 [1-4]: "

if "%choice%"=="1" python main.py
if "%choice%"=="2" (
    set /p cid="  课程 ID: "
    python main.py %cid%
)
if "%choice%"=="3" python main.py --list
if "%choice%"=="4" python main.py --discover

pause
