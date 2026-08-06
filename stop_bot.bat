@echo off
REM ============================================================
REM  Stops the bot and everything it left running.
REM
REM  Order matters: kill the restart loops FIRST, otherwise they
REM  relaunch the bot 15 seconds after you kill it.
REM ============================================================

setlocal
REM Folder name is read at runtime, so renaming the project doesn't
REM silently stop this script from finding the bot's Chrome.
for %%I in ("%~dp0.") do set "PROJDIR=%%~nxI"

echo Stopping the bot in "%PROJDIR%"...
echo.

echo [1/4] restart loops (start_bot.bat)
wmic process where "name='cmd.exe' and commandline like '%%start_bot%%'" delete >nul 2>&1

echo [2/4] hidden launchers (run_hidden.vbs)
wmic process where "name='wscript.exe' and commandline like '%%run_hidden%%'" delete >nul 2>&1
wmic process where "name='cscript.exe' and commandline like '%%run_hidden%%'" delete >nul 2>&1

echo [3/4] the bot itself (python bot.py)
wmic process where "name='python.exe' and commandline like '%%bot.py%%'" delete >nul 2>&1

echo [4/4] chromedriver and the browser it opened
taskkill /F /IM chromedriver.exe >nul 2>&1
REM Match on the profile folder so ONLY the bot's Chrome dies, never yours.
wmic process where "name='chrome.exe' and commandline like '%%%PROJDIR%%%'" delete >nul 2>&1
wmic process where "name='chrome.exe' and commandline like '%%chrome_profile%%'" delete >nul 2>&1

REM Clear any lock the killed Chrome left behind
if exist "%~dp0chrome_profile\SingletonLock"   del /f /q "%~dp0chrome_profile\SingletonLock"   >nul 2>&1
if exist "%~dp0chrome_profile\SingletonCookie" del /f /q "%~dp0chrome_profile\SingletonCookie" >nul 2>&1
if exist "%~dp0chrome_profile\SingletonSocket" del /f /q "%~dp0chrome_profile\SingletonSocket" >nul 2>&1

echo.
echo Verifying...
timeout /t 2 /nobreak >nul

set "ALIVE="
for /f %%A in ('wmic process where "name='python.exe' and commandline like '%%bot.py%%'" get processid 2^>nul ^| find /c "="') do set ALIVE=%%A

wmic process where "name='python.exe' and commandline like '%%bot.py%%'" get processid 2>nul | findstr /r "[0-9]" >nul && (
  echo   WARNING: a bot process survived. Use Task Manager.
) || (
  echo   Bot stopped.
)

wmic process where "name='chrome.exe' and commandline like '%%chrome_profile%%'" get processid 2>nul | findstr /r "[0-9]" >nul && (
  echo   WARNING: the bot's Chrome is still open. Close that window manually.
) || (
  echo   Bot's Chrome closed. Your normal Chrome is untouched.
)

echo.
pause
