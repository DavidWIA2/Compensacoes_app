param(
    [Parameter(Mandatory = $true)]
    [string]$ArtifactPath,
    [string]$Sha256Path = ""
)

$ErrorActionPreference = "Stop"

$resolvedArtifactPath = (Resolve-Path $ArtifactPath).Path
if (-not $Sha256Path) {
    $Sha256Path = [System.IO.Path]::ChangeExtension($resolvedArtifactPath, ".sha256")
}
$resolvedSha256Path = (Resolve-Path $Sha256Path).Path

$expectedLine = Get-Content -Path $resolvedSha256Path -TotalCount 1
$expectedHash = ($expectedLine -split "\s+")[0].Trim().ToLowerInvariant()
if (-not $expectedHash) {
    throw "Arquivo SHA256 invalido: $resolvedSha256Path"
}

$actualHash = (Get-FileHash -Algorithm SHA256 $resolvedArtifactPath).Hash.ToLowerInvariant()

Write-Host ""
Write-Host "==> Verificando checksum" -ForegroundColor Cyan
Write-Host "  File     : $resolvedArtifactPath"
Write-Host "  SHA file : $resolvedSha256Path"
Write-Host "  Expected : $expectedHash"
Write-Host "  Actual   : $actualHash"

if ($actualHash -ne $expectedHash) {
    throw "Checksum SHA-256 divergente para $resolvedArtifactPath"
}

Write-Host "Checksum confere." -ForegroundColor Green
