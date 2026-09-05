param(
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv-gui\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv-gui. Create the project environment before building."
}

$SavedEnvironment = @{}
foreach ($Name in @("PATH", "PYTHONPATH", "PYTHONHOME", "PYTHONNOUSERSITE")) {
    $SavedEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
}

Push-Location $Root
try {
    # Native hooks scan PATH; unrelated developer tools can contribute large or incompatible DLLs.
    $BasePython = (& $Python -I -c "import sys; print(sys.base_prefix)").Trim()
    if ($LASTEXITCODE -ne 0 -or -not $BasePython) { throw "Could not locate the base Python runtime." }
    $env:PATH = @(
        (Split-Path -Parent $Python),
        $BasePython,
        (Join-Path $BasePython "DLLs"),
        (Join-Path $env:SystemRoot "System32"),
        (Join-Path $env:SystemRoot "System32\Wbem"),
        $env:SystemRoot
    ) -join [IO.Path]::PathSeparator
    $env:PYTHONPATH = $null
    $env:PYTHONHOME = $null
    $env:PYTHONNOUSERSITE = "1"

    if (-not $SkipInstall) {
        & $Python -m pip install -e ".[gui,build]"
        if ($LASTEXITCODE -ne 0) { throw "Build dependencies could not be installed." }
    }

    & $Python scripts\build_icon.py
    if ($LASTEXITCODE -ne 0) { throw "Application icon could not be generated." }

    & $Python -m PyInstaller --noconfirm --clean packaging\windows\wechat_ai_memory.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    & $Python -m PyInstaller --noconfirm --clean packaging\windows\wechat_ai_memory_portable.spec
    if ($LASTEXITCODE -ne 0) { throw "Portable executable build failed." }

    $Archive = Join-Path $Root "outputs\WeChatAIMemory-Windows-x64.zip"
    if (Test-Path -LiteralPath $Archive) {
        Remove-Item -LiteralPath $Archive
    }
    Compress-Archive -Path "dist\WeChatAIMemory\*" -DestinationPath $Archive -CompressionLevel Optimal

    $Portable = Join-Path $Root "outputs\WeChatAIMemory-Portable.exe"
    Copy-Item -LiteralPath "dist\WeChatAIMemory-Portable.exe" -Destination $Portable -Force

    Write-Host "Windows package: $Archive"
    Write-Host "Portable executable: $Portable"
}
finally {
    foreach ($Name in $SavedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $SavedEnvironment[$Name], "Process")
    }
    Pop-Location
}
