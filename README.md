# Facilita — Sistema de Gestão Financeira

Versão **2.5.0**, mantida na branch **main**.
Sistema de uso em produção para gestão financeira discreta, contratos/operações, recebimentos e cartões de crédito, com interface administrativa completa e portal de autoatendimento para o cliente. Não inclui dados demonstrativos nem usuário ou senha padrão.

## Funcionalidades

- **Contratos e Operações**: Aportes, juros mensais, amortizações e liquidações com valores estritamente em centavos inteiros (`BIGINT`).
- **Atraso Proporcional**: Juro mensal original × dias de atraso ÷ 30, sem capitalização indevida de juros em títulos futuros.
- **Recebimentos e Reagendamento**: Agrupamento flexível de cobranças com prévia de cálculos e opções de liquidação.
- **Portal do Cliente**: Acesso seguro para visualização de extratos, comprovantes e dados cadastrais, com solicitação de acesso e foto de perfil.
- **Login Unificado**: Seletor intuitivo entre Área do Cliente e Acesso Administrativo com recuperação de acesso.
- **Modo Privacidade**: Ocultação rápida de valores monetários na tela para uso discreto em locais públicos.
- **Auditoria e Segurança**: Registro completo de operações sensíveis com confirmação de senha, senhas em hash Scrypt, CSRF e cookies seguros.

## Arquitetura na Nuvem (Produção)

O **Facilita** opera 100% diretamente na nuvem (sem necessidade de instalação local):

- **Hospedagem Web Serverless**: [Vercel](https://vercel.com) com CDN global, rewrites serverless (`api/index.py`) e SSL/HTTPS automático.
- **Banco de Dados Produção**: [Supabase](https://supabase.com) (PostgreSQL 17 gerenciado no datacenter de São Paulo - `sa-east-1`).
- **Acesso Mobile (PWA)**: Pode ser adicionado como aplicativo à tela inicial de celulares (iOS Safari ou Android Chrome).

Para detalhes de variáveis de ambiente, domínios e backups, consulte o [Guia da Nuvem Vercel + Supabase](docs/NUVEM_VERCEL_SUPABASE.md).

## Desenvolvimento e Testes

Stack: Python 3.12+, Flask, PostgreSQL/SQLite, Jinja2, HTML5/CSS3 moderno.

```sh
python -m pip install -r requirements.lock
python -m unittest discover -s tests -v
python teste_local.py
```

O servidor local de testes roda isoladamente na porta 5001 com banco em `data/local-test`.

## Documentação

- [Changelog](CHANGELOG.md)
- [Nuvem Vercel + Supabase](docs/NUVEM_VERCEL_SUPABASE.md)
- [Arquitetura](docs/ARCHITECTURE.md)
- [Regras financeiras](docs/BUSINESS_RULES.md)
- [Espaço e manutenção](docs/RECURSOS_E_MANUTENCAO.md)
- [Testes locais](docs/TESTE_LOCAL.md)
