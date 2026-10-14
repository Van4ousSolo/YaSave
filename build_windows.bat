@echo off
chcp 65001 > nul
echo ========================================================
echo        YaSave — Сборка EXE для Windows
echo ========================================================
echo.

if not exist .venv\Scripts\python.exe (
    echo [ОШИБКА] Виртуальное окружение .venv не найдено!
    pause
    exit /b 1
)

echo [1/3] Проверка PyInstaller...
.venv\Scripts\python.exe -m PyInstaller --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Установка PyInstaller в .venv...
    .venv\Scripts\pip.exe install pyinstaller
)

echo [2/3] Запуск сборки YaSave.exe...
.venv\Scripts\python.exe -m PyInstaller ^
    --noconfirm ^
    --onedir ^
    --windowed ^
    --add-data "web;web" ^
    --add-data "assets;assets" ^
    --icon "assets/icon.png" ^
    --name "YaSave" ^
    main.py

if %errorlevel% equ 0 (
    echo.
    echo ========================================================
    echo [УСПЕХ] Сборка успешно завершена!
    echo Готовое приложение находится в папке:
    echo %cd%\dist\YaSave\YaSave.exe
    echo ========================================================
) else (
    echo.
    echo [ОШИБКА] Во время сборки произошла ошибка.
)

pause
