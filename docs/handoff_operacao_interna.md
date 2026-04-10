# Handoff de Operação Interna

## Produto
`Plataforma de Gestão Ambiental`

## Ambientes
### Produção oficial
- Usa autenticação corporativa.
- Lê e grava na base oficial via Supabase.
- Mantém cache local sincronizado para leitura operacional.

### Demonstração isolada
- Serve para treinamento e validação visual.
- Não deve ser usada para operação real.
- Não impacta a base oficial.

### Contingência local
- Serve para suporte, contingência e uso offline.
- Não substitui a operação oficial em Produção.

## Perfis
### Administrador
- Gerencia usuários.
- Redefine senhas.
- Ativa e desativa contas.
- Ajusta perfis.

### Editor
- Opera os módulos e atualiza dados.
- Não gerencia usuários.

### Leitor
- Consulta dados e relatórios.
- Não altera registros.

## Rotina recomendada
1. Entrar sempre em `Produção oficial` para operação real.
2. Conferir no topo:
   - conta ativa
   - perfil
   - ambiente
3. Validar o recorte no módulo antes de salvar alterações.
4. Usar `Operações` quando houver dúvida sobre cache, escrita, fallback ou restauração.

## Recuperação de acesso
- O próprio usuário pode iniciar `Esqueci minha senha`.
- Um `Administrador` também pode redefinir uma senha provisória pela aba `Administração`.

## Cuidados operacionais
- Não usar `Demonstração` como se fosse Produção.
- Não usar `Contingência local` como fonte oficial sem alinhamento interno.
- Não remover nem rebaixar o último administrador ativo.
- Sempre confirmar a conta ativa antes de alterações sensíveis.

## Verificações rápidas de suporte
- Login funcionando
- Sincronia visível no topo
- Painel carregando gráficos
- Operações mostrando histórico
- Compensações e TCRAs abrindo sem erro
- Exportações PDF/Excel funcionando

## Referência final
Antes de qualquer liberação, seguir:
- [checklist_release_interna.md](C:\Users\david\Desktop\Pen%20Drive\Compensacoes_app\docs\checklist_release_interna.md)
