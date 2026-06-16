param(
    [string]$TaskName = "DobotRuntimeAgent",
    [string]$ProjectRoot = "",
    [string]$PythonExe = "",
    [int]$StartupDelaySeconds = 20
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

$RuntimeScript = Join-Path $ProjectRoot "runtime_agent.py"
if (-not (Test-Path $RuntimeScript)) {
    throw "runtime_agent.py not found under ProjectRoot: $ProjectRoot"
}

$arguments = "`"$RuntimeScript`" --startup-delay $StartupDelaySeconds"
$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $arguments -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host "Registered scheduled task '$TaskName'"
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "PythonExe:   $PythonExe"
Write-Host "Script:      $RuntimeScript"
Write-Host "Arguments:   $arguments"
