param(
    [string]$ProjectRoot = "C:\DobotRuntime",
    [switch]$StartLegacyTasks
)

. (Join-Path $PSScriptRoot "windows_service_common.ps1")
Assert-Administrator
$resolvedRoot = Resolve-DobotProjectRoot -ProjectRoot $ProjectRoot
& (Join-Path $PSScriptRoot "uninstall_windows_services.ps1") `
    -ProjectRoot $resolvedRoot

$backupDirectory = Join-Path (
    Split-Path -Parent (Get-DobotServiceDirectory)
) "scheduled-task-backup"
Restore-LegacyTasks `
    -BackupDirectory $backupDirectory `
    -Start:$StartLegacyTasks

Write-Host "Rollback complete. Legacy scheduled task states are restored."
