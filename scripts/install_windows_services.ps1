param(
    [string]$ProjectRoot = "C:\DobotRuntime",
    [string]$PythonExe = "",
    [string]$ServiceUser = ".\DobotRuntimeSvc",
    [System.Management.Automation.PSCredential]$ServiceCredential,
    [string]$GuiUser = "$env:USERDOMAIN\$env:USERNAME",
    [switch]$CreateServiceUser,
    [switch]$SkipStart,
    [switch]$ForceReinstall
)

. (Join-Path $PSScriptRoot "windows_service_common.ps1")
Assert-Administrator

$ProjectRoot = Resolve-DobotProjectRoot -ProjectRoot $ProjectRoot
$PythonExe = Resolve-DobotPython -ProjectRoot $ProjectRoot -PythonExe $PythonExe
$serviceDirectory = Get-DobotServiceDirectory
$backupDirectory = Join-Path (
    Split-Path -Parent $serviceDirectory
) "scheduled-task-backup"
$configPath = Join-Path $ProjectRoot "dobot_move\config.json"
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$tokenPath = Join-Path $ProjectRoot "runtime_ipc.token"
if (
    $config.runtime -and
    $config.runtime.PSObject.Properties.Name -contains "ipc_token_path"
) {
    $configuredTokenPath = [string]$config.runtime.ipc_token_path
    if ([IO.Path]::IsPathRooted($configuredTokenPath)) {
        $tokenPath = $configuredTokenPath
    } else {
        $tokenPath = Join-Path $ProjectRoot $configuredTokenPath
    }
}
$vendorBinary = Join-Path $ProjectRoot (
    "dobot_move\windows_service\vendor\WinSW-x64.exe"
)
$runtimeWrapper = Join-Path $serviceDirectory "DobotRuntimeService.exe"
$watchdogWrapper = Join-Path $serviceDirectory "DobotRuntimeWatchdog.exe"
$runtimeXml = Join-Path $serviceDirectory "DobotRuntimeService.xml"
$watchdogXml = Join-Path $serviceDirectory "DobotRuntimeWatchdog.xml"

if (-not $ServiceCredential) {
    $ServiceCredential = Get-Credential `
        -UserName $ServiceUser `
        -Message "Credentials for the dedicated Dobot Runtime service account"
}
if ($ServiceCredential.UserName -ne $ServiceUser) {
    throw "Credential user must match ServiceUser: $ServiceUser"
}

$localUserName = $ServiceUser -replace '^\.\\', ''
$existingLocalUser = Get-LocalUser -Name $localUserName -ErrorAction SilentlyContinue
if ($null -eq $existingLocalUser) {
    if (-not $CreateServiceUser) {
        throw "Local service user does not exist. Use -CreateServiceUser."
    }
    New-LocalUser `
        -Name $localUserName `
        -Password $ServiceCredential.Password `
        -AccountNeverExpires `
        -PasswordNeverExpires `
        -UserMayNotChangePassword | Out-Null
}

Push-Location $ProjectRoot
try {
    & $PythonExe -m dobot_move.windows_service.preflight
} finally {
    Pop-Location
}
if ($LASTEXITCODE -ne 0) {
    throw "Python/config/model deployment preflight failed."
}
& $PythonExe -c (
    "from dobot_move.windows_service.service_config import " +
    "verify_winsw_binary; import sys; " +
    "sys.exit(0 if verify_winsw_binary(r'$vendorBinary') else 1)"
)
if ($LASTEXITCODE -ne 0) {
    throw "WinSW binary is missing or SHA256 verification failed."
}

New-Item -ItemType Directory -Path $serviceDirectory -Force | Out-Null
New-Item -ItemType Directory -Path (
    Join-Path $ProjectRoot "logs"
) -Force | Out-Null

if ($ForceReinstall) {
    Stop-And-UninstallServiceWrapper -Executable $watchdogWrapper
    Stop-And-UninstallServiceWrapper -Executable $runtimeWrapper
} elseif (
    (Get-Service -Name $script:RuntimeServiceName -ErrorAction SilentlyContinue) -or
    (Get-Service -Name $script:WatchdogServiceName -ErrorAction SilentlyContinue)
) {
    throw "Dobot Windows services already exist. Use -ForceReinstall."
}

if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) {
    New-Item -ItemType Directory -Path (
        Split-Path -Parent $tokenPath
    ) -Force | Out-Null
    $bytes = New-Object byte[] 48
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($bytes)
    } finally {
        $random.Dispose()
    }
    $token = [Convert]::ToBase64String($bytes)
    [IO.File]::WriteAllText($tokenPath, $token, [Text.Encoding]::ASCII)
}

Copy-Item -LiteralPath $vendorBinary -Destination $runtimeWrapper -Force
Copy-Item -LiteralPath $vendorBinary -Destination $watchdogWrapper -Force
& $PythonExe -m dobot_move.windows_service.generate_config `
    --project-root $ProjectRoot `
    --python-exe $PythonExe `
    --token-path $tokenPath `
    --output-dir $serviceDirectory
if ($LASTEXITCODE -ne 0) {
    throw "WinSW XML generation failed."
}

icacls $ProjectRoot /grant "${ServiceUser}:(OI)(CI)M" /T /C | Out-Null
icacls $tokenPath /inheritance:r | Out-Null
icacls $tokenPath /grant:r `
    "${ServiceUser}:(R)" `
    "${GuiUser}:(R)" `
    "SYSTEM:(F)" `
    "Administrators:(F)" | Out-Null

$plainPassword = $null
$bstr = [IntPtr]::Zero
$legacyTasksDisabled = $false
try {
    Backup-AndDisableLegacyTasks -BackupDirectory $backupDirectory
    $legacyTasksDisabled = $true
    $modbusPort = if ($config.modbus_port) {
        [int]$config.modbus_port
    } else {
        502
    }
    $ipcPort = 8765
    if (
        $config.runtime -and
        $config.runtime.PSObject.Properties.Name -contains "ipc_port"
    ) {
        $ipcPort = [int]$config.runtime.ipc_port
    }
    $portsReady = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $ipcAvailable = Test-LocalTcpPortAvailable `
            -Address "127.0.0.1" -Port $ipcPort
        $modbusAvailable = Test-LocalTcpPortAvailable `
            -Address "0.0.0.0" -Port $modbusPort
        if ($ipcAvailable -and $modbusAvailable) {
            $portsReady = $true
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $portsReady) {
        throw "IPC $ipcPort or Modbus $modbusPort is still occupied."
    }

    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR(
        $ServiceCredential.Password
    )
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    [xml]$document = Get-Content -LiteralPath $runtimeXml -Raw
    $account = $document.CreateElement("serviceaccount")
    $username = $document.CreateElement("username")
    $username.InnerText = $ServiceUser
    $password = $document.CreateElement("password")
    $password.InnerText = $plainPassword
    $allowLogon = $document.CreateElement("allowservicelogon")
    $allowLogon.InnerText = "true"
    $account.AppendChild($username) | Out-Null
    $account.AppendChild($password) | Out-Null
    $account.AppendChild($allowLogon) | Out-Null
    $document.service.AppendChild($account) | Out-Null
    $document.Save($runtimeXml)

    Invoke-WinSW -Executable $runtimeWrapper -Command "install"

    # Remove the transient credential from the persistent XML immediately.
    & $PythonExe -m dobot_move.windows_service.generate_config `
        --project-root $ProjectRoot `
        --python-exe $PythonExe `
        --token-path $tokenPath `
        --output-dir $serviceDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to scrub credentials from Runtime service XML."
    }

    Invoke-WinSW -Executable $watchdogWrapper -Command "install"
    if (-not $SkipStart) {
        Invoke-WinSW -Executable $runtimeWrapper -Command "start"
        Start-Sleep -Seconds 3
        Invoke-WinSW -Executable $watchdogWrapper -Command "start"
        & (Join-Path $PSScriptRoot "test_windows_services.ps1") `
            -ProjectRoot $ProjectRoot `
            -PythonExe $PythonExe
        if ($LASTEXITCODE -ne 0) {
            throw "Windows service verification failed."
        }
    }
} catch {
    Stop-And-UninstallServiceWrapper -Executable $watchdogWrapper
    Stop-And-UninstallServiceWrapper -Executable $runtimeWrapper
    if ($legacyTasksDisabled) {
        Restore-LegacyTasks -BackupDirectory $backupDirectory
    }
    throw
} finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $plainPassword = $null
    Remove-Variable ServiceCredential -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $runtimeXml) {
        & $PythonExe -m dobot_move.windows_service.generate_config `
            --project-root $ProjectRoot `
            --python-exe $PythonExe `
            --token-path $tokenPath `
            --output-dir $serviceDirectory
    }
}

Write-Host "Installed $($script:RuntimeServiceName)"
Write-Host "Installed $($script:WatchdogServiceName)"
Write-Host "Legacy scheduled tasks are disabled and backed up at $backupDirectory"
