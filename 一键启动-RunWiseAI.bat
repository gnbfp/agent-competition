@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===========================================
echo RunWise AI - 一键启动网页版
 echo 需要 Python 3.12 / 3.13 和现代浏览器
 echo ===========================================
where py >nul 2>nul
if not errorlevel 1 (
  py -3.12 -V >nul 2>nul
  if not errorlevel 1 (
    py -3.12 tools\launch_runwise.py
    goto end
  )
)
where python >nul 2>nul
if errorlevel 1 (
  echo 未检测到 Python，请先安装 Python 3.12。
  pause
  exit /b 1
)
python tools\launch_runwise.py
:end
echo 按任意键关闭窗口。
pause >nul
