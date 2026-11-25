param([switch]$Background)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Run ./scripts/setup.ps1 first.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend/dist/index.html'))) { throw 'Build the HMI with npm run build --prefix frontend first.' }
Push-Location $projectRoot
try {
    $envFile = if (Test-Path -LiteralPath '.env') { '.env' } else { '.env.example' }
    if (-not $Background) {
        & $pythonExe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --env-file $envFile
        if ($LASTEXITCODE -ne 0) { throw 'Server exited with an error.' }
        return
    }
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($listener) { throw 'Port 8000 is already in use. Leave the existing instance running or stop it explicitly first.' }
    $logDirectory = Join-Path $projectRoot 'data/logs'
    New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $process = Start-Process -FilePath $pythonExe -ArgumentList @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000', '--env-file', $envFile) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory "$stamp.stdout.log") -RedirectStandardError (Join-Path $logDirectory "$stamp.stderr.log")
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 500
        $process.Refresh()
        if ($process.HasExited) { throw "Server exited. Read logs in $logDirectory" }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/health' -TimeoutSec 2
            if ($health.version) {
                Write-Output "Pallet Vision is running locally at http://127.0.0.1:8000 (PID $($process.Id))."
                Write-Output "To stop this instance: Stop-Process -Id $($process.Id)"
                return
            }
        } catch { if ($attempt -eq 19) { throw 'Server did not become healthy. Inspect the log directory.' } }
    }
} finally { Pop-Location }
