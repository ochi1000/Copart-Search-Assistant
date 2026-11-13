param(
    [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"
$exampleEnvFile = Join-Path $projectRoot ".env.example"
$venvDirectory = Join-Path $projectRoot ".venv"
$pythonExecutable = Join-Path $venvDirectory "Scripts\python.exe"
$requirementsFile = Join-Path $projectRoot "requirements.txt"
$requirementsStamp = Join-Path $venvDirectory ".requirements.sha256"

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

$requirementsHash = (Get-FileHash -LiteralPath $requirementsFile -Algorithm SHA256).Hash
$installedHash = if (Test-Path -LiteralPath $requirementsStamp) {
    (Get-Content -Raw -LiteralPath $requirementsStamp).Trim()
} else {
    ""
}

if ($requirementsHash -ne $installedHash) {
    Write-Host "Installing backend dependencies..." -ForegroundColor Cyan
    & $pythonExecutable -m pip install --disable-pip-version-check -r $requirementsFile
    if ($LASTEXITCODE -ne 0) {
        throw "Backend dependency installation failed."
    }
    Set-Content -LiteralPath $requirementsStamp -Value $requirementsHash -Encoding ascii
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
    throw "Set $requiredKey in .env before starting the backend."
}

$browserProvider = [Environment]::GetEnvironmentVariable("BROWSER_PROVIDER")
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
            $chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
        }
        if (-not (Test-Path -LiteralPath $chromePath)) {
            throw "Google Chrome was not found at '$chromePath'. Set CHROME_PATH in .env."
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

if ($PrepareOnly) {
    Write-Host "Backend setup is ready." -ForegroundColor Green
    return
}

Write-Host "Starting the backend at http://127.0.0.1:8000..." -ForegroundColor Green
Push-Location $projectRoot
try {
    & $pythonExecutable -m backend.main
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
