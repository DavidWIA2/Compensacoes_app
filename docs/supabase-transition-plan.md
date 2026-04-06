# Plano de transicao definitiva para Supabase

Este plano segue a ordem mais simples, segura e rapida para tirar a producao do Excel/SQLite autoritativo sem reescrever o app de uma vez.

## Objetivo final

- `Supabase` como fonte oficial de leitura e escrita.
- `SQLite` apenas como cache local operacional.
- `Excel` apenas para importacao e exportacao.
- `Demonstracao` sempre isolada da `Producao`.

## Ordem recomendada de commits

1. `feat: protege producao com perfis e RLS no supabase`
   Fase 1. Cria `public.profiles`, trigger a partir de `auth.users`, helper functions de acesso e politicas RLS. O app passa a negar login de producao para usuario nao ativado.

2. `feat: adiciona rpc transacional para mutacoes de compensacoes`
   Cria funcoes SQL/RPC para `add`, `edit`, `delete` e `import` de compensacoes e plantios em transacao unica, com auditoria.

3. `feat: move escrita de compensacoes para supabase`
   O formulario de compensacoes passa a gravar primeiro no Supabase e so depois atualizar o cache local.

4. `feat: adiciona rpc transacional para mutacoes de tcra`
   Cria funcoes SQL/RPC para `save`, `delete`, `bulk actions` e `import` de TCRAs e eventos.

5. `feat: move escrita de tcra para supabase`
   O modulo TCRA passa a usar o backend remoto como fonte autoritativa.

6. `refactor: adota leitura remote-first com cache local`
   Startup, filtros e dashboards passam a tratar o Supabase como origem oficial e o SQLite como cache sincronizado.

7. `refactor: remove autoridade do excel em producao`
   Excel deixa de ser caminho de carga oficial da producao. Fica apenas em importacao/exportacao.

## Fase 1 entregue nesta rodada

- `public.profiles` no Supabase com ativacao por usuario.
- Trigger para manter perfis sincronizados com `auth.users`.
- RLS nas tabelas de producao baseado em usuario ativo.
- Login de producao bloqueado para usuario nao liberado.

## Fase 2 entregue nesta rodada

- RPCs transacionais de compensacoes publicadas no Supabase:
  - `public.rpc_save_compensacao_record`
  - `public.rpc_delete_compensacao_record`
  - `public.rpc_replace_compensacoes_snapshot`
- Helpers privados em `app_private` para normalizacao, upsert, plantios, auditoria e refresh de contadores.
- Camada Python pronta para consumir essas RPCs em [app/services/supabase_compensacoes_rpc_service.py](C:/Users/david.oliveira/Desktop/Pen%20Drive/Compensacoes_app/app/services/supabase_compensacoes_rpc_service.py).
- Sessao autenticada do Supabase agora pode ser reutilizada no app sem novo login, via [app/services/access_service.py](C:/Users/david.oliveira/Desktop/Pen%20Drive/Compensacoes_app/app/services/access_service.py).

## Fase 3 entregue nesta rodada

- `Compensacoes` em `Producao` agora usam o Supabase como caminho principal de escrita para `add`, `edit`, `delete` e `import`, via [app/application/use_cases/authoritative_persistence.py](C:/Users/david.oliveira/Desktop/Pen%20Drive/Compensacoes_app/app/application/use_cases/authoritative_persistence.py).
- Cada mutacao remota passa pelas RPCs de compensacoes em [app/services/supabase_compensacoes_rpc_service.py](C:/Users/david.oliveira/Desktop/Pen%20Drive/Compensacoes_app/app/services/supabase_compensacoes_rpc_service.py).
- Depois de cada escrita remota bem-sucedida, o app faz uma sincronizacao completa do cache local da producao para manter `SQLite` alinhado com a base oficial e com as alteracoes feitas em outras maquinas.
- Se essa sincronizacao completa falhar, o app aplica um fallback local controlado no cache para nao deixar a sessao visual desatualizada, e expõe a pendencia na UI operacional.
- `Demo` e `Local` continuam no fluxo anterior, sem gravacao remota.

## Como ativar um usuario de producao

1. Criar ou confirmar o usuario em `Authentication > Users`.
2. Abrir a tabela `public.profiles`.
3. Marcar `is_active = true`.
4. Definir `role = editor` para uso normal ou `role = admin` para administracao futura.

Enquanto `is_active = false`, o usuario consegue existir no Auth, mas o app nao libera acesso a producao.

## Risco principal remanescente

`Compensacoes` ja escrevem remoto em producao, mas o modulo `TCRA` ainda nao migrou para RPC autoritativa no Supabase. A proxima etapa critica e repetir esse padrao para `save/delete/import` de TCRAs e eventos, mantendo o cache SQLite apenas como espelho operacional.
