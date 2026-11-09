#requires -Version 5.1
param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][ValidateSet("monitor", "dashboard")][string]$Service,
    [Parameter(Mandatory = $true)][string]$Marker
)

$ErrorActionPreference = "Stop"
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Set-Location -LiteralPath $ProjectRoot
$env:PYTHONUNBUFFERED = "1"
$env:BODYLINE_SERVICE_MARKER = $Marker
if ($Service -eq "monitor") {
    $env:BODYLINE_READY_FILE = Join-Path $logDir "monitor.ready"
    $env:BODYLINE_STOPPED_FILE = Join-Path $logDir "monitor.stopped"
    Remove-Item Env:BODYLINE_DASHBOARD_READY_FILE -ErrorAction SilentlyContinue
} else {
    $env:BODYLINE_DASHBOARD_READY_FILE = Join-Path $logDir "dashboard.ready"
    Remove-Item Env:BODYLINE_READY_FILE -ErrorAction SilentlyContinue
}

if (-not (Test-Path -LiteralPath $python)) { throw "Nem talalhato a projekt virtualis kornyezetenek Pythonja: $python" }

Write-Host ""
Write-Host ("BODYLINE szolgaltatas: {0}" -f $Service) -ForegroundColor Cyan
Write-Host ("Projekt: {0}" -f $ProjectRoot) -ForegroundColor DarkGray
Write-Host ("Azonosito: {0}" -f $Marker) -ForegroundColor DarkGray
Write-Host ""

# Python and Uvicorn may write normal startup messages to stderr. PowerShell can
# promote those records to terminating errors when ErrorActionPreference is Stop.
# Keep the service console/log stream alive; the native process exit code is checked below.
$previousErrorActionPreference = $ErrorActionPreference
$nativePreferenceVariable = Get-Variable -Name "PSNativeCommandUseErrorActionPreference" -ErrorAction SilentlyContinue
$hadNativePreferenceVariable = $null -ne $nativePreferenceVariable
if ($hadNativePreferenceVariable) {
    $previousNativePreference = [bool]$nativePreferenceVariable.Value
    $PSNativeCommandUseErrorActionPreference = $false
}
$ErrorActionPreference = "Continue"

try {
    if ($Service -eq "monitor") {
        $logPath = Join-Path $logDir "monitor.log"
        & $python -u -m src.monitor 2>&1 | Tee-Object -FilePath $logPath -Append
    } else {
        $logPath = Join-Path $logDir "dashboard.log"
        # Streamlit is headless: only the parent launcher opens the browser.
        & $python -u -m streamlit run --server.headless true --server.port 8501 src/dashboard.py 2>&1 | Tee-Object -FilePath $logPath -Append
    }
    $serviceExitCode = $LASTEXITCODE
}
finally {
    $ErrorActionPreference = $previousErrorActionPreference
    if ($hadNativePreferenceVariable) {
        $PSNativeCommandUseErrorActionPreference = $previousNativePreference
    }
}
if ($serviceExitCode -ne 0) {
    Write-Host ""
    Write-Host ("A {0} szolgaltatas hibakoddal allt le: {1}" -f $Service, $serviceExitCode) -ForegroundColor Red
}
Write-Host ""
Read-Host "A szolgaltatas ablakanak bezarasahoz nyomj Entert"
