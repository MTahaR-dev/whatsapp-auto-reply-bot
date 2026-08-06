@echo off
REM ============================================================
REM  WhatsApp auto-reply bot launcher
REM
REM  Runs the bot from the project's venv, logs everything to
REM  logs\, and restarts automatically if it crashes.
REM
REM  Run this directly to watch it in a console window.
REM  Run run_hidden.vbs to start it with NO console window.
REM
REM  To stop a hidden one: Task Manager -> end python.exe
REM  (or run stop_bot.bat)
REM ============================================================

cd /d "%~dp0"

REM Emoji in chat names crash the default Windows cp1252 encoding the moment
REM output is redirected to a file. Force UTF-8 everywhere.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
chcp 65001 >nul

if not exist "logs" mkdir "logs"

REM Build a dated log filename: logs\bot_2026-08-06.log
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set dt=%%I
set LOGFILE=logs\bot_%dt:~0,4%-%dt:~4,2%-%dt:~6,2%.log

REM On a fresh boot Windows launches startup items before wifi is up,
REM and the first API call would die with a DNS error. Wait it out.
timeout /t 25 /nobreak >nul

:loop
echo. >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo  Started %date% %time% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

REM Unbuffered (-u) so the log updates live instead of in chunks
".venv\Scripts\python.exe" -u bot.py >> "%LOGFILE%" 2>&1

echo Bot exited %time%, restarting in 15s >> "%LOGFILE%"
timeout /t 15 /nobreak >nul
goto loop
