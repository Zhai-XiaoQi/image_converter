Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
script = folder & "\image_converter_gui.py"

cmd = "pyw -3 " & Chr(34) & script & Chr(34)
rc = shell.Run(cmd, 0, False)
