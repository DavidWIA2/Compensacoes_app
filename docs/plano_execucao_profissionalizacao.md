# Plano de Execução - Profissionalização da Plataforma de Gestão Ambiental

## Origem
- Documento de referência: `Projeto Compensacoes_app.docx`
- Branch de referência na extração: `main`
- Commit confirmado no momento da extração: `7a2add5`
- Estado confirmado: `main` sincronizada com `origin/main`, worktree limpa

## Objetivo desta rodada
Conduzir a evolução do produto em 8 pacotes sequenciais, priorizando:
- profissionalização visual e operacional
- robustez de cadastro e sincronização
- consistência institucional
- segurança e administração
- preparação para fechamento de release

## Estado atual já consolidado

### Contexto pronto no projeto
- Branding atualizado para `Plataforma de Gestão Ambiental`
- Tela de acesso/login redesenhada e integrada ao fluxo atual
- Módulo `TCRAs` existente e integrado
- Fluxos `Produção`, `Demonstração` e `Local` disponíveis
- Cache local SQLite com integração Supabase
- Layout principal já passou por várias rodadas de responsividade
- Campos de data com calendário e máscara progressiva
- Exportação PDF de TCRA corrigida

### Observação importante
O finding antigo sobre `importação em lote não atômica` está desatualizado e não deve ser reaberto sem revalidação.

Referência já existente:
- `tests/test_excel_service.py::test_import_records_atomic_does_not_persist_partial_rows_on_failure`

## Pacotes já concluídos

### Pacote 1 de 8 - Concluído
Objetivo:
- Fortalecer integridade cadastral e detectar inconsistências estruturais

Entregas já concluídas:
- serviço de integridade cadastral
- detecção de UID duplicado
- detecção de `Av. Tec.` duplicada
- detecção de identidade fraca/insuficiente
- detecção de coordenadas inválidas ou incompletas
- detecção de compensado sem endereço de plantio ou plantios
- integração com diagnóstico da sessão
- integração com refresh do `DataController`
- integração com snapshot de `Operações`
- exibição de integridade da base no texto técnico de `Operações`

### Pacote 2 de 8 - Concluído
Objetivo:
- Tornar o diagnóstico visível e útil no produto

Entregas já concluídas:
- contexto executivo dinâmico no `Painel`
- exibição de recorte ativo
- exibição de integridade da base
- exibição de modo de leitura
- bloco específico de `integridade cadastral` no `Painel`
- botão `Exportar diagnóstico` no `Painel`
- botão `Exportar diagnóstico` em `Operações`
- tooltip do rodapé com integridade quando houver problema
- adaptação de chamadas antigas do dashboard
- atualização de mocks e testes de janela

### Pacote 3 de 8 - Concluído
Objetivo:
- Profissionalizar a rotina diária em `Operações` e `TCRAs`

Entregas concluídas:
- CTAs mais claros entre `Painel`, `Operações` e `TCRAs`
- resumos mais orientados à ação no `Painel`
- `Operações` com linguagem mais operacional e menos técnica na primeira leitura
- botão `Ver diagnóstico técnico` para separar melhor profundidade e uso diário
- `TCRAs` com resumo executivo mais direto e fila operacional com melhor hierarquia
- ajustes de copy e foco visual em `Painel`, `Operações` e `TCRAs`
- correções de acentuação e limpeza de microcopy nas abas tocadas

### Pacote 4 de 8 - Concluído
Objetivo:
- Deixar o cadastro mais inteligente e mais difícil de errar

Entregas concluídas:
- validações inline acima do formulário de `Compensações`
- feedback visual por campo com severidade (`erro`, `alerta`, `informação`, `ok`)
- normalização automática de `Ofício/Processo`, `Caixa`, `Av. Tec.`, `Compensação`, `Endereço` e `Microbacia`
- comportamento consistente para `S/N` e `Arquivado`
- prevenção de duplicidade de `Av. Tec.` com orientação explícita antes de salvar
- foco automático no primeiro campo problemático ao falhar em `Adicionar` ou `Salvar`
- orientação de geocodificação no próprio formulário
- revalidação automática ao mexer em `Plantios`, `Compensado`, `S/N` e `Arquivado`

Critérios de aceite atendidos:
- menos erro silencioso no cadastro
- menos tentativa e erro para o usuário
- mensagens de correção mais autoexplicativas

### Pacote 5 de 8 - Concluído
Objetivo:
- Consolidar robustez de Supabase, cache local e conflitos

Entregas concluídas:
- mensagens de erro mais orientadas à ação em `error_service.py`
- estados remoto/local mais previsíveis no topo da janela
- rótulos e tooltips de `Sincronia`, `Escrita` e `Seleção` mais claros para produção
- textos operacionais mais úteis em `Operações` para cache, fallback e conflito
- mensagens internas da persistência autoritativa mais legíveis para suporte e diagnóstico
- redução de ambiguidade entre `Supabase`, `cache local`, `fallback local` e `rollback`

Critérios de aceite atendidos:
- conflitos detectados e comunicados de forma confiável
- estados remoto/local mais consistentes
- menos ambiguidade operacional em produção

## Próximos pacotes

### Pacote 6 de 8 - Concluído
Objetivo:
- Profissionalizar exportações e saídas institucionais

Entregas concluídas:
- cabeçalho institucional compartilhado entre relatórios
- metadados de emissão padronizados para PDF e planilha gerencial
- planilha `Resumo Gerencial` com identidade visual consistente e propriedades de documento
- PDF de compensações com sumário executivo, paginação e rodapé institucional
- PDF do painel com apresentação executiva mais limpa
- alinhamento visual da ficha individual ao mesmo padrão de ativos e identidade
- revisão de acentuação e microcopy institucional nos arquivos de exportação

Critérios de aceite atendidos:
- PDFs e planilhas com aparência institucional consistente
- menor diferença visual entre saídas de módulos distintos

### Pacote 7 de 8 - Concluído
Objetivo:
- Endurecer segurança e administração do app

Entregas concluídas:
- gestão de perfis refinada com alteração segura de papel na tela de administração
- proteção contra autoalteração de perfil e contra desativação, exclusão ou rebaixamento do último administrador ativo
- UX de administração com contexto da conta operadora, permissões por perfil e confirmações mais claras para ações sensíveis
- separação `Produção x Demonstração x Local` mais explícita no login, na janela principal e nos textos operacionais
- sinais visuais de ambiente reforçados no topo da janela, título, tooltips e chips de sessão
- backend administrativo preparado para atualização de perfil com regras de proteção alinhadas ao ambiente oficial

Critérios de aceite atendidos:
- administração mais clara e segura
- separação entre ambientes sem ambiguidades
- menor chance de erro operacional na base oficial

### Pacote 8 de 8 - Concluído
Objetivo:
- Fechar a rodada como release profissional

Entregas concluídas:
- revisão final do app inteiro com polimento visual e textual nas mensagens críticas
- estados vazios e de detalhe mais profissionais em `Painel` e `Operações`
- placeholders e mensagens de carregamento mais claros em `Compensações`
- checklist final de release criado em `docs/checklist_release_interna.md`
- handoff operacional interno criado em `docs/handoff_operacao_interna.md`
- suíte completa monolítica estabilizada e validada antes do fechamento do plano

Critérios de aceite atendidos:
- produto visualmente mais consistente
- sem mensagens improvisadas nos fluxos principais revisados
- release com handoff simples para operação interna

## Ordem recomendada
1. Plano concluído

## Modo de execução recomendado
Para cada pacote:
1. Implementar
2. Testar
3. Resumir o que foi entregue
4. Registrar o que falta
5. Informar explicitamente em qual pacote estamos

## Próximo passo oficial
Usar `docs/checklist_release_interna.md` como roteiro da próxima liberação e `docs/handoff_operacao_interna.md` como base de operação interna.
