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

Push-Location $ProjectRoot
try {
    & $PythonExe -c (
        "from dobot_move.windows_service.service_config import " +
        "verify_winsw_binary; import sys; " +
        "sys.exit(0 if verify_winsw_binary(r'$vendorBinary') else 1)"
    )
} finally {
    Pop-Location
}
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
    Join-Path $ProjectRoot "user_data\config.json"
) -Raw | ConvertFrom-Json
$healthPath = Join-Path $ProjectRoot "user_data\runtime_health.json"
if (
    $config.PSObject.Properties.Name -contains "runtime" -and
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

$ipcPort = 8765
if (
    $config.PSObject.Properties.Name -contains "runtime" -and
    $config.runtime.PSObject.Properties.Name -contains "ipc_port"
) {
    $ipcPort = [int]$config.runtime.ipc_port
}
$ipcTokenPath = ""
if (
    $config.PSObject.Properties.Name -contains "runtime" -and
    $config.runtime.PSObject.Properties.Name -contains "ipc_token_path"
) {
    $configuredTokenPath = [string]$config.runtime.ipc_token_path
    if ([IO.Path]::IsPathRooted($configuredTokenPath)) {
        $ipcTokenPath = $configuredTokenPath
    } else {
        $ipcTokenPath = Join-Path $ProjectRoot $configuredTokenPath
    }
}
Push-Location $ProjectRoot
try {
    if ($ipcTokenPath) {
        & $PythonExe -c (
            "from dobot_move.ui.gui_ipc_client import RuntimeIpcClient; " +
            "r=RuntimeIpcClient(port=$ipcPort, token_path=r'$ipcTokenPath').ping(); " +
            "assert r.get('ok'), r; print('IPC ping: OK')"
        )
    } else {
        & $PythonExe -c (
            "from dobot_move.ui.gui_ipc_client import RuntimeIpcClient; " +
            "r=RuntimeIpcClient(port=$ipcPort).ping(); " +
            "assert r.get('ok'), r; print('IPC ping: OK')"
        )
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticated Runtime IPC ping failed."
    }
} finally {
    Pop-Location
}

Write-Host "Runtime service: $($runtime.Status)"
Write-Host "Watchdog service: $($watchdog.Status)"
Write-Host "Runtime health: fresh"
