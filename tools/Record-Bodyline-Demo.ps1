#requires -Version 5.1
[CmdletBinding()]
param(
    [ValidateRange(30, 600)]
    [int]$DurationSeconds = 240,
    [string]$OutputPath = "docs/demo_video/BODYLINE_demo.mp4"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$ffmpeg = Get-Command "ffmpeg.exe" -ErrorAction SilentlyContinue
if (-not $ffmpeg) { $ffmpeg = Get-Command "ffmpeg" -ErrorAction SilentlyContinue }
if (-not $ffmpeg) {
    throw "Az FFmpeg nem található. Telepítsd, és add hozzá a PATH környezeti változóhoz."
}

$target = if ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath
} else {
    Join-Path $root $OutputPath
}
$target = [System.IO.Path]::GetFullPath($target)
$targetDir = Split-Path -Parent $target
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

Write-Host "A teljes asztal rögzítése indul $DurationSeconds másodpercre." -ForegroundColor Cyan
Write-Host "Kimeneti videó: $target" -ForegroundColor Cyan
Write-Host "A felvétel előtt zárd be a személyes adatokat megjelenítő ablakokat." -ForegroundColor Yellow

$ffmpegArgs = @(
    "-y", "-hide_banner", "-f", "gdigrab", "-framerate", "25",
    "-i", "desktop", "-t", [string]$DurationSeconds,
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart", $target
)
& $ffmpeg.Source @ffmpegArgs
if ($LASTEXITCODE -ne 0) {
    throw "Az FFmpeg hibával állt le (exit code: $LASTEXITCODE)."
}
if (-not (Test-Path -LiteralPath $target) -or (Get-Item -LiteralPath $target).Length -le 0) {
    throw "A videófájl nem jött létre vagy üres: $target"
}
Write-Host "A felvétel elkészült: $target" -ForegroundColor Green
