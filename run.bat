@echo off
REM Включи окружение переменных
setlocal enabledelayedexpansion

REM Переходи в папку бота
cd /d %~dp0

REM Проверь, что .venv существует
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

REM Активируй окружение
call .venv\Scripts\activate.bat

REM Установи токен (замени на свой!)
set BOT_TOKEN=8649792155:AAG8XLHaTZTuRIg9JuIakqvLOoximP1mM-c

REM Запусти бота
python bot.py

pause