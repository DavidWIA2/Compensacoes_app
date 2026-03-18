# Compensações

Aplicativo desktop em Python para cadastro, consulta e acompanhamento de compensações ambientais ligadas à supressão de árvores no município de São Carlos - SP.

O projeto foi evoluído para um fluxo mais completo de operação: leitura e edição de planilhas Excel, filtros e métricas, mapa com apoio geoespacial, exportações em vários formatos, diagnósticos, logs e pipeline de release para distribuição no Windows.

## O que o app faz

- Abre uma planilha padrão de compensações e transforma as linhas em registros editáveis.
- Permite cadastrar, alterar, excluir, filtrar e pesquisar registros com interface gráfica.
- Exibe métricas consolidadas, pendências e visão analítica por filtros.
- Trabalha com mapa, microbacias e apoio geoespacial.
- Faz geocodificação em lote para apoiar o preenchimento de coordenadas.
- Exporta dados em `CSV`, `Excel` e `PDF`, incluindo ficha individual e relatório de painel.
- Mantém backups da planilha e permite restaurar versões anteriores.
- Gera logs e diagnóstico para suporte.
- Suporta verificação de atualização por `latest.json`.

## Stack principal

- Python 3.12
- PySide6
- openpyxl
- pandas
- reportlab
- geopandas
- shapely
- pyogrio
- fiona
- pyproj
- requests
- PyInstaller
- pytest

## Estrutura do projeto

```text
Compensacoes_app/
|-- app/           Codigo principal da aplicacao
|-- assets/        Icones e recursos visuais
|-- data/          Planilha modelo, microbacias e cache local
|-- docs/          Documentacao de operacao e release
|-- scripts/       Automacoes de validacao, build e release
|-- tests/         Suite automatizada
|-- run.py         Ponto de entrada da aplicacao
|-- README.md
`-- requirements.txt
```

## Planilha modelo

O arquivo de referência está em [data/modelo_planilha_compensacoes.xlsx](data/modelo_planilha_compensacoes.xlsx).

Para o app funcionar corretamente, a estrutura da planilha deve manter os cabeçalhos esperados pelo sistema.

## Como executar localmente

No Windows PowerShell:

```powershell
git clone https://github.com/DavidWIA2/Compensacoes_app.git
cd Compensacoes_app
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Se você já usa a venv do projeto em Python 3.12:

```powershell
.\.venv312\Scripts\activate
python run.py
```

## Testes e validação

Rodar a suíte completa:

```powershell
.\.venv312\Scripts\python.exe -m pytest -q
```

Validação rápida do app e do ambiente:

```powershell
.\scripts\validate.ps1 -PythonExe .\.venv312\Scripts\python.exe
```

## Build e distribuição

Build local de release:

```powershell
.\scripts\build_release.ps1 -PythonExe .\.venv312\Scripts\python.exe -Clean
```

O fluxo de release atual gera:

- pacote `.zip`
- checksum `.sha256`
- notas de release
- guia de distribuição
- `latest.json` para o atualizador
- script de verificação de checksum
- script do instalador Inno Setup

Para detalhes de empacotamento, instalador, publicação e assinatura de código, veja [docs/release.md](docs/release.md).

## Distribuição sem assinatura

O app pode ser usado normalmente sem assinatura digital, o que é suficiente para uso interno ou distribuição restrita. Nesse cenário, o recomendado é publicar o artefato com o `.sha256` e orientar a validação com:

```powershell
.\verify_release_checksum.ps1 -ArtifactPath .\Compensacoes-vX.Y.Z-win64.zip
```

## Releases

As versões publicadas ficam em [GitHub Releases](https://github.com/DavidWIA2/Compensacoes_app/releases).

## Autor

David Wiliam Pinheiro de Oliveira
