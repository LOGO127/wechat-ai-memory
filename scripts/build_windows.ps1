param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv-gui\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv-gui. Create the project environment before building."
}

Push-Location $Root
try {
    if (-not $SkipInstall) {
        & $Python -m pip install -e ".[gui,build]"
        if ($LASTEXITCODE -ne 0) { throw "Build dependencies could not be installed." }
    }

    & $Python scripts\build_icon.py
    if ($LASTEXITCODE -ne 0) { throw "Application icon could not be generated." }

    & $Python -m PyInstaller --noconfirm --clean packaging\windows\wechat_ai_memory.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $Archive = Join-Path $Root "outputs\WeChatAIMemory-Windows-x64.zip"
    if (Test-Path -LiteralPath $Archive) {
        Remove-Item -LiteralPath $Archive
    }
    Compress-Archive -Path "dist\WeChatAIMemory\*" -DestinationPath $Archive -CompressionLevel Optimal
    Write-Host "Windows package: $Archive"
}
finally {
    Pop-Location
}
