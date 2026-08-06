@echo off
REM ============================================================
REM  Stops the bot and everything it left running.
REM
REM  Order matters: kill the restart loops FIRST, otherwise they
REM  just relaunch the bot 15 seconds after you kill it.
REM ============================================================

echo Stopping the bot...
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
wmic process where "name='chrome.exe' and commandline like '%%MegaProject2\\chrome_profile%%'" delete >nul 2>&1

REM Clear any lock the killed Chrome left behind
if exist "%~dp0chrome_profile\SingletonLock"   del /f /q "%~dp0chrome_profile\SingletonLock"   >nul 2>&1
if exist "%~dp0chrome_profile\SingletonCookie" del /f /q "%~dp0chrome_profile\SingletonCookie" >nul 2>&1
if exist "%~dp0chrome_profile\SingletonSocket" del /f /q "%~dp0chrome_profile\SingletonSocket" >nul 2>&1

echo.
echo Checking nothing survived...
timeout /t 2 /nobreak >nul
wmic process where "name='python.exe' and commandline like '%%bot.py%%'" get processid 2>nul | find /i "ProcessId" >nul && (
  echo   WARNING: a bot process is still alive. Use Task Manager.
) || (
  echo   Clean. Your normal Chrome is untouched.
)

echo.
pause
