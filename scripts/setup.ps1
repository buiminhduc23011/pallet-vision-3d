param([switch]$Vision, [switch]$Camera)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
        & py -3.13 -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 is required for the locked Windows setup.' }
    }
    $pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
    & $pythonExe -m pip install -r backend/requirements.lock
    if ($LASTEXITCODE -ne 0) { throw 'Core dependency installation failed.' }
    & $pythonExe -m pip install --no-deps -e backend
    if ($LASTEXITCODE -ne 0) { throw 'Backend installation failed.' }
    if ($Vision) {
        & $pythonExe -m pip install -e 'backend[vision]'
        if ($LASTEXITCODE -ne 0) { throw 'Vision dependency installation failed. Check Python/PyTorch compatibility.' }
    }
    if ($Camera) {
        & $pythonExe -m pip install -e 'backend[camera]'
        if ($LASTEXITCODE -ne 0) { throw 'RealSense SDK installation failed. Check supported Python/platform wheels.' }
    }
    & npm ci --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    & npm run build --prefix frontend
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    Write-Output 'Setup finished. Model weights are not bundled. Run ./scripts/start.ps1 next.'
} finally { Pop-Location }
