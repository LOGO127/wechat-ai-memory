param(
    [string]$Python = ".venv-gui\Scripts\python.exe",
    [int]$PortableMaxMiB = 185,
    [int]$ArchiveMaxMiB = 195,
    [int]$ExtractedMaxMiB = 475
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root $Python
$DirectoryExe = Join-Path $Root "dist\WeChatAIMemory\WeChatAIMemory.exe"
$PortableExe = Join-Path $Root "dist\WeChatAIMemory-Portable.exe"
$Archive = Join-Path $Root "outputs\WeChatAIMemory-Windows-x64.zip"
$PublishedPortable = Join-Path $Root "outputs\WeChatAIMemory-Portable.exe"
$Fixture = Join-Path $Root "examples\demo_chat.json"
$SmokeRoot = Join-Path $Root "work\release-smoke"

foreach ($Path in @($Python, $DirectoryExe, $PortableExe, $Archive, $PublishedPortable, $Fixture)) {
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Missing release input: $Path"
    }
}

$ExpectedVersion = (& $Python -c "from wechat_context_exporter import __version__; print(__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or -not $ExpectedVersion) {
    throw "Could not read the package version."
}

foreach ($Executable in @($DirectoryExe, $PortableExe, $PublishedPortable)) {
    $Version = (Get-Item -LiteralPath $Executable).VersionInfo
    if ($Version.FileVersion -ne $ExpectedVersion -or $Version.ProductVersion -ne $ExpectedVersion) {
        throw "Version mismatch in ${Executable}: expected $ExpectedVersion"
    }
    if ($Version.ProductName -ne "WeChat AI Memory") {
        throw "Unexpected product name in $Executable"
    }
}

$ForbiddenRuntime = Get-ChildItem -LiteralPath (Join-Path $Root "dist\WeChatAIMemory") -Recurse -Force |
    Where-Object { $_.Name -match '^imageio(_ffmpeg)?(\.|$)' }
if ($ForbiddenRuntime) {
    throw "Unused imageio dependency leaked into the release package: $($ForbiddenRuntime.FullName -join ', ')"
}

$BundledFFmpeg = Get-ChildItem -LiteralPath (Join-Path $Root "dist\WeChatAIMemory") -Recurse -File |
    Where-Object { $_.Name -match '^ffmpeg.*\.exe$' }
if ($BundledFFmpeg) {
    throw "Duplicate standalone FFmpeg leaked into the release; WXGF and speech must share PyAV."
}

$UnusedQt = Get-ChildItem -LiteralPath (Join-Path $Root "dist\WeChatAIMemory") -Recurse -File |
    Where-Object { $_.Name -match '^(Qt6(Qml|Quick|Pdf|VirtualKeyboard).*|qtvirtualkeyboardplugin|qpdf)\.dll$' }
if ($UnusedQt) {
    throw "Unused Qt plugins or dependencies leaked into the release: $($UnusedQt.Name -join ', ')"
}

$BundledVad = Get-ChildItem -LiteralPath (Join-Path $Root "dist\WeChatAIMemory") -Recurse -File |
    Where-Object { $_.Name -eq 'silero_vad_v6.onnx' }
if (-not $BundledVad) {
    throw "The faster-whisper VAD model was not bundled in the Windows release."
}

New-Item -ItemType Directory -Path $SmokeRoot -Force | Out-Null
$PackageFiles = Get-ChildItem -LiteralPath (Join-Path $Root "dist\WeChatAIMemory") -Recurse -File
$Sizes = [ordered]@{
    version = $ExpectedVersion
    portable_bytes = (Get-Item -LiteralPath $PublishedPortable).Length
    zip_bytes = (Get-Item -LiteralPath $Archive).Length
    extracted_bytes = ($PackageFiles | Measure-Object -Property Length -Sum).Sum
}
$Sizes | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $SmokeRoot "package-sizes.json") -Encoding utf8
if ($Sizes.portable_bytes -gt $PortableMaxMiB * 1MB -or
    $Sizes.zip_bytes -gt $ArchiveMaxMiB * 1MB -or
    $Sizes.extracted_bytes -gt $ExtractedMaxMiB * 1MB) {
    throw "Release size budget exceeded. Inspect work\release-smoke\package-sizes.json before changing the budget."
}
if ((Get-FileHash -LiteralPath $PortableExe).Hash -ne (Get-FileHash -LiteralPath $PublishedPortable).Hash) {
    throw "The published portable EXE does not match the tested build."
}

& $Python scripts\package_runtime_smoke.py `
    --exe $DirectoryExe `
    --output (Join-Path $SmokeRoot "directory\runtime.json")
if ($LASTEXITCODE -ne 0) { throw "Directory package media runtime test failed." }

& $Python scripts\package_runtime_smoke.py `
    --exe $PortableExe `
    --output (Join-Path $SmokeRoot "portable\runtime.json")
if ($LASTEXITCODE -ne 0) { throw "Portable package media runtime test failed." }

& $Python scripts\package_gui_smoke.py `
    --exe $DirectoryExe `
    --fixture $Fixture `
    --output (Join-Path $SmokeRoot "directory\filtered.pdf")
if ($LASTEXITCODE -ne 0) { throw "Directory package GUI smoke test failed." }

& $Python scripts\package_gui_smoke.py `
    --exe $PortableExe `
    --fixture $Fixture `
    --output (Join-Path $SmokeRoot "portable\filtered.pdf")
if ($LASTEXITCODE -ne 0) { throw "Portable package GUI smoke test failed." }

$Hashes = @($Archive, $PublishedPortable) | ForEach-Object {
    $Hash = Get-FileHash -Algorithm SHA256 -LiteralPath $_
    "{0}  {1}" -f $Hash.Hash.ToLowerInvariant(), (Split-Path -Leaf $_)
}
$Hashes | Set-Content -LiteralPath (Join-Path $Root "outputs\SHA256SUMS.txt") -Encoding ascii

Write-Host "Windows release verified at version $ExpectedVersion."
Write-Host ("Portable {0:N1} MiB; ZIP {1:N1} MiB; extracted {2:N1} MiB." -f `
    ($Sizes.portable_bytes / 1MB), ($Sizes.zip_bytes / 1MB), ($Sizes.extracted_bytes / 1MB))
