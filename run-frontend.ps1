param(
    [switch]$PrepareOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = $PSScriptRoot
$frontendDirectory = Join-Path $projectRoot "frontend"
$nodeModulesDirectory = Join-Path $frontendDirectory "node_modules"

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

if ($PrepareOnly) {
    Write-Host "Frontend setup is ready." -ForegroundColor Green
    return
}

Write-Host "Starting the frontend at http://127.0.0.1:5173..." -ForegroundColor Green
Push-Location $frontendDirectory
try {
    & npm.cmd run dev -- --host 127.0.0.1
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
