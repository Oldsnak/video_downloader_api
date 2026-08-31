# Starts Memurai (Redis-compatible) on localhost:6379 if not already running.
# Memurai Developer auto-stops after 10 days — re-run this script when Celery cannot connect.

$ErrorActionPreference = "Stop"

function Test-RedisPort {
    try {
        $client = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 6379)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

if (Test-RedisPort) {
    Write-Host "Redis already listening on localhost:6379"
    exit 0
}

$memuraiExe = "C:\Program Files\Memurai\memurai.exe"
$memuraiConf = "C:\Program Files\Memurai\memurai.conf"

if (-not (Test-Path $memuraiExe)) {
    Write-Host "Memurai not found. Install with: winget install Memurai.MemuraiDeveloper"
    Write-Host "Or set CELERY_TASK_ALWAYS_EAGER=true in .env to skip Redis for local dev."
    exit 1
}

Write-Host "Starting Memurai on port 6379..."
Start-Process -FilePath $memuraiExe -ArgumentList "`"$memuraiConf`"" -WindowStyle Hidden

for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    if (Test-RedisPort) {
        Write-Host "Memurai is ready (localhost:6379)"
        exit 0
    }
}

Write-Host "Memurai did not start. Try running PowerShell as Administrator:"
Write-Host "  Start-Service Memurai"
exit 1
