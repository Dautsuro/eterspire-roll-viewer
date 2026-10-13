@echo off
rem Builds dist\EterspireRollViewer.exe, a single file players can run without installing Python.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (py -3 -m venv .venv 2>nul || python -m venv .venv)
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller || exit /b 1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name EterspireRollViewer ^
    --add-data "roll_viewer\data;roll_viewer\data" ^
    --add-data "roll_viewer\assets;roll_viewer\assets" ^
    --icon roll_viewer\assets\icon.ico --hidden-import pystray._win32 --collect-submodules winrt ^
    run.py || exit /b 1
echo.
echo Done: dist\EterspireRollViewer.exe
