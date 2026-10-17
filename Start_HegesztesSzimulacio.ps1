#requires -Version 5.1
$ErrorActionPreference = "Stop"

$root = $PSScriptRoot
Set-Location -LiteralPath $root
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$activateScript = Join-Path $root ".venv\Scripts\Activate.ps1"

Write-Host ""
Write-Host "  BODYLINE | Ipar 4.0 - oldalfal-hegesztes" -ForegroundColor Cyan
Write-Host "  Projekt: $root" -ForegroundColor DarkGray
Write-Host ""

# Create the virtual environment once, then reuse it.
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "[1/5] Python virtualis kornyezet letrehozasa..." -ForegroundColor Yellow
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($null -eq $py) {
        throw "Nem talalhato a Python Launcher (py). Telepits Python 3.11+ verziot, majd inditsd ujra ezt a scriptet."
    }
    & py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "A virtualis kornyezet letrehozasa nem sikerult." }
}

# Install dependencies only when the environment is missing one of the app packages.
Write-Host "[2/5] Python-csomagok ellenorzese..." -ForegroundColor Yellow
& $venvPython -c "import streamlit, pandas, openpyxl, paho.mqtt.client"
if ($LASTEXITCODE -ne 0) {
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "A pip frissitese nem sikerult." }
    & $venvPython -m pip install -r (Join-Path $root "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "A fuggosegek telepitese nem sikerult." }
}

# Docker CLI alone is not enough: Docker Desktop's engine must be running.
Write-Host "[3/5] Docker Desktop es MQTT-broker ellenorzese..." -ForegroundColor Yellow
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($null -eq $docker) {
    throw "A docker parancs nem talalhato. Telepitsd a Docker Desktopot, majd inditsd ujra ezt a scriptet."
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $dockerDesktopPaths = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Docker\Docker\Docker Desktop.exe")
    )
    $dockerDesktopExe = $dockerDesktopPaths | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($dockerDesktopExe) {
        Start-Process -FilePath $dockerDesktopExe | Out-Null
    } else {
        throw "A Docker CLI telepitve van, de a Docker Desktop alkalmazas nem talalhato. Inditsd el kezzel a Docker Desktopot."
    }

    $ready = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Seconds 2
        & docker info *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
    }
    if (-not $ready) {
        throw "A Docker Engine 120 masodperc alatt sem indult el. Nyisd meg a Docker Desktopot, es ellenorizd a WSL 2 beallitasait."
    }
}

& docker compose up -d mqtt
if ($LASTEXITCODE -ne 0) { throw "Az MQTT-broker nem indult el. Ellenorizd a Docker Desktop allapotat." }

# Stop old monitor/dashboard Python processes from this checkout. Otherwise port 8501
# or Python's cached modules can keep serving an older version after git pull.
Write-Host "Regi BODYLINE monitor/dashboard folyamatok leallitasa..." -ForegroundColor Yellow
$rootNormalized = [System.IO.Path]::GetFullPath($root).TrimEnd('\')
$staleProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and
    -not [string]::IsNullOrWhiteSpace($_.CommandLine) -and
    $_.CommandLine.IndexOf($rootNormalized, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
    (($_.CommandLine -match 'src\.monitor') -or
     ($_.CommandLine -match 'streamlit\s+run\s+src/dashboard\.py'))
}
foreach ($process in $staleProcesses) {
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        Write-Host ("Leallitva: PID {0} ({1})" -f $process.ProcessId, $process.Name) -ForegroundColor DarkGray
    } catch {
        Write-Host ("A regi PID {0} nem allithato le: {1}" -f $process.ProcessId, $_.Exception.Message) -ForegroundColor DarkYellow
    }
}
Start-Sleep -Seconds 2

# Open the monitor and dashboard in separate PowerShell windows.
Write-Host "[4/5] Monitor es kezelofelulet inditasa..." -ForegroundColor Yellow
$quotedRoot = $root.Replace("'", "''")
$quotedPython = $venvPython.Replace("'", "''")
$monitorCommand = "Set-Location -LiteralPath '$quotedRoot'; & '$quotedPython' -m src.monitor"
$dashboardCommand = "Set-Location -LiteralPath '$quotedRoot'; & '$quotedPython' -m streamlit run src/dashboard.py"

Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $monitorCommand
) | Out-Null
Start-Sleep -Seconds 2
Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", $dashboardCommand
) | Out-Null

Write-Host "[5/5] A bongeszo megnyitasa..." -ForegroundColor Yellow
Start-Sleep -Seconds 3
Start-Process "http://localhost:8501" | Out-Null

Write-Host ""
Write-Host "Elindult a BODYLINE szimulacio. Ne zarjad be a monitor es a dashboard ablakat." -ForegroundColor Green
Write-Host "Leallitas: a webes feluleten kapcsold ki az automatikus gyartast, majd zarhatod a ket terminalt."
Write-Host ""
