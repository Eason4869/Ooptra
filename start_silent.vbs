' ===================================================================
'  Ooptra - silent launcher
'  Place this file in the project root, next to main.py.
'
'  Double-click        -> starts immediately, no window shown
'  Startup shortcut    -> passes "delay", waits START_DELAY_SECONDS
'
'  NOTE: this file is intentionally ASCII-only. Windows Script Host
'  reads .vbs as ANSI, so non-ASCII text here would be garbled.
'  Keep it ASCII if you edit it.
' ===================================================================

Option Explicit

' Seconds to wait before launch when started with the "delay" argument.
' Raise this if the bot cannot reach Oopz right after boot.
Const START_DELAY_SECONDS = 30

Dim shell, fso, baseDir, pythonExe, logDir, stdoutLog
Dim cmd, wql, delaySeconds

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

baseDir   = fso.GetParentFolderName(WScript.ScriptFullName)
pythonExe = baseDir & "\.venv\Scripts\python.exe"
logDir    = baseDir & "\logs"
stdoutLog = logDir & "\autostart_stdout.log"

If Not fso.FileExists(pythonExe) Then
    MsgBox "Virtualenv python not found:" & vbCrLf & pythonExe & vbCrLf & vbCrLf & _
           "Check that .venv exists under " & baseDir, _
           vbCritical, "Ooptra - cannot start"
    WScript.Quit 1
End If

If Not fso.FolderExists(logDir) Then fso.CreateFolder logDir

' Single-instance guard: skip if this project's python is already running.
wql = "SELECT ProcessId FROM Win32_Process WHERE Name='python.exe'" & _
      " AND ExecutablePath='" & Replace(pythonExe, "\", "\\") & "'"
If IsRunning(wql) Then WScript.Quit 0

delaySeconds = 0
If WScript.Arguments.Unnamed.Count > 0 Then
    If LCase(Trim(WScript.Arguments.Unnamed(0))) = "delay" Then
        delaySeconds = START_DELAY_SECONDS
    End If
End If
If delaySeconds > 0 Then WScript.Sleep delaySeconds * 1000

' Window style 0 = hidden. cmd /c is only here to capture stray
' stdout/stderr; the bot's own logging still goes to logs\oopz_bot.log.
shell.CurrentDirectory = baseDir
cmd = "cmd /c " & Q(Q(pythonExe) & " main.py > " & Q(stdoutLog) & " 2>&1")
shell.Run cmd, 0, False


' Wrap a string in double quotes.
Function Q(s)
    Q = """" & s & """"
End Function

' True when a process matching the WQL query exists.
' Fails open: if WMI is unavailable we allow the start rather than block it.
Function IsRunning(query)
    Dim wmi, procs
    IsRunning = False
    On Error Resume Next
    Set wmi = GetObject("winmgmts:\\.\root\cimv2")
    If Err.Number = 0 Then
        Set procs = wmi.ExecQuery(query)
        If Err.Number = 0 Then
            If procs.Count > 0 Then IsRunning = True
        End If
    End If
    Err.Clear
    On Error GoTo 0
End Function
