# Supabase

Este projeto foi preparado para usar o Supabase como camada Postgres remota sem
colocar dados de producao ou credenciais sensiveis dentro do repositorio.

## O que entrou no repositorio

- `supabase/migrations/`: schema inicial equivalente ao banco SQLite atual.
- `supabase/seed.sql`: seed vazio por seguranca.
- `scripts/sync_sqlite_to_supabase.py`: carga administrativa para migrar o banco
  local atual para o Postgres remoto.

## Estrategia recomendada

No curto prazo:

1. O aplicativo continua usando o banco local `SQLite`.
2. O Supabase passa a ser a base central remota.
3. A carga inicial da base remota e feita por um script administrativo.

No medio prazo:

1. Criar uma camada backend confiavel para mediar o acesso ao Supabase.
2. Evitar embutir senha de banco ou `service_role` no app desktop.
3. Migrar o runtime do app para ler e gravar via backend.

## Como subir o schema

Depois de instalar a CLI do Supabase e ligar o repositorio ao projeto:

```powershell
supabase db push --db-url "postgres://..."
```

As migrations presentes em `supabase/migrations/` tambem podem ser executadas
automaticamente pela integracao GitHub do Supabase quando configurada para o
branch de producao.

## Como migrar os dados do SQLite atual

Instale as dependencias administrativas:

```powershell
pip install -r requirements-dev.txt
```

Opcionalmente, copie `.env.supabase.example` para `.env.supabase` e preencha a
connection string para nao precisar passá-la na linha de comando.

Rode um dry-run:

```powershell
python .\scripts\sync_sqlite_to_supabase.py --db-url "postgres://..." --dry-run
```

Se as contagens estiverem corretas, rode a sincronizacao real:

```powershell
python .\scripts\sync_sqlite_to_supabase.py --db-url "postgres://..."
```

O script:

- le o `data/state/compensacoes.db`;
- apaga os dados atuais das tabelas remotas equivalentes;
- recria `workbooks`, `records`, `plantios`, `audit_events`, `tcras` e `tcra_eventos`;
- preserva IDs, timestamps e payloads JSON.

## Qual connection string usar

Para administracao e sincronizacao:

- prefira a connection string de Postgres mostrada em `Connect` no painel do
  Supabase;
- em rede IPv4 comum, a opcao mais pratica costuma ser o Session Pooler;
- sempre use SSL.

## O que ainda falta para o app usar Supabase em tempo real

- camada de configuracao remota no app;
- autenticacao e modelo de seguranca;
- backend ou API intermediaria para evitar segredo de banco no cliente desktop;
- migracao do fluxo de escrita hoje baseado em `SQLite`.
