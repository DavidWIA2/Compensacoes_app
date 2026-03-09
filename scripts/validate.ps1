param(
    [string]$PythonExe = "C:\Users\david\AppData\Local\Programs\Python\Python312\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PythonExe)) {
    throw "Python nao encontrado em: $PythonExe"
}

Write-Host "Usando Python:" $PythonExe
& $PythonExe --version
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Compilando os modulos..."
& $PythonExe -m compileall app run.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Executando testes..."
$env:QT_QPA_PLATFORM = "offscreen"
& $PythonExe -m pytest
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
