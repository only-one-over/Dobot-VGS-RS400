param(
    [string]$ProjectRoot = "C:\DobotRuntime",
    [switch]$EnableLegacyTasks,
    [switch]$StartLegacyTasks,
    [switch]$RemoveToken
)

. (Join-Path $PSScriptRoot "windows_service_common.ps1")
Assert-Administrator
$ProjectRoot = Resolve-DobotProjectRoot -ProjectRoot $ProjectRoot
$serviceDirectory = Get-DobotServiceDirectory

Stop-And-UninstallServiceWrapper -Executable (
    Join-Path $serviceDirectory "DobotRuntimeWatchdog.exe"
)
Stop-And-UninstallServiceWrapper -Executable (
    Join-Path $serviceDirectory "DobotRuntimeService.exe"
)

if ($EnableLegacyTasks -or $StartLegacyTasks) {
    Enable-LegacyTasks -Start:$StartLegacyTasks
}
if ($RemoveToken) {
    $config = Get-Content -LiteralPath (
        Join-Path $ProjectRoot "dobot_move\config.json"
    ) -Raw | ConvertFrom-Json
    $tokenPath = Join-Path $ProjectRoot "runtime_ipc.token"
    if (
        $config.runtime -and
        $config.runtime.PSObject.Properties.Name -contains "ipc_token_path"
    ) {
        $configuredTokenPath = [string]$config.runtime.ipc_token_path
        $tokenPath = if ([IO.Path]::IsPathRooted($configuredTokenPath)) {
            $configuredTokenPath
        } else {
            Join-Path $ProjectRoot $configuredTokenPath
        }
    }
    Remove-Item -LiteralPath $tokenPath -Force -ErrorAction SilentlyContinue
}

Write-Host "Dobot Windows services uninstalled."
