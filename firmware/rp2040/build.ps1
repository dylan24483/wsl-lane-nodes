# Developer build -> build/wsl_phase8b_rp2040.uf2
#
# This does not create a controlled release bundle. For a flashable artifact,
# use release.ps1, which builds both variants and verifies their manifest.
#
# One-command rebuild. Auto-discovers the toolchain bootstrapped 2026-06-03:
#   - xpack arm-none-eabi-gcc   (C:\Users\Dylan DeYoung\arm-none-eabi-gcc\...)
#   - WinLibs host gcc + cmake + ninja  (winget BrechtSanders.WinLibs.POSIX.UCRT)
#   - cloned pico-sdk           (C:\Users\Dylan DeYoung\pico-sdk)
# Override any of these by setting $env:PICO_SDK_PATH (or putting the tools on PATH) first.
#
# Usage:   pwsh -File build.ps1        (run from anywhere; resolves its own dir)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- pico-sdk ---
if (-not $env:PICO_SDK_PATH) { $env:PICO_SDK_PATH = "C:\Users\Dylan DeYoung\pico-sdk" }
if (-not (Test-Path "$env:PICO_SDK_PATH\pico_sdk_init.cmake")) {
    throw "pico-sdk not found at '$env:PICO_SDK_PATH' (set `$env:PICO_SDK_PATH)"
}

# --- arm-none-eabi-gcc (target compiler) ---
$arm = (Get-Command arm-none-eabi-gcc -ErrorAction SilentlyContinue).Source
if (-not $arm) {
    $arm = Get-ChildItem "$env:USERPROFILE\arm-none-eabi-gcc" -Recurse -Filter arm-none-eabi-gcc.exe -ErrorAction SilentlyContinue |
           Select-Object -First 1 -ExpandProperty FullName
}
if (-not $arm) { throw "arm-none-eabi-gcc not found (install the xpack toolchain or pico-setup-windows)" }
$armbin = Split-Path -Parent $arm

# --- host gcc + cmake + ninja (WinLibs) ---
$cmake = (Get-Command cmake -ErrorAction SilentlyContinue).Source
if (-not $cmake) {
    $cmake = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter cmake.exe -ErrorAction SilentlyContinue |
             Where-Object { $_.FullName -match 'WinLibs' } | Select-Object -First 1 -ExpandProperty FullName
}
if (-not $cmake) { throw "cmake not found (winget install BrechtSanders.WinLibs.POSIX.UCRT)" }
$hostbin = Split-Path -Parent $cmake

$env:PATH = "$armbin;$hostbin;$env:PATH"
Write-Host "PICO_SDK_PATH = $env:PICO_SDK_PATH"
Write-Host "arm gcc       = $arm"
Write-Host "host/cmake    = $hostbin`n"

& $cmake -S $here -B "$here\build" -G Ninja @args
& $cmake --build "$here\build"

Write-Host "`nArtifacts:"
Get-ChildItem "$here\build" -Filter "wsl_phase8b_rp2040.*" |
    Select-Object Name, @{n='KB';e={[math]::Round($_.Length/1KB,1)}} | Format-Table -AutoSize
