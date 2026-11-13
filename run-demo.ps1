param(
    [switch]$HealthCheckOnly,
    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,
    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = $PSScriptRoot
$frontendDirectory = Join-Path $projectRoot "frontend"
$runDirectory = Join-Path $projectRoot ".run"
$backendScript = Join-Path $projectRoot "run-backend.ps1"
$frontendScript = Join-Path $projectRoot "run-frontend.ps1"
$pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"
$viteExecutable = Join-Path $frontendDirectory "node_modules\vite\bin\vite.js"
$backendBaseUrl = "http://127.0.0.1:$BackendPort"
$backendHealthUrl = "$backendBaseUrl/api/v1/health"
$frontendUrl = "http://127.0.0.1:$FrontendPort"
$originalApiPort = $env:API_PORT
$originalFrontendOrigins = $env:FRONTEND_ORIGINS
$originalFrontendApiUrl = $env:VITE_API_BASE_URL

function Wait-ForService {
    param(
        [string]$Name,
        [string]$Url,
        [System.Diagnostics.Process]$Process,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) {
            throw "$Name stopped before it became ready. Check the logs in .run."
        }
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 750
        }
    }
    throw "$Name did not become ready within $TimeoutSeconds seconds."
}

function Assert-PortAvailable {
    param([int]$Port)

    $listener = Get-NetTCPConnection `
        -LocalPort $Port `
        -State Listen `
        -ErrorAction SilentlyContinue
    if ($listener) {
        throw "Port $Port is already in use. Stop the existing service and try again."
    }
}

Write-Host "Preparing the Copart Search Assistant..." -ForegroundColor Cyan
& $backendScript -PrepareOnly
& $frontendScript -PrepareOnly
Assert-PortAvailable -Port $BackendPort
Assert-PortAvailable -Port $FrontendPort

New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
$logFiles = @(
    "backend.out.log",
    "backend.err.log",
    "frontend.out.log",
    "frontend.err.log"
)
foreach ($logFile in $logFiles) {
    $path = Join-Path $runDirectory $logFile
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

$backendProcess = $null
$frontendProcess = $null
try {
    $env:API_PORT = [string]$BackendPort
    $env:FRONTEND_ORIGINS = $frontendUrl
    $backendProcess = Start-Process `
        -FilePath $pythonExecutable `
        -ArgumentList @("-m", "backend.main") `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runDirectory "backend.out.log") `
        -RedirectStandardError (Join-Path $runDirectory "backend.err.log") `
        -PassThru

    Wait-ForService -Name "Backend" -Url $backendHealthUrl -Process $backendProcess
    Write-Host "Backend is ready." -ForegroundColor Green

    $env:VITE_API_BASE_URL = $backendBaseUrl
    $nodeExecutable = (Get-Command node -ErrorAction Stop).Source
    $frontendProcess = Start-Process `
        -FilePath $nodeExecutable `
        -ArgumentList @(
            "`"$viteExecutable`"",
            "--host",
            "127.0.0.1",
            "--port",
            [string]$FrontendPort
        ) `
        -WorkingDirectory $frontendDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runDirectory "frontend.out.log") `
        -RedirectStandardError (Join-Path $runDirectory "frontend.err.log") `
        -PassThru

    Wait-ForService -Name "Frontend" -Url $frontendUrl -Process $frontendProcess
    Write-Host "Frontend is ready." -ForegroundColor Green
    if ($HealthCheckOnly) {
        Write-Host "Combined startup health check passed." -ForegroundColor Green
        return
    }
    Write-Host "Opening $frontendUrl" -ForegroundColor Cyan
    Write-Host "Press Ctrl+C here to stop both services." -ForegroundColor Yellow
    Start-Process $frontendUrl

    while ($true) {
        $backendProcess.Refresh()
        $frontendProcess.Refresh()
        if ($backendProcess.HasExited -or $frontendProcess.HasExited) {
            throw "A service stopped unexpectedly. Check the logs in .run."
        }
        Start-Sleep -Seconds 1
    }
} finally {
    $env:API_PORT = $originalApiPort
    $env:FRONTEND_ORIGINS = $originalFrontendOrigins
    $env:VITE_API_BASE_URL = $originalFrontendApiUrl
    foreach ($process in @($frontendProcess, $backendProcess)) {
        if ($null -ne $process) {
            $process.Refresh()
            if (-not $process.HasExited) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Write-Host "Demo services stopped." -ForegroundColor Cyan
}
