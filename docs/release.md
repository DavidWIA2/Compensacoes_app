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
- gera `Compensacoes-v<versao>-win64-guide.txt` com instrucoes de distribuicao
- gera um arquivo `.sha256` para conferencia do artefato
- gera um `latest.json` com metadados da release para o atualizador
- publica `verify_release_checksum.ps1` na pasta `release/` para facilitar a validacao do arquivo baixado

## Saidas esperadas

Ao final do processo, a pasta `release/` recebe:

- `Compensacoes-v<versao>-win64.zip`
- `Compensacoes-v<versao>-win64.sha256`
- `Compensacoes-v<versao>-win64-guide.txt`
- `Compensacoes-v<versao>-win64-notes.md`
- `Compensacoes-v<versao>-win64-notes.txt`
- `verify_release_checksum.ps1`
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

## Distribuicao restrita sem assinatura

Para uso interno ou distribuicao com publico pequeno, voce pode operar sem code signing:

- publique o artefato principal junto do `.sha256`
- inclua o `Compensacoes-v<versao>-win64-guide.txt`
- oriente o usuario a rodar `.\verify_release_checksum.ps1 -ArtifactPath .\arquivo-baixado`

Isso nao remove avisos do Windows, mas ajuda a validar integridade e a reduzir risco operacional enquanto a distribuicao ainda eh controlada.

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

Para assinatura local futura com certificado no store do Windows, o build tambem aceita:

```powershell
.\scripts\build_release.ps1 `
  -PythonExe .\.venv312\Scripts\python.exe `
  -BuildInstaller `
  -SignArtifacts `
  -CertificateThumbprint "SEU_THUMBPRINT" `
  -CertificateStoreLocation "CurrentUser" `
  -CertificateStoreName "My" `
  -Clean
```

Ou, se preferir selecao por assunto do certificado:

```powershell
.\scripts\build_release.ps1 `
  -PythonExe .\.venv312\Scripts\python.exe `
  -BuildInstaller `
  -SignArtifacts `
  -CertificateSubjectName "Seu Nome ou Razao Social" `
  -Clean
```

As variaveis de ambiente equivalentes sao:

- `COMPENSACOES_CERT_THUMBPRINT`
- `COMPENSACOES_CERT_SUBJECT`
- `COMPENSACOES_CERT_STORE_LOCATION`
- `COMPENSACOES_CERT_STORE_NAME`

Se o `signtool.exe` nao estiver no `PATH`, o build agora tenta localizar automaticamente o executavel no Windows SDK. Depois da assinatura, o pipeline valida os binarios com `signtool verify /pa /v` para falhar cedo se a assinatura ou o timestamp estiverem incorretos.

Para verificar um binario manualmente:

```powershell
.\scripts\verify_signature.ps1 -Path .\release\Compensacoes-Setup-v1.0.0-win64.exe
```

Checklist para assinatura real:

- ter um certificado valido para code signing, via `.pfx` ou store do Windows
- configurar `COMPENSACOES_CERT_PFX` e `COMPENSACOES_CERT_PASSWORD` localmente, se usar `.pfx`
- ou configurar `COMPENSACOES_CERT_THUMBPRINT`/`COMPENSACOES_CERT_SUBJECT` para assinatura via store
- ou definir `WINDOWS_SIGN_CERT_PFX_B64` e `WINDOWS_SIGN_CERT_PASSWORD` no GitHub
- garantir que o runner/maquina tenha `signtool.exe` disponivel no Windows SDK

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
