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
set "choice="
set /p choice="  请选择 [1-4]: "

if "%choice%"=="1" python main.py 95383
if "%choice%"=="2" goto input_course
if "%choice%"=="3" python main.py
if "%choice%"=="4" goto discover
goto end

:input_course
set "cid="
set /p cid="  课程 ID: "
python main.py %cid%
goto end

:discover
set "range="
set /p range="  扫描范围 (直接回车使用 95000-100000): "
if "%range%"=="" set range=95000-100000
python main.py --discover %range%
goto end

:end
pause
