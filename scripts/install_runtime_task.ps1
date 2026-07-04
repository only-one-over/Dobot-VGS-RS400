param(
    [string]$TaskName = "DobotRuntimeAgent",
    [string]$WatchdogTaskName = "DobotRuntimeWatchdog",
    [string]$ProjectRoot = "",
    [string]$PythonExe = "",
    [int]$StartupDelaySeconds = 0
)

if (-not $ProjectRoot) {
    $ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
}

if (-not $PythonExe) {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $PythonExe = $venvPython
    } else {
        $PythonExe = "python"
    }
}

$RuntimeModuleFile = Join-Path $ProjectRoot "dobot_move\runtime_agent.py"
if (-not (Test-Path $RuntimeModuleFile)) {
    throw "dobot_move.runtime_agent not found under ProjectRoot: $ProjectRoot"
}
$WatchdogModuleFile = Join-Path $ProjectRoot "dobot_move\runtime_watchdog.py"
if (-not (Test-Path $WatchdogModuleFile)) {
    throw "dobot_move.runtime_watchdog not found under ProjectRoot: $ProjectRoot"
}

$arguments = "-m dobot_move.runtime_agent --startup-delay $StartupDelaySeconds"
$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $arguments -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force

$watchdogArguments = "-m dobot_move.runtime_watchdog --task-name `"$TaskName`""
$watchdogAction = New-ScheduledTaskAction -Execute $PythonExe -Argument $watchdogArguments -WorkingDirectory $ProjectRoot
$watchdogSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $WatchdogTaskName `
    -Action $watchdogAction `
    -Trigger $trigger `
    -Settings $watchdogSettings `
    -RunLevel Highest `
    -Force

Write-Host "Registered scheduled task '$TaskName'"
Write-Host "Registered watchdog task '$WatchdogTaskName'"
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "PythonExe:   $PythonExe"
Write-Host "Module:      dobot_move.runtime_agent"
Write-Host "Arguments:   $arguments"
Write-Host "Watchdog:    dobot_move.runtime_watchdog"
