' ============================================================
'  Starts the bot with NO console window.
'
'  Windows batch files always open a black cmd window. This
'  wrapper launches the same batch file with the window state
'  set to 0 (hidden), so it runs silently in the background.
'
'  Put a shortcut to THIS file in shell:startup for a truly
'  invisible autostart.
'
'  Output still goes to logs\bot_YYYY-MM-DD.log -- that's your
'  only window into what it's doing, so check it if something
'  seems wrong.
'
'  To stop it: run stop_bot.bat, or Task Manager -> python.exe
' ============================================================

Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")

folder = fso.GetParentFolderName(WScript.ScriptFullName)

' 0 = hidden window, False = don't wait for it to finish
shell.Run """" & folder & "\start_bot.bat""", 0, False
