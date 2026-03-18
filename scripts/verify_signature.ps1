param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [string]$SignToolPath = "signtool.exe"
)

$ErrorActionPreference = "Stop"

function Resolve-CommandPath {
    param([string]$CommandName)

    if ([string]::IsNullOrWhiteSpace($CommandName)) {
        return $null
    }

    if (Test-Path $CommandName) {
        return (Resolve-Path $CommandName).Path
    }

    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    return $null
}

function Resolve-DefaultSignTool {
    $sdkRoots = @(
        "C:\Program Files (x86)\Windows Kits\10\bin",
        "C:\Program Files\Windows Kits\10\bin"
    )

    foreach ($root in $sdkRoots) {
        if (-not (Test-Path $root)) {
            continue
        }

        $candidate = Get-ChildItem -Path $root -Recurse -Filter "signtool.exe" -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }

    return $null
}

$resolvedSignTool = Resolve-CommandPath $SignToolPath
if (-not $resolvedSignTool -and $SignToolPath -eq "signtool.exe") {
    $resolvedSignTool = Resolve-DefaultSignTool
}
if (-not $resolvedSignTool) {
    throw "Ferramenta de verificacao nao encontrada: $SignToolPath"
}

$targetPath = (Resolve-Path $Path).Path

Write-Host ""
Write-Host "==> Verificando assinatura" -ForegroundColor Cyan
Write-Host "  Tool : $resolvedSignTool"
Write-Host "  File : $targetPath"

& $resolvedSignTool verify /pa /v $targetPath
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
