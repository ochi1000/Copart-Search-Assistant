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
$envFile = Join-Path $projectRoot ".env"
$exampleEnvFile = Join-Path $projectRoot ".env.example"
$venvDirectory = Join-Path $projectRoot ".venv"
$pythonExecutable = Join-Path $venvDirectory "Scripts\python.exe"
$requirementsFile = Join-Path $projectRoot "requirements.txt"
$requirementsStamp = Join-Path $venvDirectory ".requirements.sha256"
$nodeModulesDirectory = Join-Path $frontendDirectory "node_modules"
$viteExecutable = Join-Path $frontendDirectory "node_modules\vite\bin\vite.js"
$backendBaseUrl = "http://127.0.0.1:$BackendPort"
$backendHealthUrl = "$backendBaseUrl/api/v1/health"
$frontendUrl = "http://127.0.0.1:$FrontendPort"
$originalApiPort = $env:API_PORT
$originalFrontendOrigins = $env:FRONTEND_ORIGINS
$originalFrontendApiUrl = $env:VITE_API_BASE_URL

function Get-DotEnvValue {
    param([string]$Name)

    if (-not (Test-Path -LiteralPath $envFile)) {
        return $null
    }

    $line = Get-Content -LiteralPath $envFile | Where-Object {
        $_ -match "^\s*$([regex]::Escape($Name))\s*="
    } | Select-Object -Last 1

    if (-not $line) {
        return $null
    }

    $value = ($line -split "=", 2)[1].Trim()
    return $value.Trim('"').Trim("'")
}

function Prepare-Backend {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw "Python was not found. Install Python 3.11 or newer and try again."
    }

    if (-not (Test-Path -LiteralPath $envFile)) {
        Copy-Item -LiteralPath $exampleEnvFile -Destination $envFile
        Write-Host "Created .env from .env.example." -ForegroundColor Yellow
        throw "Add your Groq or OpenAI API key to .env, then run this script again."
    }

    if (-not (Test-Path -LiteralPath $pythonExecutable)) {
        Write-Host "Creating the Python virtual environment..." -ForegroundColor Cyan
        & python -m venv $venvDirectory
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the Python virtual environment."
        }
    }

    $requirementsHash = (
        Get-FileHash -LiteralPath $requirementsFile -Algorithm SHA256
    ).Hash
    $installedHash = if (Test-Path -LiteralPath $requirementsStamp) {
        (Get-Content -Raw -LiteralPath $requirementsStamp).Trim()
    } else {
        ""
    }

    if ($requirementsHash -ne $installedHash) {
        Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
        & $pythonExecutable -m pip install `
            --disable-pip-version-check `
            -r $requirementsFile
        if ($LASTEXITCODE -ne 0) {
            throw "Backend dependency installation failed."
        }
        Set-Content `
            -LiteralPath $requirementsStamp `
            -Value $requirementsHash `
            -Encoding ascii
    }

    $provider = Get-DotEnvValue "LLM_PROVIDER"
    if (-not $provider) {
        $provider = "groq"
    }
    $requiredKey = if ($provider.ToLowerInvariant() -eq "groq") {
        "GROQ_API_KEY"
    } else {
        "OPENAI_API_KEY"
    }
    $configuredKey = [Environment]::GetEnvironmentVariable($requiredKey)
    if (-not $configuredKey) {
        $configuredKey = Get-DotEnvValue $requiredKey
    }
    if (-not $configuredKey) {
        throw "Set $requiredKey in .env before starting the application."
    }

    $browserProvider = [Environment]::GetEnvironmentVariable(
        "BROWSER_PROVIDER"
    )
    if (-not $browserProvider) {
        $browserProvider = Get-DotEnvValue "BROWSER_PROVIDER"
    }
    if (-not $browserProvider) {
        $browserProvider = "local"
    }

    switch ($browserProvider.ToLowerInvariant()) {
        "local" {
            $chromePath = [Environment]::GetEnvironmentVariable("CHROME_PATH")
            if (-not $chromePath) {
                $chromePath = Get-DotEnvValue "CHROME_PATH"
            }
            if (-not $chromePath) {
                $chromePath = (
                    "C:\Program Files\Google\Chrome\Application\chrome.exe"
                )
            }
            if (-not (Test-Path -LiteralPath $chromePath)) {
                throw (
                    "Google Chrome was not found at '$chromePath'. " +
                    "Set CHROME_PATH in .env."
                )
            }
        }
        "browserless" {
            $browserlessToken = [Environment]::GetEnvironmentVariable(
                "BROWSERLESS_TOKEN"
            )
            if (-not $browserlessToken) {
                $browserlessToken = Get-DotEnvValue "BROWSERLESS_TOKEN"
            }
            if (-not $browserlessToken) {
                throw "Set BROWSERLESS_TOKEN when BROWSER_PROVIDER=browserless."
            }
        }
        default {
            throw "BROWSER_PROVIDER must be either 'local' or 'browserless'."
        }
    }

    Write-Host "Backend setup is ready." -ForegroundColor Green
}

function Prepare-Frontend {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw "Node.js was not found. Install Node.js 20 or newer and try again."
    }
    if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
        throw "npm was not found. Install Node.js 20 or newer and try again."
    }

    if (-not (Test-Path -LiteralPath $nodeModulesDirectory)) {
        Write-Host "Installing frontend dependencies..." -ForegroundColor Cyan
        Push-Location $frontendDirectory
        try {
            & npm.cmd ci
            if ($LASTEXITCODE -ne 0) {
                throw "Frontend dependency installation failed."
            }
        } finally {
            Pop-Location
        }
    }

    Write-Host "Frontend setup is ready." -ForegroundColor Green
}

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
            throw "$Name stopped before it became ready. Start it manually for details."
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
Prepare-Backend
Prepare-Frontend
Assert-PortAvailable -Port $BackendPort
Assert-PortAvailable -Port $FrontendPort

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
            throw "A service stopped unexpectedly. Start it manually for details."
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
