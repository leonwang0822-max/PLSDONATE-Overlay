@echo off
echo Building PLS DONATE Overlay EXE...
echo Cleaning previous builds...
rmdir /s /q build dist
echo.
echo Building with PyInstaller...
pyinstaller --noconfirm --onefile --windowed --name "PLS DONATE Overlay" --add-data "templates;templates" --add-data "static;static" --hidden-import="PyQt6.QtWebEngineCore" --hidden-import="PyQt6.QtWebEngineWidgets" app.py
echo.
echo Build complete! The executable is in the 'dist' folder.
pause
