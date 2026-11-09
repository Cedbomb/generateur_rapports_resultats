@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\pythonw.exe" goto lancer

where py >nul 2>nul
if %errorlevel%==0 (set "PYTHON=py -3") else (set "PYTHON=python")

echo Premiere utilisation : installation des dependances...
%PYTHON% -m venv .venv
if errorlevel 1 goto erreur
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 goto erreur

:lancer
start "" ".venv\Scripts\pythonw.exe" generateur_meq_gui.py
exit /b 0

:erreur
if exist ".venv" rmdir /s /q ".venv"
echo.
echo L'installation a echoue. Verifiez que Python 3.10 ou plus recent est installe.
pause
exit /b 1
