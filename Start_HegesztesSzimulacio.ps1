#requires -Version 5.1
$ErrorActionPreference = "Stop"

$root = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\')
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$helperPath = Join-Path $root "tools\Run-Bodyline-Service.ps1"
$logDir = Join-Path $root "logs"
$monitorLog = Join-Path $logDir "monitor.log"
$monitorReadyFile = Join-Path $logDir "monitor.ready"
$dashboardLog = Join-Path $logDir "dashboard.log"
$dashboardUrl = "http://localhost:8501"
$dashboardHealthUrl = "$dashboardUrl/_stcore/health"
$dashboardPort = 8501

$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $rootToken = ([System.BitConverter]::ToString($sha256.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($root)))).Replace("-", "").Substring(0, 12)
} finally {
    $sha256.Dispose()
}
$serviceMarkerPrefix = "BODYLINE_SERVICE_$rootToken"

# Prevent two quick double-clicks from launching two stacks.
$mutex = [System.Threading.Mutex]::new($false, "Local\BODYLINE_START_$rootToken")
$mutexAcquired = $false

function Test-TcpPort {
    param([string]$HostName, [int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-ListenerOwner {
    param([int]$Port)
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -ne $connection) { return [int]$connection.OwningProcess }
    } catch {}
    return $null
}

function Get-ProcessSnapshot {
    return @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop)
}

function Test-DashboardHealth {
    try {
        $response = Invoke-WebRequest -Uri $dashboardHealthUrl -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -eq 200 -and $response.Content.Trim() -eq "ok")
    } catch {
        return $false
    }
}

function Get-BodylineServiceProcesses {
    param([string]$RootPath, [string]$PythonPath, [string]$MarkerPrefix)
    $resultItems = @()
    foreach ($process in (Get-ProcessSnapshot)) {
        if ($process.ProcessId -eq $PID -or [string]::IsNullOrWhiteSpace($process.CommandLine)) { continue }
        $commandLine = [string]$process.CommandLine
        $usesProjectPython = $commandLine.IndexOf($PythonPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        $isMonitorCommand = $commandLine -match 'src\.monitor'
        $isDashboardCommand = ($commandLine -match 'streamlit\s+run') -and ($commandLine -match 'src[/\\]dashboard\.py')
        $isHelperCommand = ($commandLine -match 'Run-Bodyline-Service\.ps1') -and
            ($commandLine.IndexOf($RootPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
        $hasMarker = $commandLine.IndexOf($MarkerPrefix, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
        if (($usesProjectPython -and ($isMonitorCommand -or $isDashboardCommand)) -or $isHelperCommand -or $hasMarker) {
            $resultItems += $process
        }
    }
    return @($resultItems)
}

function Stop-BodylineMonitorProcesses {
    param([string]$RootPath, [string]$PythonPath, [string]$MarkerPrefix)
    $snapshot = Get-ProcessSnapshot

    # Stop monitor helper windows first; taskkill then terminates their child Python process.
    foreach ($process in $snapshot) {
        if ($process.ProcessId -eq $PID -or [string]::IsNullOrWhiteSpace($process.CommandLine)) { continue }
        $cmd = [string]$process.CommandLine
        $isMonitorHelper = ($cmd -match 'Run-Bodyline-Service\.ps1') -and ($cmd -match 'monitor') -and
            (($cmd.IndexOf($RootPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -or
             ($cmd.IndexOf($MarkerPrefix, [System.StringComparison]::OrdinalIgnoreCase) -ge 0))
        if ($isMonitorHelper) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $process.ProcessId /T /F *> $null
        }
    }

    # Then remove orphaned monitor interpreters, without touching the healthy dashboard.
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        $remaining = @()
        foreach ($process in (Get-ProcessSnapshot)) {
            if ($process.ProcessId -eq $PID -or [string]::IsNullOrWhiteSpace($process.CommandLine)) { continue }
            $cmd = [string]$process.CommandLine
            $usesProjectPython = $cmd.IndexOf($PythonPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0
            if ($usesProjectPython -and ($cmd -match 'src\.monitor')) {
                $remaining += $process
            }
        }
        if ($remaining.Count -eq 0) { return }
        foreach ($process in $remaining) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
    }

    $remaining = @()
    foreach ($process in (Get-ProcessSnapshot)) {
        if ($process.ProcessId -eq $PID -or [string]::IsNullOrWhiteSpace($process.CommandLine)) { continue }
        $cmd = [string]$process.CommandLine
        if (($cmd.IndexOf($PythonPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -and ($cmd -match 'src\.monitor')) {
            $remaining += $process
        }
    }
    foreach ($process in $remaining) {
        Write-Warning ("A monitor process is still running (PID {0})." -f $process.ProcessId)
    }
}

function Stop-ExistingBodylineProcesses {
    param([string]$RootPath, [string]$PythonPath, [string]$MarkerPrefix)

    $snapshot = Get-ProcessSnapshot
    # Kill old service wrapper trees once. Do not later taskkill the same child PIDs again.
    foreach ($process in $snapshot) {
        if ($process.ProcessId -eq $PID -or [string]::IsNullOrWhiteSpace($process.CommandLine)) { continue }
        $cmd = [string]$process.CommandLine
        $isServiceHelper = ($cmd -match 'Run-Bodyline-Service\.ps1') -and
            (($cmd.IndexOf($RootPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -or
             ($cmd.IndexOf($MarkerPrefix, [System.StringComparison]::OrdinalIgnoreCase) -ge 0))
        if ($isServiceHelper) {
            & "$env:SystemRoot\System32\taskkill.exe" /PID $process.ProcessId /T /F *> $null
        }
    }

    # Terminate any orphaned Python service processes and wait until they are actually gone.
    for ($attempt = 0; $attempt -lt 6; $attempt++) {
        $remaining = @(Get-BodylineServiceProcesses -RootPath $RootPath -PythonPath $PythonPath -MarkerPrefix $MarkerPrefix |
            Where-Object {
                $cmd = [string]$_.CommandLine
                ($cmd.IndexOf($PythonPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -and
                (($cmd -match 'src\.monitor') -or
                 (($cmd -match 'streamlit\s+run') -and ($cmd -match 'src[/\\]dashboard\.py')))
            })

        if ($remaining.Count -eq 0) { return }

        foreach ($process in $remaining) {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
    }

    $remaining = @(Get-BodylineServiceProcesses -RootPath $RootPath -PythonPath $PythonPath -MarkerPrefix $MarkerPrefix)
    if ($remaining.Count -gt 0) {
        $pids = ($remaining | ForEach-Object { [string]$_.ProcessId }) -join ", "
        throw "Could not stop old BODYLINE service processes. Remaining PID(s): $pids"
    }
}

function Start-BodylineServiceWindow {
    param([ValidateSet("monitor", "dashboard")][string]$Service, [string]$ProjectRoot, [string]$Marker, [string]$Helper)
    $arguments = '-NoProfile -NoExit -ExecutionPolicy Bypass -File "{0}" -ProjectRoot "{1}" -Service "{2}" -Marker "{3}"' -f $Helper, $ProjectRoot, $Service, $Marker
    return Start-Process -FilePath "powershell.exe" -ArgumentList $arguments -WorkingDirectory $ProjectRoot -WindowStyle Normal -PassThru
}

function Get-TextFileLength {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    try { return [System.IO.File]::ReadAllText($Path).Length } catch { return 0 }
}

function Test-MonitorReadySignal {
    param([string]$ReadyPath)
    if (-not (Test-Path -LiteralPath $ReadyPath)) { return $false }
    try {
        $content = [System.IO.File]::ReadAllText($ReadyPath)
        return $content.Contains("status=connected")
    } catch {
        return $false
    }
}

function Wait-ForMonitorReady {
    param([string]$ReadyPath, [int]$TimeoutSeconds)
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (Test-MonitorReadySignal -ReadyPath $ReadyPath) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Show-LogTail {
    param([string]$Path, [string]$Title)
    Write-Host ""
    Write-Host $Title -ForegroundColor Yellow
    if (Test-Path -LiteralPath $Path) {
        Get-Content -LiteralPath $Path -Tail 35 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host "A naplofajl meg nem jott letre: $Path" -ForegroundColor DarkGray
    }
}

try {
    try {
        $mutexAcquired = $mutex.WaitOne(0)
    } catch [System.Threading.AbandonedMutexException] {
        $mutexAcquired = $true
    }

    if (-not $mutexAcquired) {
        Write-Host "A BODYLINE inditasa mar folyamatban van. Nem inditok masodik peldanyt." -ForegroundColor Yellow
        return
    }

    Set-Location -LiteralPath $root
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    Write-Host ""
    Write-Host "  BODYLINE | Ipar 4.0 - oldalfal-hegesztes" -ForegroundColor Cyan
    Write-Host "  Projekt: $root" -ForegroundColor DarkGray
    Write-Host ""

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Write-Host "[1/5] Python virtualis kornyezet letrehozasa..." -ForegroundColor Yellow
        $py = Get-Command py -ErrorAction SilentlyContinue
        if ($null -eq $py) { throw "Nem talalhato a Python Launcher (py). Telepits Python 3.11+ verziot." }
        & py -3 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "A virtualis kornyezet letrehozasa nem sikerult." }
    }
    if (-not (Test-Path -LiteralPath $venvPython)) { throw "A virtualis kornyezet Pythonja nem jott letre: $venvPython" }

    Write-Host "[2/5] Python-csomagok ellenorzese..." -ForegroundColor Yellow
    & $venvPython -c "import streamlit, pandas, openpyxl, paho.mqtt.client"
    if ($LASTEXITCODE -ne 0) {
        & $venvPython -m pip install --upgrade pip
        if ($LASTEXITCODE -ne 0) { throw "A pip frissitese nem sikerult." }
        & $venvPython -m pip install -r (Join-Path $root "requirements.txt")
        if ($LASTEXITCODE -ne 0) { throw "A fuggosegek telepitese nem sikerult." }
        & $venvPython -c "import streamlit, pandas, openpyxl, paho.mqtt.client"
        if ($LASTEXITCODE -ne 0) { throw "A Python-fuggosegek ellenorzese a telepites utan sem sikerult." }
    }
    if (-not (Test-Path -LiteralPath $helperPath)) { throw "Hianyzik az inditoszkript segedfajlja: $helperPath. Frissitsd a GitHub-repozitoriumot." }

    Write-Host "[3/5] Docker Desktop es MQTT-broker ellenorzese..." -ForegroundColor Yellow
    $docker = Get-Command docker -ErrorAction SilentlyContinue
    if ($null -eq $docker) { throw "A docker parancs nem talalhato. Telepitsd a Docker Desktopot." }
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        $dockerDesktopPaths = @((Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"), (Join-Path $env:LOCALAPPDATA "Programs\Docker\Docker\Docker Desktop.exe"))
        $dockerDesktopExe = $dockerDesktopPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if ($dockerDesktopExe) { Start-Process -FilePath $dockerDesktopExe | Out-Null }
        else { throw "A Docker Desktop alkalmazas nem talalhato. Inditsd el kezzel." }
        $dockerReady = $false
        for ($i = 0; $i -lt 90; $i++) {
            Start-Sleep -Seconds 2
            & docker info *> $null
            if ($LASTEXITCODE -eq 0) { $dockerReady = $true; break }
        }
        if (-not $dockerReady) { throw "A Docker Engine 180 masodperc alatt sem indult el. Ellenorizd a Docker Desktopot es a WSL 2-t." }
    }

    & docker compose up -d mqtt
    if ($LASTEXITCODE -ne 0) { throw "Az MQTT-broker inditasa nem sikerult." }
    $brokerReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        if (Test-TcpPort -HostName "127.0.0.1" -Port 1883) { $brokerReady = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $brokerReady) { throw "A localhost:1883 MQTT-port 30 masodperc alatt nem valt elerhetove." }

    # Reuse an already healthy instance; never open a second browser tab on rerun.
    $listenerPid = Get-ListenerOwner -Port $dashboardPort
    if ($null -ne $listenerPid) {
        $owner = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $listenerPid" -ErrorAction SilentlyContinue
        $ownerCommand = if ($null -ne $owner) { [string]$owner.CommandLine } else { "" }
        $sameProjectDashboard = ($ownerCommand.IndexOf($venvPython, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -and ($ownerCommand -match 'streamlit\s+run') -and ($ownerCommand -match 'src[/\\]dashboard\.py')
        if (-not $sameProjectDashboard) { throw "A localhost:$dashboardPort portot masik folyamat hasznalja (PID: $listenerPid). Allitsd le azt az alkalmazast." }

        if (Test-DashboardHealth) {
            $snapshot = Get-ProcessSnapshot
            $monitorExists = $false
            foreach ($process in $snapshot) {
                if ([string]::IsNullOrWhiteSpace($process.CommandLine)) { continue }
                $cmd = [string]$process.CommandLine
                if (($cmd.IndexOf($venvPython, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) -and ($cmd -match 'src\.monitor')) { $monitorExists = $true; break }
            }
            if (-not $monitorExists -or -not (Test-MonitorReadySignal -ReadyPath $monitorReadyFile)) {
                Write-Host "The dashboard is healthy; restarting the monitor so its MQTT readiness can be verified..." -ForegroundColor Yellow
                Stop-BodylineMonitorProcesses -RootPath $root -PythonPath $venvPython -MarkerPrefix $serviceMarkerPrefix
                Remove-Item -LiteralPath $monitorReadyFile -Force -ErrorAction SilentlyContinue
                $monitorWindow = Start-BodylineServiceWindow -Service "monitor" -ProjectRoot $root -Marker ($serviceMarkerPrefix + ":monitor") -Helper $helperPath
                if (-not (Wait-ForMonitorReady -ReadyPath $monitorReadyFile -TimeoutSeconds 30)) {
                    Show-LogTail -Path $monitorLog -Title "Monitor log"
                    throw "The monitor did not connect to the MQTT broker. Do not start production yet."
                }
            }
            Write-Host "A BODYLINE mar fut. Nem inditottam ujabb peldanyt es nem nyitottam uj bongeszoablakot." -ForegroundColor Green
            Write-Host "Dashboard: $dashboardUrl"
            return
        }
        Write-Host "A korabbi BODYLINE-dashboard nem valaszol; ujrainditom..." -ForegroundColor Yellow
    }

    Write-Host "Korabbi, ehhez a projekthez tartozo folyamatok ellenorzese..." -ForegroundColor Yellow
    Stop-ExistingBodylineProcesses -RootPath $root -PythonPath $venvPython -MarkerPrefix $serviceMarkerPrefix
    $portReleased = $false
    for ($i = 0; $i -lt 20; $i++) {
        if ($null -eq (Get-ListenerOwner -Port $dashboardPort)) { $portReleased = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $portReleased) {
        $busyPid = Get-ListenerOwner -Port $dashboardPort
        throw "A localhost:$dashboardPort port tovabbra is foglalt (PID: $busyPid). Nem inditok masodik dashboardot."
    }

    Write-Host "[4/5] Starting MQTT monitor and dashboard..." -ForegroundColor Yellow
    Remove-Item -LiteralPath $monitorReadyFile -Force -ErrorAction SilentlyContinue
    $monitorWindow = Start-BodylineServiceWindow -Service "monitor" -ProjectRoot $root -Marker ($serviceMarkerPrefix + ":monitor") -Helper $helperPath
    if (-not (Wait-ForMonitorReady -ReadyPath $monitorReadyFile -TimeoutSeconds 30)) {
        Show-LogTail -Path $monitorLog -Title "Monitor log"
        throw "The monitor did not signal a successful MQTT connection within 30 seconds. Dashboard startup was cancelled."
    }
    Write-Host "Az MQTT-monitor csatlakozott." -ForegroundColor Green

    $dashboardWindow = Start-BodylineServiceWindow -Service "dashboard" -ProjectRoot $root -Marker ($serviceMarkerPrefix + ":dashboard") -Helper $helperPath
    Write-Host "[5/5] A dashboard egeszsegi allapotanak ellenorzese..." -ForegroundColor Yellow
    $dashboardReady = $false
    $healthyChecks = 0
    for ($i = 0; $i -lt 60; $i++) {
        if (Test-DashboardHealth) {
            $healthyChecks++
            if ($healthyChecks -ge 2) { $dashboardReady = $true; break }
        } else { $healthyChecks = 0 }
        Start-Sleep -Seconds 1
    }
    if (-not $dashboardReady) {
        Show-LogTail -Path $dashboardLog -Title "Dashboard naplo"
        throw "A dashboard 60 masodperc alatt nem valt egeszseges allapotuva. Nem nyitottam meg a bongeszot."
    }

    Write-Host "A dashboard egeszsegesen elerheto: $dashboardUrl" -ForegroundColor Green
    Write-Host "A bongeszo megnyitasa egyszer..." -ForegroundColor Yellow
    Start-Process -FilePath $dashboardUrl | Out-Null
    Write-Host ""
    Write-Host "A BODYLINE elindult. A gyartas alapbol leallitott allapotban van; az automatikat az Elo gyartas fulon indithatod." -ForegroundColor Green
    Write-Host "A monitor es a dashboard ablakat hagyd nyitva. Naplok: $logDir"
    Write-Host ""
} catch {
    Write-Host ""
    Write-Host ("INDITASI HIBA: {0}" -f $_.Exception.Message) -ForegroundColor Red
    Write-Host "A bongeszot nem nyitottam meg, mert a dashboard ellenorzese nem volt sikeres." -ForegroundColor Yellow
    Read-Host "Nyomj Entert az ablak bezarasahoz"
    exit 1
} finally {
    if ($mutexAcquired) { try { $mutex.ReleaseMutex() } catch {} }
    $mutex.Dispose()
}
