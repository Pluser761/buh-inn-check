@echo off
rem Сборка CheckINN.exe под Windows. Нужен установленный Python 3.10+ (python.org, с галочкой "Add to PATH").
chcp 65001 >nul
cd /d "%~dp0"

python -m venv .build-venv || goto :error
call .build-venv\Scripts\activate.bat
python -m pip install --upgrade pip || goto :error
pip install -r requirements.txt pyinstaller || goto :error

pyinstaller --noconfirm --clean --onefile --windowed --name CheckINN gui.py || goto :error

echo.
echo Готово: dist\CheckINN.exe
pause
exit /b 0

:error
echo.
echo Сборка не удалась.
pause
exit /b 1
