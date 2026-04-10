# Checklist de Release Interna

## Objetivo
Validar a liberação da `Plataforma de Gestão Ambiental` para uso interno com o menor risco operacional possível.

## 1. Base e autenticação
- Confirmar que o projeto Supabase correto está configurado para Produção.
- Validar login com uma conta `admin` ativa.
- Validar login com uma conta `editor`.
- Validar que `Leitor` não enxerga a aba `Administração`.
- Confirmar que `Demonstração` continua isolada e sem impacto na base oficial.

## 2. Administração de usuários
- Criar um novo usuário pela aba `Administração`.
- Reativar um usuário inativo.
- Desativar um usuário comum.
- Redefinir senha de um usuário comum.
- Confirmar que não é possível:
  - desativar a própria conta
  - excluir a própria conta
  - alterar o perfil da própria conta
  - desativar, excluir ou rebaixar o último administrador ativo

## 3. Compensações
- Abrir a base oficial e confirmar leitura do recorte.
- Criar um cadastro novo.
- Editar um cadastro existente.
- Excluir um cadastro existente.
- Validar prevenção de duplicidade de `Av. Tec.`.
- Validar exportação de ficha PDF.
- Validar exportação do resumo gerencial.

## 4. TCRAs
- Abrir a aba `TCRAs` e validar leitura do cache sincronizado.
- Criar ou editar um termo.
- Registrar um evento.
- Validar `Inbox`, `Qualidade` e atualização da agenda.
- Validar exportação PDF/Excel do módulo.

## 5. Painel e Operações
- Abrir `Painel > Compensações`.
- Abrir `Painel > TCRAs`.
- Confirmar carregamento dos gráficos.
- Validar `Operações` com histórico, detalhe e status de sincronia.
- Exportar diagnóstico técnico.

## 6. Estados e UX
- Revisar visual em `1440x900`.
- Confirmar que não há sobreposição grave de controles.
- Confirmar que o topo diferencia claramente:
  - `Produção oficial`
  - `Demonstração isolada`
  - `Contingência local`
- Revisar estados vazios e mensagens principais.

## 7. Validação técnica
- Rodar a suíte completa:
  - `python -m pytest -q`
- Confirmar resultado verde antes da publicação.

## 8. Publicação
- Revisar `git status`.
- Fazer commit com resumo claro.
- Publicar no repositório remoto.
- Registrar a versão liberada e a data da publicação.
