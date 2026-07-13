Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:RuntimeServiceName = "DobotRuntimeService"
$script:WatchdogServiceName = "DobotRuntimeWatchdog"
$script:LegacyTaskNames = @("DobotRuntimeAgent", "DobotRuntimeWatchdog")

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator
    )) {
        throw "Run this script from an elevated PowerShell session."
    }
}

function Resolve-DobotProjectRoot {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)
    $resolved = (Resolve-Path -LiteralPath $ProjectRoot).Path
    if (-not (Test-Path -LiteralPath (
        Join-Path $resolved "dobot_move\runtime\runtime_agent.py"
    ))) {
        throw "dobot_move.runtime.runtime_agent not found under: $resolved"
    }
    return $resolved
}

function Resolve-DobotPython {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [string]$PythonExe
    )
    if (-not $PythonExe) {
        $PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    }
    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw "Python executable not found: $PythonExe"
    }
    return (Resolve-Path -LiteralPath $PythonExe).Path
}

function Get-DobotServiceDirectory {
    $base = Join-Path $env:ProgramData "DobotRuntime"
    return Join-Path $base "service"
}

function Backup-AndDisableLegacyTasks {
    param([Parameter(Mandatory = $true)][string]$BackupDirectory)
    New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null
    foreach ($taskName in $script:LegacyTaskNames) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            continue
        }
        Export-ScheduledTask -TaskName $taskName |
            Set-Content -LiteralPath (
                Join-Path $BackupDirectory "$taskName.xml"
            ) -Encoding Unicode
        @{
            Enabled = [bool]$task.Settings.Enabled
            WasRunning = [string]$task.State -eq "Running"
        } | ConvertTo-Json | Set-Content -LiteralPath (
            Join-Path $BackupDirectory "$taskName.state.json"
        ) -Encoding UTF8
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskName $taskName | Out-Null
    }
}

function Restore-LegacyTasks {
    param(
        [Parameter(Mandatory = $true)][string]$BackupDirectory,
        [switch]$Start
    )
    foreach ($taskName in $script:LegacyTaskNames) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            continue
        }
        $statePath = Join-Path $BackupDirectory "$taskName.state.json"
        $state = $null
        if (Test-Path -LiteralPath $statePath) {
            $state = Get-Content -LiteralPath $statePath -Raw |
                ConvertFrom-Json
        }
        if ($null -eq $state -or $state.Enabled) {
            Enable-ScheduledTask -TaskName $taskName | Out-Null
        } else {
            Disable-ScheduledTask -TaskName $taskName | Out-Null
        }
        if ($Start -or ($null -ne $state -and $state.WasRunning)) {
            Start-ScheduledTask -TaskName $taskName
        }
    }
}

function Enable-LegacyTasks {
    param([switch]$Start)
    foreach ($taskName in $script:LegacyTaskNames) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            continue
        }
        Enable-ScheduledTask -TaskName $taskName | Out-Null
        if ($Start) {
            Start-ScheduledTask -TaskName $taskName
        }
    }
}

function Invoke-WinSW {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string]$Command
    )
    & $Executable $Command
    if ($LASTEXITCODE -ne 0) {
        throw "WinSW command failed: $Executable $Command ($LASTEXITCODE)"
    }
}

function Test-LocalTcpPortAvailable {
    param(
        [Parameter(Mandatory = $true)][string]$Address,
        [Parameter(Mandatory = $true)][int]$Port
    )
    $listener = $null
    try {
        $ip = [Net.IPAddress]::Parse($Address)
        $listener = New-Object Net.Sockets.TcpListener($ip, $Port)
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($null -ne $listener) {
            $listener.Stop()
        }
    }
}

function Stop-And-UninstallServiceWrapper {
    param([Parameter(Mandatory = $true)][string]$Executable)
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
        return
    }
    & $Executable stop 2>$null
    & $Executable uninstall 2>$null
}
