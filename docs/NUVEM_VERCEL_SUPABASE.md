# Guia de Operação e Arquitetura — Facilita na Nuvem

## 1. Visão Geral da Arquitetura

O **Facilita** opera em uma arquitetura serverless moderna, 100% gratuita e de alta disponibilidade:

* **Hospedagem Web**: [Vercel](https://vercel.com) com SSL automático e CDN global.
* **Banco de Dados**: [Supabase](https://supabase.com) (PostgreSQL 17 gerenciado no datacenter de São Paulo, `sa-east-1`).
* **Segurança**: Senhas criptografadas em hash Werkzeug/Scrypt, cookies `HttpOnly`, `SameSite=Lax` e `Secure`, tokens CSRF automáticos em todos os formulários POST.
* **Integridade Monetária**: Valores estritamente armazenados em inteiros centavos (`BIGINT`), sem perda de precisão flutuante.

---

## 2. Domínios Oficiais

* Principal: `https://facilitando.vercel.app`
* Alternativo: `https://facilita-br.vercel.app`
* Time: `https://facilita-mini-pdv.vercel.app`

---

## 3. Variáveis de Ambiente na Vercel

Configuradas em `Settings > Environment Variables`:

| Variável | Finalidade |
| :--- | :--- |
| `DATABASE_URL` | String de conexão PostgreSQL do Supabase (Pooler porta 6543) |
| `SECRET_KEY` | Chave de assinatura criptográfica de sessões Flask |
| `EMPRESTIMO_HTTPS` | Habilita regras restritas de SSL e cookies seguros |
| `EMPRESTIMO_BEHIND_PROXY` | Configura suporte ao reverse proxy da Vercel |

---

## 4. Backups do Banco de Dados

Seus dados estão protegidos no Supabase:
1. **Backups Diários Automáticos**: O Supabase realiza snapshots diários da base de dados.
2. **Exportação Manual via SQL**:
   No painel do Supabase (`SQL Editor`), você pode exportar qualquer tabela ou rodar consultas analíticas diretamente.
3. **Cópia Local de Segurança**:
   Se desejar baixar os dados da nuvem para o SQLite local, use o script:
   ```bash
   python scripts/migrar_sqlite_supabase.py
   ```

---

## 5. Como Usar como Aplicativo no Celular (PWA)

O Facilita já vem com suporte completo para ser adicionado como atalho nativo na tela do seu celular:

### No iPhone (iOS):
1. Abra `https://facilitando.vercel.app` no **Safari**.
2. Toque no ícone de **Compartilhar** (quadrado com seta para cima no rodapé).
3. Selecione **"Adicionar à Tela de Início"**.
4. O ícone **Facilita** aparecerá na tela do seu iPhone como um app independente!

### No Android:
1. Abra `https://facilitando.vercel.app` no **Google Chrome**.
2. Toque nos três pontinhos no canto superior direito.
3. Selecione **"Instalar aplicativo"** ou **"Adicionar à tela inicial"**.
