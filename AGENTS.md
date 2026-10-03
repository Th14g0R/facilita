# AGENTS.md — Contexto obrigatório para IAs (Facilita)

## Objetivo

Este repositório implementa o **Facilita**, um sistema web discreto e seguro de controle financeiro, acordos, operações e cartões de crédito. A prioridade do projeto é **simplicidade operacional**, **integridade financeira centavo por centavo**, **discrição perante terceiros** e **alta disponibilidade na nuvem**.

## Stack e Arquitetura

- **Backend**: Python 3.12+ / Flask / WSGI
- **Frontend**: Jinja2 / HTML5 / CSS Moderno (Vanilla CSS com Design Tokens e Modo Privacidade)
- **Nuvem (Produção 24/7)**: Vercel Serverless (`api/index.py`, `vercel.json` com rewrites)
- **Banco de Dados Produção**: Supabase PostgreSQL 17 (Datacenter São Paulo - `sa-east-1`)
- **Banco de Dados Desenvolvimento/Testes**: Suporte híbrido transparente para SQLite (`data/emprestimos.db`) e PostgreSQL via `DATABASE_URL`

Não introduzir Node.js, npm, Docker, Next.js, Prisma ou frontend SPA separado sem solicitação explícita.

## Regras Financeiras Obrigatórias

1. **Valores Monetários**: Sempre armazenados em **centavos inteiros** (`INTEGER` / `BIGINT`). Nunca usar `float` para valores financeiros.
2. Cada operação pertence a um cliente e é independente das demais operações do mesmo cliente.
3. Todo movimento financeiro pertence obrigatoriamente a um `emprestimo_id`.
4. `EMPRESTIMO` (Aporte) cria o valor original e o saldo inicial da operação.
5. `JUROS` (Taxa de Serviço) é integral por competência mensal e não reduz nem aumenta o saldo principal.
6. Não pode existir mais de um lançamento `JUROS` para a mesma competência e operação.
7. `ABATIMENTO` (Amortização) pode ocorrer várias vezes no mesmo mês e reduz apenas o saldo principal da operação selecionada.
8. `QUITACAO` (Liquidação) deve corresponder ao saldo principal restante, zerar o saldo e marcar a operação como quitada.
9. Uma operação permanece ativa enquanto possuir saldo principal maior que zero.
10. Edição/correção de valor financeiro já lançado exige confirmação de senha do usuário logado e registro em auditoria.

## Vocabulário Discreto e Apresentação (Facilita)

Para preservar a privacidade do usuário em locais públicos e proteger os clientes no portal:
- **Operações / Contratos**: substitui "Empréstimos"
- **Taxa de Serviço / Compensação**: substitui "Juros"
- **Aporte / Disponibilização**: substitui "Empréstimo inicial"
- **Amortização**: substitui "Abatimento"
- **Liquidação**: substitui "Quitação"
- **Modo Privacidade**: oculta valores na tela mediante clique no botão de olho ou persistido em `localStorage`.

## Idioma e Comunicação

- Responda e comunique-se sempre em **Português do Brasil (pt-BR)**.
- Todos os comentários no código-fonte, docstrings e explicações técnicas devem ser escritos obrigatoriamente em **Português do Brasil (pt-BR)**.
- Metadados de ferramentas (`toolAction`, `toolSummary`, `Description`) devem ser redigidos exclusivamente em **Português do Brasil (pt-BR)**.
