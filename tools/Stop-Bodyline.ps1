#requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [ValidateRange(10, 600)][int]$SafeStopTimeoutSeconds = 150
)

$ErrorActionPreference = "Stop"
$root = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$python = Join-Path $root ".venv\Scripts\python.exe"
$serviceHelper = Join-Path $root "tools\Run-Bodyline-Service.ps1"
$logDir = Join-Path $root "logs"
$productionLog = Join-Path $logDir "production_log.txt"
$shutdownLog = Join-Path $logDir "shutdown.log"
$shutdownRequest = Join-Path $logDir "shutdown.request"
$productionIdle = Join-Path $logDir "production_idle.ready"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location -LiteralPath $root

function Add-ProductionLogLine {
    param([string]$Message)
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $line = "$timestamp | SYSTEM STATUS | $Message$([Environment]::NewLine)"
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::AppendAllText($productionLog, $line, $encoding)
}

function Get-ProjectServiceProcesses {
    $found = @()
    $snapshot = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
    foreach ($process in $snapshot) {
        if ($process.ProcessId -eq $PID -or [string]::IsNullOrWhiteSpace($process.CommandLine)) { continue }
        $cmd = [string]$process.CommandLine
        $usesProjectPython = $cmd.IndexOf($python, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        $isMonitor = $usesProjectPython -and ($cmd -match 'src\.monitor')
        $isDashboard = $usesProjectPython -and ($cmd -match 'streamlit\s+run') -and ($cmd -match 'src[/\\]dashboard\.py')
        if ($isMonitor -or $isDashboard) { $found += $process }
    }
    return @($found)
}

try {
    Add-Content -LiteralPath $shutdownLog -Value "[$(Get-Date -Format s)] Shutdown requested." -Encoding UTF8
    if (-not (Test-Path -LiteralPath $shutdownRequest)) {
        [System.IO.File]::WriteAllText($shutdownRequest, (Get-Date).ToString("o"), (New-Object System.Text.UTF8Encoding($false)))
    }

    Write-Host "Waiting for the current sidewall cycle to reach a safe stop point..."
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $productionIdle) -and $watch.Elapsed.TotalSeconds -lt $SafeStopTimeoutSeconds) {
        Start-Sleep -Milliseconds 500
    }

    if (Test-Path -LiteralPath $productionIdle) {
        Write-Host "Production cycle reached a safe stop point."
    } else {
        Add-ProductionLogLine "SAFE STOP TIMEOUT - FORCING SERVICE SHUTDOWN"
        Add-Content -LiteralPath $shutdownLog -Value "Safe-stop timeout reached; terminating remaining project processes." -Encoding UTF8
    }

    # The monitor watches shutdown.request and disconnects cleanly after the final body verdict.
    $monitorStopped = Join-Path $logDir "monitor.stopped"
    $monitorWatch = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $monitorStopped) -and $monitorWatch.Elapsed.TotalSeconds -lt 10) {
        Start-Sleep -Milliseconds 250
    }
    if (-not (Test-Path -LiteralPath $monitorStopped)) {
        Add-Content -LiteralPath $shutdownLog -Value "Monitor clean-stop signal was not received; its service process will be terminated." -Encoding UTF8
    }

    # Stop service wrapper windows first; /T also stops their Python child processes.
    $snapshot = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
    foreach ($process in $snapshot) {
        if ($process.ProcessId -eq $PID -or [string]::IsNullOrWhiteSpace($process.CommandLine)) { continue }
        $cmd = [string]$process.CommandLine
        $isServiceWindow = ($cmd.IndexOf($serviceHelper, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -and
            ($cmd.IndexOf($root, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
        if ($isServiceWindow) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $process.ProcessId /T /F *> $null
        }
    }

    # Catch orphaned service interpreters without touching unrelated Python processes.
    Start-Sleep -Milliseconds 500
    foreach ($process in (Get-ProjectServiceProcesses)) {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
    }

    $remaining = @()
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        $remaining = @(Get-ProjectServiceProcesses)
        if ($remaining.Count -eq 0) { break }
        Start-Sleep -Milliseconds 500
    }
    if ($remaining.Count -gt 0) {
        $pids = ($remaining | ForEach-Object { [string]$_.ProcessId }) -join ", "
        throw "BODYLINE service process(es) could not be stopped. Remaining PID(s): $pids"
    }

    # Stop only this project's MQTT service; Docker Desktop itself remains available.
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $docker) { throw "Docker command was not found; BODYLINE processes stopped but MQTT container may still be running." }
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & docker compose stop mqtt 2>&1 | Tee-Object -FilePath $shutdownLog -Append
        $dockerExitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($dockerExitCode -ne 0) {
        throw "Docker Compose could not stop the BODYLINE MQTT container (exit code $dockerExitCode)."
    }

    Remove-Item -LiteralPath (Join-Path $logDir "monitor.ready") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $monitorStopped -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $logDir "dashboard.ready") -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $productionIdle -Force -ErrorAction SilentlyContinue
    Add-ProductionLogLine "ALL BODYLINE SERVICES STOPPED"
    Add-Content -LiteralPath $shutdownLog -Value "[$(Get-Date -Format s)] BODYLINE shutdown completed successfully." -Encoding UTF8
    Remove-Item -LiteralPath $shutdownRequest -Force -ErrorAction SilentlyContinue
    Write-Host "BODYLINE dashboard, monitor and MQTT container have been stopped."
} catch {
    $message = $_.Exception.Message
    Add-Content -LiteralPath $shutdownLog -Value "[$(Get-Date -Format s)] SHUTDOWN ERROR: $message" -Encoding UTF8
    try { Add-ProductionLogLine "SHUTDOWN INCOMPLETE - $message" } catch {}
    Write-Host "BODYLINE shutdown was incomplete: $message" -ForegroundColor Red
    exit 1
}
