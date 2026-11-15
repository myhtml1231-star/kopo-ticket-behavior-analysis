$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path $py)) { $py = 'python' }
$workerActive = $false
if (Test-Path 'worker_status.json') {
    try {
        $workerStatus = Get-Content -Raw -Encoding UTF8 'worker_status.json' | ConvertFrom-Json
        $workerActive = (([DateTimeOffset]::UtcNow - [DateTimeOffset]::Parse($workerStatus.heartbeat)).TotalSeconds -lt 8)
    } catch { $workerActive = $false }
}
if ((Test-Path '.env') -and -not $workerActive) { Start-Process -FilePath $py -ArgumentList 'worker.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden }
$webActive = $false
try { $null = Invoke-WebRequest -Uri 'http://127.0.0.1:5050/api/state' -TimeoutSec 2; $webActive = $true } catch { }
if (-not $webActive) { Start-Process -FilePath $py -ArgumentList 'app.py' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden }
Start-Process 'http://127.0.0.1:5050/practice/intro'
