# Release Windows

Fluxo recomendado para validar e empacotar o app no Windows.

## Validacao rapida

```powershell
.\scripts\validate.ps1 -PythonExe .\.venv312\Scripts\python.exe
```

Esse passo compila os modulos e roda a suite de testes em modo `offscreen`.

## Build de distribuicao

```powershell
.\scripts\build_release.ps1 -PythonExe .\.venv312\Scripts\python.exe -Clean
```

O script:

- gera o arquivo `build/windows_version_info.txt`
- roda os testes automaticamente por padrao
- executa o `PyInstaller` com o `Compensacoes.spec`
- cria um pacote versionado em `release/`
- gera `Compensacoes-v<versao>-win64-notes.md` e `Compensacoes-v<versao>-win64-notes.txt`
- gera um arquivo `.sha256` para conferencia do artefato
- gera um `latest.json` com metadados da release para o atualizador

## Saidas esperadas

Ao final do processo, a pasta `release/` recebe:

- `Compensacoes-v<versao>-win64.zip`
- `Compensacoes-v<versao>-win64.sha256`
- `Compensacoes-v<versao>-win64-notes.md`
- `Compensacoes-v<versao>-win64-notes.txt`
- `latest.json`

## Manifest de atualizacao

Se voce hospedar o arquivo `latest.json` em um servidor ou bucket, a aplicacao pode consultar esse endpoint usando a variavel de ambiente `COMPENSACOES_UPDATE_URL`.

Exemplo de build com link publico:

```powershell
.\scripts\build_release.ps1 `
  -PythonExe .\.venv312\Scripts\python.exe `
  -ReleaseBaseUrl "https://example.com/downloads" `
  -HomepageUrl "https://example.com/compensacoes" `
  -NotesFile ".\docs\release-notes.txt" `
  -Clean
```

As notas de release sao geradas automaticamente a partir dos commits mais recentes ou do intervalo desde a ultima tag encontrada. Se voce quiser sobrescrever apenas o texto publicado no `latest.json`, pode apontar `-NotesFile` para um arquivo manual; o build continua gerando o `.md` automatico para uso em publicacao.

## Instalador Windows

O pipeline tambem consegue gerar o script do instalador Inno Setup em `build/installer/CompensacoesInstaller.iss`.

Para compilar o instalador `.exe`, instale o Inno Setup e rode:

```powershell
.\scripts\build_release.ps1 `
  -PythonExe .\.venv312\Scripts\python.exe `
  -BuildInstaller `
  -Clean
```

Se o comando `ISCC.exe` estiver no `PATH`, o build tambem produz:

- `Compensacoes-Setup-v<versao>-win64.exe`
- `Compensacoes-Setup-v<versao>-win64.sha256`

Se o Inno Setup nao estiver instalado, o build continua com ZIP + manifest e avisa que o `.iss` foi gerado, pronto para compilar depois.

## Assinatura de codigo

O build suporta assinatura opcional dos binarios com `signtool.exe`:

```powershell
.\scripts\build_release.ps1 `
  -PythonExe .\.venv312\Scripts\python.exe `
  -BuildInstaller `
  -SignArtifacts `
  -CertificatePfxPath ".\certs\release-cert.pfx" `
  -Clean
```

Tambem e possivel deixar o caminho do certificado em `COMPENSACOES_CERT_PFX` e a senha em `COMPENSACOES_CERT_PASSWORD`.

## Publicacao automatizada

O workflow [`windows-release.yml`](C:\Users\david\Desktop\Pen Drive\Compensacoes_app\.github\workflows\windows-release.yml):

- dispara em tags `v*`
- aceita execucao manual com `tag_name`
- roda testes, build, instalador e assinatura opcional
- publica todos os artefatos de `release/` no GitHub Releases
- usa o arquivo `Compensacoes-v<versao>-win64-notes.md` como corpo da release

Para assinatura no GitHub Actions, configure estes secrets:

- `WINDOWS_SIGN_CERT_PFX_B64`
- `WINDOWS_SIGN_CERT_PASSWORD`

O `latest.json` e gerado com links no formato `https://github.com/<repo>/releases/download/<tag>/...`, deixando o atualizador pronto para consumir a release publicada.

## CI

O workflow [`.github/workflows/windows-ci.yml`](C:\Users\david\Desktop\Pen Drive\Compensacoes_app\.github\workflows\windows-ci.yml) usa o mesmo script de build para manter o empacotamento local e o do GitHub Actions alinhados.
