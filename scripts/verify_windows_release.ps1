param(
    [string]$Python = ".venv-gui\Scripts\python.exe"
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
    Where-Object { $_.Name -match '^(numpy|imageio)(\.|$)' }
if ($ForbiddenRuntime) {
    throw "Unused media dependencies leaked into the release package: $($ForbiddenRuntime.FullName -join ', ')"
}

$BundledFFmpeg = Get-ChildItem -LiteralPath (Join-Path $Root "dist\WeChatAIMemory") -Recurse -File |
    Where-Object { $_.Name -match '^ffmpeg.*\.exe$' }
if (-not $BundledFFmpeg) {
    throw "The WXGF image decoder was not bundled in the Windows release."
}

New-Item -ItemType Directory -Path $SmokeRoot -Force | Out-Null
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
