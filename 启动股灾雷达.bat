@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ================================================
echo   股灾雷达
echo ================================================
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没找到 Python。请先安装 Python 3.9 以上：https://www.python.org/downloads/
  echo        安装时勾选 "Add Python to PATH"
  pause
  exit /b 1
)
python -c "import pandas,numpy,requests,xlrd" 2>nul
if errorlevel 1 (
  echo 第一次运行，正在安装依赖库 ...
  python -m pip install -r requirements.txt
)
python run.py
pause
