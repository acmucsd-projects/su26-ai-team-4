param([switch]$Restart)

$ErrorActionPreference = 'Stop'
$demoRepo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$demoRoot = Join-Path $demoRepo 'local_experiments/gis_context_v2'
$demoPython = Join-Path $demoRoot '.venv/Scripts/python.exe'
$demoPidPath = Join-Path $demoRoot 'dashboard.pid'
$demoErrorLog = Join-Path $demoRoot 'dashboard.stderr.log'
if (-not (Test-Path -LiteralPath $demoPython)) {
    throw 'Create the ignored GIS environment and install app/backend/requirements-demo.txt first.'
}

Push-Location $demoRepo
$previousSceneMode = $env:DEMO_SCENES_ONLY
$previousContextRoot = $env:GIS_CONTEXT_ROOT
try {
    & $demoPython -B -m app.backend.gis_context.export_dashboard
    if ($LASTEXITCODE -ne 0) { throw 'Reviewed overlay export failed; existing server was left running.' }
    if (Test-Path -LiteralPath $demoPidPath) {
        $demoServerId = [int](Get-Content -LiteralPath $demoPidPath -Raw).Trim()
        $demoExisting = Get-CimInstance Win32_Process -Filter "ProcessId = $demoServerId"
        if ($demoExisting) {
            # Never stop a reused PID or a server launched from another environment.
            if ($demoExisting.ExecutablePath -ne $demoPython -or
                $demoExisting.CommandLine -notmatch '-m\s+uvicorn\s+app\.backend\.api:app\s+--host\s+127\.0\.0\.1\s+--port\s+8000') {
                throw 'The saved PID does not identify this local demo. Refusing to stop it.'
            }
            if (-not $Restart) {
                Write-Output 'Local demo is already running at http://127.0.0.1:8000/ (use -Restart to reload backend code).'
                return
            }
            # The venv launcher owns a child Python process on Windows.
            & taskkill.exe /PID $demoServerId /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not stop the previous local demo.' }
        }
    }
    $env:DEMO_SCENES_ONLY = '1'
    $env:GIS_CONTEXT_ROOT = Join-Path $demoRoot 'overlays'
    $demoProcess = Start-Process -FilePath $demoPython -ArgumentList @('-B', '-m', 'uvicorn', 'app.backend.api:app', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $demoRepo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $demoRoot 'dashboard.stdout.log') -RedirectStandardError $demoErrorLog -PassThru
    $demoProcess.Id | Set-Content -LiteralPath $demoPidPath
    for ($demoAttempt = 0; $demoAttempt -lt 30; $demoAttempt++) {
        Start-Sleep -Milliseconds 200
        if ($demoProcess.HasExited) { throw "Local server exited. See $demoErrorLog" }
        try { $demoHealth = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 1 } catch { continue }
        if ($demoHealth.mode -eq 'scenes_only') {
            Write-Output 'Local scene-only demo ready at http://127.0.0.1:8000/ (no model inference).'
            return
        }
    }
    throw "Local server did not become ready. See $demoErrorLog"
} finally {
    $env:DEMO_SCENES_ONLY = $previousSceneMode
    $env:GIS_CONTEXT_ROOT = $previousContextRoot
    Pop-Location
}
