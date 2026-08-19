<#
.SYNOPSIS
  Registers the ibagent scheduled tasks on Windows (run in an elevated PowerShell).

  IBAgent-Supervisor  at logon, restarts on failure every minute, no run-time limit
  IBAgent-Watchdog    every 5 minutes, independent process: heartbeat -> alert if stale
  IBAgent-Gateway     (optional) at logon: IBC start script for IB Gateway auto-login

  All tasks run "only when user is logged on": IB Gateway is a GUI app and Claude Code's
  OAuth login lives in this user's profile. Keep the PC awake (-DisableSleep) and auto-logon
  or leave the session locked, not logged out.

.EXAMPLE
  .\install_tasks.ps1 -RepoDir C:\Users\me\ibkr-agent -PythonExe C:\Users\me\ibkr-agent\.venv\Scripts\python.exe `
      -IbcStartScript C:\IBC\StartGateway.bat -DisableSleep
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $RepoDir,
    [Parameter(Mandatory)] [string] $PythonExe,
    [string] $IbcStartScript = "",
    [switch] $DisableSleep,
    [switch] $Uninstall
)
$ErrorActionPreference = "Stop"
$tasks = @("IBAgent-Supervisor", "IBAgent-Watchdog", "IBAgent-Gateway")

if ($Uninstall) {
    foreach ($t in $tasks) { Unregister-ScheduledTask -TaskName $t -Confirm:$false -ErrorAction SilentlyContinue }
    Write-Host "ibagent tasks removed"; exit 0
}
if (-not (Test-Path $RepoDir)) { throw "RepoDir not found: $RepoDir" }
if (-not (Test-Path $PythonExe)) { throw "PythonExe not found: $PythonExe" }
$pythonw = Join-Path (Split-Path $PythonExe) "pythonw.exe"
if (-not (Test-Path $pythonw)) { $pythonw = $PythonExe }
$mandate = Join-Path $RepoDir "mandate.yaml"
$user = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$noLimit = New-TimeSpan -Days 3650

# --- Supervisor: the single long-running engine process ---
$supAction = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "-m ibagent supervise --mandate `"$mandate`"" -WorkingDirectory $RepoDir
$supTrigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$supSettings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit $noLimit -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "IBAgent-Supervisor" -Action $supAction -Trigger $supTrigger `
    -Settings $supSettings -Principal $principal -Force | Out-Null

# --- Watchdog: never touches the broker; only reads the heartbeat and alerts ---
$wdAction = New-ScheduledTaskAction -Execute $pythonw `
    -Argument "-m ibagent watchdog --mandate `"$mandate`"" -WorkingDirectory $RepoDir  # pythonw:
    # a console python.exe here flashes a cmd window every 5 minutes on the user's desktop
$wdTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5)
$wdSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "IBAgent-Watchdog" -Action $wdAction -Trigger $wdTrigger `
    -Settings $wdSettings -Principal $principal -Force | Out-Null

# --- Optional: IB Gateway via IBC (auto-login + daily restart handled by IBC's config.ini) ---
if ($IbcStartScript) {
    if (-not (Test-Path $IbcStartScript)) { throw "IbcStartScript not found: $IbcStartScript" }
    $gwAction = New-ScheduledTaskAction -Execute $IbcStartScript -WorkingDirectory (Split-Path $IbcStartScript)
    $gwTrigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $gwSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit $noLimit -StartWhenAvailable `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName "IBAgent-Gateway" -Action $gwAction -Trigger $gwTrigger `
        -Settings $gwSettings -Principal $principal -Force | Out-Null
}

if ($DisableSleep) {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /change monitor-timeout-ac 10
}

$repoGlob = "//" + ($RepoDir -replace "\\", "/") + "/**"
Write-Host "Tasks registered for $user."
Write-Host "Add to mandate.yaml -> llm.sandbox.deny_read_globs:  [`"$repoGlob`", `"//$($env:LOCALAPPDATA -replace '\\','/')/ibagent/data/**`"]"
Write-Host "Verify in Phase 5: the sandboxed run must be DENIED reading a file under the repo."
