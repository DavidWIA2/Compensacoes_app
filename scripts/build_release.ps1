param(
    [string]$PythonExe = "python",
    [string]$ReleaseDir = "release",
    [string]$ReleaseBaseUrl = "",
    [string]$HomepageUrl = "",
    [string]$NotesFile = "",
    [int]$ReleaseNotesMaxEntries = 20,
    [switch]$BuildInstaller,
    [string]$InstallerCompiler = "ISCC.exe",
    [switch]$RequireInstallerCompiler,
    [switch]$SignArtifacts,
    [string]$SignToolPath = "signtool.exe",
    [string]$CertificatePfxPath = "",
    [string]$CertificatePasswordEnv = "COMPENSACOES_CERT_PASSWORD",
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$SkipTests,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot

function Run-Step {
    param(
        [string]$Label,
        [scriptblock]$Action
    )

    Write-Host ""
    Write-Host "==> $Label" -ForegroundColor Cyan
    & $Action
}

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

function Sign-ReleaseArtifact {
    param(
        [string]$ToolPath,
        [string]$TargetPath,
        [string]$CertificatePath,
        [string]$CertificatePassword,
        [string]$TimestampServer
    )

    if (-not (Test-Path $TargetPath)) {
        throw "Artefato para assinatura nao encontrado: $TargetPath"
    }

    $args = @(
        "sign",
        "/fd", "SHA256",
        "/td", "SHA256",
        "/tr", $TimestampServer,
        "/f", $CertificatePath
    )
    if (-not [string]::IsNullOrWhiteSpace($CertificatePassword)) {
        $args += @("/p", $CertificatePassword)
    }
    $args += $TargetPath

    & $ToolPath @args
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Push-Location $RepoRoot
try {
    if (-not $CertificatePfxPath -and $env:COMPENSACOES_CERT_PFX) {
        $CertificatePfxPath = $env:COMPENSACOES_CERT_PFX
    }

    if ($Clean) {
        Run-Step "Limpando artefatos antigos" {
            foreach ($dir in @("build", "dist", $ReleaseDir)) {
                if (Test-Path $dir) {
                    Remove-Item -Recurse -Force $dir
                }
            }
        }
    }

    Run-Step "Validando Python" {
        & $PythonExe --version
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    Run-Step "Gerando metadados de versao do executavel" {
        & $PythonExe scripts/generate_version_info.py
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    if (-not $SkipTests) {
        Run-Step "Executando testes automatizados" {
            $env:QT_QPA_PLATFORM = "offscreen"
            & $PythonExe -m pytest -q
            if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        }
    }

    Run-Step "Gerando build com PyInstaller" {
        & $PythonExe -m PyInstaller --noconfirm Compensacoes.spec
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    $version = & $PythonExe -c "from app import __version__; print(__version__)"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $artifactRoot = Join-Path $ReleaseDir "Compensacoes-v$version-win64"
    $zipPath = "$artifactRoot.zip"
    $hashPath = "$artifactRoot.sha256"
    $notesMarkdownPath = "$artifactRoot-notes.md"
    $notesTextPath = "$artifactRoot-notes.txt"
    $manifestPath = Join-Path $ReleaseDir "latest.json"
    $installerScriptPath = Join-Path "build" "installer\CompensacoesInstaller.iss"
    $installerArtifactRoot = Join-Path $ReleaseDir "Compensacoes-Setup-v$version-win64"
    $installerExePath = "$installerArtifactRoot.exe"
    $installerHashPath = "$installerArtifactRoot.sha256"
    $zipFileName = Split-Path $zipPath -Leaf
    $downloadUrl = ""
    if ($ReleaseBaseUrl) {
        $downloadUrl = ($ReleaseBaseUrl.TrimEnd('/')) + "/" + $zipFileName
    }
    $primaryArtifactPath = $zipPath
    $primaryHashPath = $hashPath
    $primaryFileName = $zipFileName
    $mainExePath = Join-Path "dist\Compensacoes" "Compensacoes.exe"
    $notesManifestSource = $notesTextPath

    Run-Step "Preparando pasta de release" {
        New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
    }

    if ($NotesFile -and -not (Test-Path $NotesFile)) {
        throw "Arquivo de notas da release nao encontrado: $NotesFile"
    }

    Run-Step "Gerando notas da release" {
        $notesArgs = @(
            "scripts/generate_release_notes.py",
            "--repo-root", $RepoRoot,
            "--version", $version,
            "--markdown-output", $notesMarkdownPath,
            "--text-output", $notesTextPath,
            "--max-entries", "$ReleaseNotesMaxEntries"
        )
        & $PythonExe @notesArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    if ($NotesFile) {
        $notesManifestSource = $NotesFile
    }

    if ($SignArtifacts) {
        $resolvedSignTool = Resolve-CommandPath $SignToolPath
        if (-not $resolvedSignTool) {
            throw "Ferramenta de assinatura nao encontrada: $SignToolPath"
        }
        if (-not $CertificatePfxPath) {
            throw "CertificatePfxPath nao informado e COMPENSACOES_CERT_PFX nao definido."
        }
        if (-not (Test-Path $CertificatePfxPath)) {
            throw "Certificado para assinatura nao encontrado: $CertificatePfxPath"
        }

        $certificatePassword = [Environment]::GetEnvironmentVariable($CertificatePasswordEnv)

        Run-Step "Assinando executavel principal" {
            Sign-ReleaseArtifact `
                -ToolPath $resolvedSignTool `
                -TargetPath $mainExePath `
                -CertificatePath $CertificatePfxPath `
                -CertificatePassword $certificatePassword `
                -TimestampServer $TimestampUrl
        }
    }

    Run-Step "Empacotando release" {
        if (Test-Path $zipPath) {
            Remove-Item -Force $zipPath
        }
        Compress-Archive -Path "dist\\Compensacoes\\*" -DestinationPath $zipPath -CompressionLevel Optimal
    }

    Run-Step "Gerando checksum" {
        $hash = (Get-FileHash -Algorithm SHA256 $zipPath).Hash.ToLowerInvariant()
        Set-Content -Path $hashPath -Value "$hash  $(Split-Path $zipPath -Leaf)"
    }

    Run-Step "Gerando script do instalador" {
        $installerArgs = @(
            "scripts/generate_installer_script.py",
            "--output", $installerScriptPath,
            "--source-dir", "dist\\Compensacoes",
            "--output-dir", $ReleaseDir,
            "--version", $version,
            "--base-filename", (Split-Path $installerArtifactRoot -Leaf)
        )
        if ($HomepageUrl) {
            $installerArgs += @("--publisher-url", $HomepageUrl, "--support-url", $HomepageUrl, "--updates-url", $HomepageUrl)
        }
        & $PythonExe @installerArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    if ($BuildInstaller) {
        $resolvedInstallerCompiler = Resolve-CommandPath $InstallerCompiler
        if (-not $resolvedInstallerCompiler) {
            $message = "Compilador do instalador nao encontrado: $InstallerCompiler"
            if ($RequireInstallerCompiler) {
                throw $message
            }
            Write-Warning "$message. O script .iss foi gerado, mas o instalador nao sera compilado."
        }
        else {
            Run-Step "Compilando instalador com Inno Setup" {
                & $resolvedInstallerCompiler $installerScriptPath
                if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
            }

            if (Test-Path $installerExePath) {
                if ($SignArtifacts) {
                    $certificatePassword = [Environment]::GetEnvironmentVariable($CertificatePasswordEnv)
                    Run-Step "Assinando instalador" {
                        Sign-ReleaseArtifact `
                            -ToolPath $resolvedSignTool `
                            -TargetPath $installerExePath `
                            -CertificatePath $CertificatePfxPath `
                            -CertificatePassword $certificatePassword `
                            -TimestampServer $TimestampUrl
                    }
                }

                Run-Step "Gerando checksum do instalador" {
                    $installerHash = (Get-FileHash -Algorithm SHA256 $installerExePath).Hash.ToLowerInvariant()
                    Set-Content -Path $installerHashPath -Value "$installerHash  $(Split-Path $installerExePath -Leaf)"
                }

                $primaryArtifactPath = $installerExePath
                $primaryHashPath = $installerHashPath
                $primaryFileName = Split-Path $installerExePath -Leaf
                if ($ReleaseBaseUrl) {
                    $downloadUrl = ($ReleaseBaseUrl.TrimEnd('/')) + "/" + $primaryFileName
                }
            }
        }
    }

    Run-Step "Gerando manifest de release" {
        $manifestArgs = @(
            "scripts/generate_release_manifest.py",
            "--output", $manifestPath,
            "--version", $version,
            "--filename", $primaryFileName,
            "--sha256-file", $primaryHashPath
        )
        if ($downloadUrl) {
            $manifestArgs += @("--download-url", $downloadUrl)
        }
        if ($HomepageUrl) {
            $manifestArgs += @("--homepage-url", $HomepageUrl)
        }
        if ($notesManifestSource) {
            $manifestArgs += @("--notes-file", $notesManifestSource)
        }
        & $PythonExe @manifestArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }

    Write-Host ""
    Write-Host "Release pronta:" -ForegroundColor Green
    Write-Host "  ZIP : $zipPath"
    Write-Host "  SHA : $hashPath"
    Write-Host "  NMD : $notesMarkdownPath"
    Write-Host "  NTX : $notesTextPath"
    Write-Host "  ISS : $installerScriptPath"
    if (Test-Path $installerExePath) {
        Write-Host "  SET : $installerExePath"
        Write-Host "  S+H : $installerHashPath"
    }
    Write-Host "  MAN : $manifestPath"
}
finally {
    Pop-Location
}
