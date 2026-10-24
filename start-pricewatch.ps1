$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendDirectory = Join-Path $projectRoot "backend"
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$port = 8000

if (-not [string]::IsNullOrWhiteSpace($env:PRICEWATCH_PORT)) {
    if (-not [int]::TryParse($env:PRICEWATCH_PORT, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw "PRICEWATCH_PORT debe ser un entero entre 1 y 65535."
    }
}

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "No se encontró el entorno del proyecto en '$python'. Crealo e instalá backend\requirements-dev.txt según README.md."
}

& $python -c "import uvicorn"
if ($LASTEXITCODE -ne 0) {
    throw "Falta uvicorn en el entorno seleccionado. Instalá las dependencias con '.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt'. No se ejecutaron migraciones."
}

Push-Location $backendDirectory
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Falló la migración de PriceWatch (código $LASTEXITCODE). El servidor no se inició."
    }

    Write-Host "PriceWatch se iniciará únicamente en http://127.0.0.1:$port/"
    & $python -m app.main
    if ($LASTEXITCODE -ne 0) {
        throw "PriceWatch terminó con el código $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
