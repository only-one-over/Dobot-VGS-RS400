param(
    [string]$ProjectRoot = "C:\DobotRuntime",
    [string]$PythonExe = ""
)

. (Join-Path $PSScriptRoot "windows_service_common.ps1")
$ProjectRoot = Resolve-DobotProjectRoot -ProjectRoot $ProjectRoot
$PythonExe = Resolve-DobotPython -ProjectRoot $ProjectRoot -PythonExe $PythonExe
$serviceDirectory = Get-DobotServiceDirectory
$vendorBinary = Join-Path $ProjectRoot (
    "dobot_move\windows_service\vendor\WinSW-x64.exe"
)

& $PythonExe -c (
    "from dobot_move.windows_service.service_config import " +
    "verify_winsw_binary; import sys; " +
    "sys.exit(0 if verify_winsw_binary(r'$vendorBinary') else 1)"
)
if ($LASTEXITCODE -ne 0) {
    throw "WinSW SHA256 verification failed."
}

$runtime = Get-Service -Name $script:RuntimeServiceName -ErrorAction Stop
$watchdog = Get-Service -Name $script:WatchdogServiceName -ErrorAction Stop
if ($runtime.Status -ne "Running") {
    throw "$($script:RuntimeServiceName) is not running."
}
if ($watchdog.Status -ne "Running") {
    throw "$($script:WatchdogServiceName) is not running."
}

$config = Get-Content -LiteralPath (
    Join-Path $ProjectRoot "dobot_move\config.json"
) -Raw | ConvertFrom-Json
$healthPath = Join-Path $ProjectRoot "runtime_health.json"
if (
    $config.runtime -and
    $config.runtime.PSObject.Properties.Name -contains "health_path"
) {
    $configuredHealthPath = [string]$config.runtime.health_path
    if ([IO.Path]::IsPathRooted($configuredHealthPath)) {
        $healthPath = $configuredHealthPath
    } else {
        $healthPath = Join-Path $ProjectRoot $configuredHealthPath
    }
}
$deadline = [DateTime]::UtcNow.AddSeconds(30)
$health = $null
$age = [double]::PositiveInfinity
do {
    if (Test-Path -LiteralPath $healthPath) {
        try {
            $health = Get-Content -LiteralPath $healthPath -Raw |
                ConvertFrom-Json
            $age = (
                [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() -
                [double]$health.timestamp
            )
            if ($age -le 5 -and $health.runtime.service_mode) {
                break
            }
        } catch {
        }
    }
    Start-Sleep -Milliseconds 500
} while ([DateTime]::UtcNow -lt $deadline)

if ($null -eq $health -or $age -gt 5) {
    throw "Runtime health file did not become fresh within 30 seconds."
}

Push-Location $ProjectRoot
try {
    & $PythonExe -c (
        "from dobot_move.gui_ipc_client import RuntimeIpcClient; " +
        "r=RuntimeIpcClient().ping(); " +
        "assert r.get('ok'), r; print('IPC ping: OK')"
    )
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticated Runtime IPC ping failed."
    }
} finally {
    Pop-Location
}

Write-Host "Runtime service: $($runtime.Status)"
Write-Host "Watchdog service: $($watchdog.Status)"
Write-Host "Runtime health: fresh"
