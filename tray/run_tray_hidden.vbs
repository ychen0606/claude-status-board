' Start the tray app in the background with no console window.
' Put a shortcut to this file in shell:startup for autostart at login.
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
sh.Run "pythonw.exe """ & here & "\claude_board_tray.py""", 0, False
