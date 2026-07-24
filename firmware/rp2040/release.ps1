<#
.SYNOPSIS
Build and verify the deterministic release + FI-1 RP2040 artifact bundle.

.DESCRIPTION
The release path is intentionally narrower than build.ps1: Release mode,
PICO_BOARD=pico, DEBUG_USB=OFF, and no ambient compiler/linker flags. It builds
both images, runs the host safety tests unless skipped, writes
release/firmware_manifest.json, and then independently verifies source
fingerprints, UF2 hashes, and the identities embedded in both UF2 payloads.

Use -VerifyOnly to verify an existing bundle without an ARM toolchain.
#>
[CmdletBinding()]
param(
    [switch]$VerifyOnly,
    [switch]$SkipHostTests,
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $OutputDirectory) {
    $OutputDirectory = Join-Path $here "release"
}
$manifest = Join-Path $OutputDirectory "firmware_manifest.json"

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][AllowEmptyCollection()][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "'$FilePath $($Arguments -join ' ')' failed with exit code $LASTEXITCODE"
    }
}

function Find-Executable {
    param([string]$Name, [string[]]$FallbackRoots = @())
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($root in $FallbackRoots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        $match = Get-ChildItem -LiteralPath $root -Recurse -Filter "$Name.exe" -ErrorAction SilentlyContinue |
                 Select-Object -First 1 -ExpandProperty FullName
        if ($match) { return $match }
    }
    throw "$Name not found"
}

$python = (Get-Command py -ErrorAction SilentlyContinue).Source
$pythonPrefix = @("-3")
if (-not $python) {
    $python = (Get-Command python -ErrorAction SilentlyContinue).Source
    $pythonPrefix = @()
}
if (-not $python) { throw "Python 3 not found" }
$provenance = Join-Path $here "release_provenance.py"

if ($VerifyOnly) {
    Invoke-Checked -FilePath $python -Arguments ($pythonPrefix + @(
        $provenance, "verify-manifest", "--source-dir", $here, "--manifest", $manifest
    ))
    Write-Host "VERIFIED: $manifest"
    exit 0
}

foreach ($name in "CFLAGS", "CXXFLAGS", "CPPFLAGS", "LDFLAGS") {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    if ($value) {
        throw "Ambient $name is set. Clear it before a controlled release build."
    }
}

if (-not $env:PICO_SDK_PATH) {
    $env:PICO_SDK_PATH = Join-Path $env:USERPROFILE "pico-sdk"
}
if (-not (Test-Path -LiteralPath (Join-Path $env:PICO_SDK_PATH "pico_sdk_init.cmake"))) {
    throw "pico-sdk not found at '$env:PICO_SDK_PATH' (set PICO_SDK_PATH)"
}

$wingetRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
$arm = Find-Executable "arm-none-eabi-gcc" @((Join-Path $env:USERPROFILE "arm-none-eabi-gcc"))
$cmake = Find-Executable "cmake" @($wingetRoot)
$ninja = Find-Executable "ninja" @($wingetRoot)
$gcc = Find-Executable "gcc" @($wingetRoot)
$env:PATH = "$(Split-Path -Parent $arm);$(Split-Path -Parent $cmake);$env:PATH"

if (-not $SkipHostTests) {
    $testDir = Join-Path $here "test"
    $testInclude = Join-Path $testDir "stubs"
    $hostBuilds = @(
        @{ Name="test_main"; Args=@("-std=c11","-Wall","-Wextra","-Werror","-I",$testDir,"-I",$testInclude,(Join-Path $testDir "test_main.c")) },
        @{ Name="test_v11"; Args=@("-std=c11","-Wall","-Wextra","-Werror","-I",$testDir,"-I",$testInclude,
              "-DCAM_SA_STOP_ENABLED=1","-DCAM_SA_TRIP='f'","-DCAM_SA_GRACE_MS=150u",
              "-DCAM_TA1_STOP_ENABLED=1","-DCAM_TA1_TRIP='f'","-DCAM_TA1_GRACE_MS=150u",
              "-DINTERLOCK_ECHO_ENABLED=1","-DMOTION_NO_RUN_ENABLED=1",(Join-Path $testDir "test_v11.c")) },
        @{ Name="test_v12"; Args=@("-std=c11","-Wall","-Wextra","-Werror","-I",$testDir,"-I",$testInclude,(Join-Path $testDir "test_v12.c")) },
        @{ Name="test_fi1"; Args=@("-std=c11","-Wall","-Wextra","-Werror","-I",$testDir,"-I",$testInclude,
              "-DFI1_ENABLED=1",(Join-Path $testDir "test_fi1.c")) }
    )
    foreach ($test in $hostBuilds) {
        $exe = Join-Path $testDir "$($test.Name).exe"
        Invoke-Checked -FilePath $gcc -Arguments (@($test.Args) + @("-o", $exe))
        Invoke-Checked -FilePath $exe -Arguments @()
    }
}

$releaseBuild = Join-Path $here "build"
$fi1Build = Join-Path $here "build_fi1"
Invoke-Checked -FilePath $cmake -Arguments @(
    "-S", $here, "-B", $releaseBuild, "-G", "Ninja",
    "-DCMAKE_BUILD_TYPE=Release", "-DPICO_BOARD=pico", "-DDEBUG_USB=OFF", "-DFI1_BUILD=OFF"
)
Invoke-Checked -FilePath $cmake -Arguments @("--build", $releaseBuild, "--clean-first")
Invoke-Checked -FilePath $cmake -Arguments @(
    "-S", $here, "-B", $fi1Build, "-G", "Ninja",
    "-DCMAKE_BUILD_TYPE=Release", "-DPICO_BOARD=pico", "-DDEBUG_USB=OFF", "-DFI1_BUILD=ON"
)
Invoke-Checked -FilePath $cmake -Arguments @("--build", $fi1Build, "--clean-first")

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$releaseUf2 = Join-Path $OutputDirectory "wsl_phase8b_rp2040.uf2"
$fi1Uf2 = Join-Path $OutputDirectory "wsl_phase8b_rp2040_FI1.uf2"
Copy-Item -LiteralPath (Join-Path $releaseBuild "wsl_phase8b_rp2040.uf2") -Destination $releaseUf2 -Force
Copy-Item -LiteralPath (Join-Path $fi1Build "wsl_phase8b_rp2040_FI1.uf2") -Destination $fi1Uf2 -Force

Invoke-Checked -FilePath $python -Arguments ($pythonPrefix + @(
    $provenance, "create-manifest",
    "--source-dir", $here,
    "--release-uf2", $releaseUf2,
    "--release-header", (Join-Path $releaseBuild "build_id.h"),
    "--release-build-dir", $releaseBuild,
    "--fi1-uf2", $fi1Uf2,
    "--fi1-header", (Join-Path $fi1Build "build_id.h"),
    "--fi1-build-dir", $fi1Build,
    "--sdk-dir", $env:PICO_SDK_PATH,
    "--compiler", $arm,
    "--cmake", $cmake,
    "--ninja", $ninja,
    "--output", $manifest
))
Invoke-Checked -FilePath $python -Arguments ($pythonPrefix + @(
    $provenance, "verify-manifest", "--source-dir", $here, "--manifest", $manifest
))

$parsed = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
Write-Host "`nVERIFIED RP2040 release bundle:"
foreach ($image in $parsed.images) {
    Write-Host ("  {0,-7} {1}  sha256={2}" -f `
        $image.variant, $image.identity.'id.build', $image.image.sha256)
}
Write-Host "  manifest $manifest"
Write-Host ("  deploy WSL_RP2040_BUILD_ALLOWLIST={0}" -f `
    $parsed.deployment_identity.build_allowlist[0])
Write-Host ("  deploy WSL_RP2040_CFG_ALLOWLIST={0}" -f `
    $parsed.deployment_identity.config_allowlist[0])
