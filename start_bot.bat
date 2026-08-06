@echo off
REM ============================================================
REM  WhatsApp auto-reply bot launcher
REM
REM  Runs the bot from the project's venv, logs to logs\, and
REM  restarts it if it crashes.
REM
REM    start_bot.bat          normal (waits for the network first)
REM    start_bot.bat nowait   skip the startup delay
REM    run_hidden.vbs         same thing with no console window
REM
REM  Stop it with stop_bot.bat.
REM ============================================================

cd /d "%~dp0"

REM Emoji in chat names crash the default cp1252 encoding as soon as output is
REM redirected to a file. Force UTF-8 everywhere.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
chcp 65001 >nul

if not exist "logs" mkdir "logs"

REM On a fresh boot Windows starts autostart items before wifi is up, and the
REM first API call dies with a DNS error. "ping" rather than "timeout" because
REM timeout needs a console handle and fails when launched hidden.
if /i not "%~1"=="nowait" (
  ping -n 26 127.0.0.1 >nul 2>&1
)

:loop

REM Recomputed every cycle -- if this is built once before the loop, a bot
REM running past midnight keeps writing to yesterday's file.
for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value 2^>nul') do set dt=%%I
if not defined dt set dt=00000000
set LOGFILE=logs\bot_%dt:~0,4%-%dt:~4,2%-%dt:~6,2%.log

echo. >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"
echo  Started %date% %time% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

REM -u = unbuffered, so the log updates live instead of in chunks
".venv\Scripts\python.exe" -u bot.py >> "%LOGFILE%" 2>&1
set EXITCODE=%ERRORLEVEL%

REM Exit code 3 means "another bot is already running". Restarting would just
REM loop forever hitting the same lock, so stop here.
if "%EXITCODE%"=="3" (
  echo Another instance is already running -- not restarting. >> "%LOGFILE%"
  goto :done
)

echo Bot exited %time% with code %EXITCODE%, restarting in 15s >> "%LOGFILE%"
ping -n 16 127.0.0.1 >nul 2>&1
goto loop

:done
