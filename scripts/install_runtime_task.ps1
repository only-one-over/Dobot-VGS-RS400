<#
.SYNOPSIS
    [已废弃] 注册 Windows 计划任务方式的 Runtime 部署。

.DESCRIPTION
    此脚本为遗留脚本，推荐改用 install_windows_services.ps1 部署 WinSW 服务方式。
    新的 WinSW 服务部署提供更好的进程管理、失败重启和看门狗机制。
    新安装流程会自动备份并禁用由此脚本创建的计划任务。
#>
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

$RuntimeModuleFile = Join-Path $ProjectRoot "dobot_move\runtime\runtime_agent.py"
if (-not (Test-Path $RuntimeModuleFile)) {
    $RuntimeModuleFile = Join-Path $ProjectRoot "dobot_move\runtime_agent.py"
    if (-not (Test-Path $RuntimeModuleFile)) {
        throw "dobot_move.runtime_agent not found under ProjectRoot: $ProjectRoot"
    }
}
$WatchdogModuleFile = Join-Path $ProjectRoot "dobot_move\runtime\runtime_watchdog.py"
if (-not (Test-Path $WatchdogModuleFile)) {
    $WatchdogModuleFile = Join-Path $ProjectRoot "dobot_move\runtime_watchdog.py"
    if (-not (Test-Path $WatchdogModuleFile)) {
        throw "dobot_move.runtime_watchdog not found under ProjectRoot: $ProjectRoot"
    }
}

$arguments = "-m dobot_move.runtime.runtime_agent --startup-delay $StartupDelaySeconds"
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

$watchdogArguments = "-m dobot_move.runtime.runtime_watchdog --task-name `"$TaskName`""
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
Write-Host "Module:      dobot_move.runtime.runtime_agent"
Write-Host "Arguments:   $arguments"
Write-Host "Watchdog:    dobot_move.runtime.runtime_watchdog"
