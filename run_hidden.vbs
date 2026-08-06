' ============================================================
'  Starts the bot with NO console window.
'
'  A .bat always opens a black cmd window. This launches the same
'  batch file with window style 0 (hidden), so it runs silently.
'
'  Put a shortcut to THIS file in shell:startup for an invisible
'  autostart.
'
'  Output goes to logs\bot_YYYY-MM-DD.log -- with no console that
'  log is your only window into what it's doing.
'
'  Stop it with stop_bot.bat.
' ============================================================

Option Explicit

Dim shell, fso, folder, batPath

Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")

folder  = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = fso.BuildPath(folder, "start_bot.bat")

If Not fso.FileExists(batPath) Then
    ' Only surfaces if something is genuinely wrong -- otherwise this script
    ' is completely silent by design.
    MsgBox "start_bot.bat not found in:" & vbCrLf & folder, _
           vbExclamation, "WhatsApp bot"
    WScript.Quit 1
End If

' Quote the path so folders with spaces still work.
' 0 = hidden window, False = don't wait for it to finish.
shell.Run """" & batPath & """", 0, False
