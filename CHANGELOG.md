# Changelog

## 2.4.5 — 2026-10-05

- **Ajustes e Otimização Visual do Extrato do Cliente**:
  - Remoção dos totalizadores duplicados abaixo do filtro e da tabela de detalhamento dos contratos na tela de extrato do cliente, mantendo o foco exclusivo em Títulos e Movimentações históricas.
- **Painel "Minha Visão Geral" do Cliente**:
  - Remoção do card redundante de "Valor Líquido dos Contratos", mantendo a grade limpa com os 4 indicadores essenciais: Total dos Contratos, Ativos com Saldo Restante, Total Amortizado e Quitados/Inativos.
- **Ordenação Inteligente de Compras e Parcelas dos Cartões de Crédito**:
  - Nova regra de ordenação nas parcelas de cartões de crédito do cliente: compras com parcelas ativas (em aberto ou vencidas) priorizadas no topo da lista.
  - Compras 100% quitadas/pagas agrupadas e posicionadas automaticamente no final da listagem.
  - Parcelas agrupadas por compra e ordenadas da primeira à última parcela por vencimento e número de parcela.
  - Reorganização da tabela de parcelas com a coluna "Compra" na primeira posição para leitura imediata.
- **Suíte de Testes Automatizados**: ampliação para 198 testes unitários automatizados com 100% de sucesso.

## 2.4.4 — 2026-10-05

- **Compatibilidade PostgreSQL (Supabase) vs SQLite em Cálculos de Contratos**:
  - Correção crítica da consulta SQL de amortizações e contratos: substituição do uso de função escalar não suportada no PostgreSQL (`MAX(col1, col2)`) por sintaxe ANSI SQL universal `CASE WHEN col1 >= col2 THEN col1 ELSE col2 END`.
  - Eliminação do erro `500 Internal Server Error` (`psycopg2.errors.UndefinedFunction: function max(bigint, bigint) does not exist`) no painel do cliente no Supabase em produção.
- **Isolamento Estrito de Sessão e Eliminação do Loop de Login**:
  - Limpeza total de resíduos de sessão administrativa ao autenticar no portal do cliente e vice-versa.
  - Correção na rota `/login` (área administrativa): clientes logados agora são redirecionados automaticamente para `/portal` em vez de ficarem presos na tela com formulário inoperante.
  - Ocultação definitiva de elementos de navegação/sidebar em telas de autenticação (`/login`, `/portal/login`, etc.), impedindo vazamento de menus administrativos para clientes.
- **Resiliência de Logout e Tela de Erro 500 Contextual**:
  - Rotas de logout (`/logout` e `/portal/logout`) tornadas tolerantes a requisições `GET` e `POST` diretas sem bloqueio por `@login_required`, garantindo que qualquer usuário consiga deslogar instantaneamente mesmo em estado de sessão anômalo.
  - Tela de erro 500 (`Erro interno ao carregar a página`) aprimorada para ser contextual: detecta se a requisição originou-se do portal do cliente ou do painel administrativo, oferecendo links de retorno adequados (`/portal` vs `/dashboard`) e botão de encerramento de sessão imediato para não prender o usuário.
- **Suíte de Testes Automatizados**: ampliação para 197 testes unitários automatizados com 100% de sucesso.

## 2.4.3 — 2026-10-05

- **Painel "Minha Visão Geral" & Somatório de Contratos**:
  - Somatório total de contratos realizados (quantidade e valor total).
  - Indicadores destacados de contratos ativos (quantidade e saldo restante) e quitados/inativos.
  - Somatório total amortizado e cálculo do **valor líquido** dos contratos (deduzindo do total contratado os valores amortizados dos quitados e inativos).
  - Tabela "Meus contratos" exibindo a data em que o contrato foi realizado e o recurso transferido ao cliente (`data_emprestimo`), valor original acordado, total amortizado de cada contrato, saldo restante e situação com badges de status.
- **Filtro Inteligente de "Próximos Pagamentos"**:
  - Exibição focada nas pendências prioritárias: títulos vencidos/atrasados e pagamentos pendentes do mês vigente.
  - Alerta/botão convidativo "Ver mais no extrato" contabilizando os pagamentos dos próximos meses e direcionando o cliente diretamente para o extrato completo.
- **Correção e Leitura de Cartões de Crédito no Portal do Cliente**:
  - Correção na consulta de resumo de cartões (`card_summaries`): valores de `pago_centavos`, `aberto_centavos` e `total_parcelado_centavos` devidamente calculados e sincronizados, corrigindo a exibição de dados zerados.
  - Nova tabela "O que foi comprado", exibindo compras no cartão, datas, quantidade de parcelas, parcelas pagas/abertas e valor total.
  - Nova tabela de parcelas (abertas e pagas) com datas de vencimento, pagamentos e situações.
  - Nova rota dedicada em modo de apenas leitura (`/portal/cartoes/<id>`), permitindo consultar detalhes individuais do cartão sem permitir alterações externas.
- **Detalhamento de Contratos no Extrato do Cliente**:
  - Nova seção "Detalhamento dos Contratos" no extrato financeiro, informando contrato, data de contratação/transferência, valor acordado, total amortizado e saldo restante com rodapé somatório.
  - Somatórios dos valores pagos ao Facilita tanto no período quanto no acumulado histórico (distinguindo amortizações de capital e taxas de compensação).
- **Cadastro do Cliente (Visão Administrativa)**:
  - Tabela de operações e contratos no cadastro do cliente enriquecida com a data de contratação e total amortizado.
- **Suíte de Testes Automatizados**: ampliação para 194 testes unitários automatizados com 100% de sucesso.

## 2.4.2 — 2026-10-05

- **Visualização de Comprovantes em Modal Pop-up (sem erro 404)**:
  - Substituição da navegação de página pelo novo modal pop-up moderno, exibido sobre a tela ao clicar em "Abrir" nos comprovantes do portal.
  - Exibição inline de metadados, valores formatados, badges de situação, observação do cliente e resposta do administrador.
  - Fallback resiliente com armazenamento em Base64: em servidores serverless (Vercel) onde arquivos locais são efêmeros, o arquivo é recuperado do banco e servido instantaneamente em memória.
  - Tratamento suave caso o anexo físico não esteja disponível no servidor: mensagem amigável no próprio modal alertando que o arquivo não foi localizado, sem quebrar a tela nem exibir o erro 404.
- **Identificação Visual por Cores e Sinais (+ / -) no Extrato do Cliente**:
  - Diferenciação visual clara do fluxo financeiro:
    - **Aportes / Disponibilizações**: destacados com sinal positivo `+` em verde e badge explicativo `+ Recebido pelo cliente`.
    - **Taxa de Serviço, Amortizações e Liquidações**: destacados com sinal negativo `-` em vermelho e badge explicativo `- Pago ao Facilita`.
  - Novos cards de balanço do período no topo do extrato: *Total Recebido (Aportes)*, *Total Pago ao Facilita* e *Títulos em Aberto*, com suporte completo ao Modo Privacidade.
- **Foto de Perfil do Cliente com Limite de 1024 KB e Corte Inteligente**:
  - Nova funcionalidade na tela `/portal/perfil` permitindo ao cliente enviar, alterar ou remover sua foto de perfil.
  - Limite estrito de arquivo de **1024 KB (1 MB)** e validação de formatos (PNG, JPG, WEBP).
  - Algoritmo de corte quadrado centralizado 1:1 e redimensionamento proporcional (160x160 px com compactação otimizada ~15 KB), aceitando fotos de qualquer resolução (incluindo 4K) sem ocupar espaço excessivo no servidor.
  - Miniatura circular (32x32 px) exibida diretamente ao lado do nome do cliente na barra de perfil do menu retrátil e suspenso.
- **Validação Inteligente e Anti-Desperdício de Comprovantes**:
  - Limite reduzido para PDFs de comprovante (até 2 MB) e verificação de integridade mínima.
  - Resolução mínima de 180x180 pixels para fotos e capturas de comprovantes.
  - Detecção com Pillow de imagens sem contraste/informação (desvio padrão de cinza < 8.0), descartando imagens monocromáticas, telas em branco, pretas ou vazias para evitar envios desnecessários.
- **Cobertura de Testes**: inclusão de `tests/test_portal_novidades.py` elevando a suíte para 191 testes automatizados com 100% de aprovação.

## 2.4.1 — 2026-10-05

- **Recuperação de Senha do Portal do Cliente**: nova tela `/portal/recuperar-senha` oferecendo duas opções claras para quando o cliente perde o acesso:
  1. *Recuperação por E-mail (Automática)*: envio de link temporário exclusivo e criptografado com validade de 60 minutos e layout responsivo.
  2. *Contato direto com o Administrador*: orientações e botão direto via WhatsApp (`WHATSAPP_SUPORTE`) para assistência humana imediata.
- **Redefinição Segura via Token**: nova rota `/portal/redefinir-senha` validando prazo de expiração e consumo do token, com auditoria completa de alteração.
- **Geração de Link pelo Administrador**: novo botão em `Acessos ao Portal` permitindo ao administrador gerar instantaneamente um link seguro com validade de 24 horas para enviar ao cliente pelo WhatsApp ou e-mail.
- **Controle Preciso de Bloqueio Temporário**: a mensagem de bloqueio por tentativas excessivas agora é exibida **somente quando a conta está efetivamente bloqueada**, calculando e informando com exatidão o tempo restante de espera (ex: *15 minutos*, *14 minutos*, *45 segundos*). Falhas convencionais de login exibem mensagem limpa sem falsos alertas de bloqueio.
- **Módulo Transacional `email_utils.py`**: suporte completo a servidores SMTP (Gmail, SES, SendGrid, Mailgun) configuráveis via variáveis de ambiente com fallback resiliente.
- **Suíte de Testes Automatizados**: inclusão de `tests/test_recuperacao_senha.py` elevando a cobertura para 182 testes validados com 100% de sucesso.

## 2.4.0 — 2026-10-05

- Mini Sidebar colapsada com Hover Suspenso (estilo Beatrix): quando recolhida, a barra lateral passa a exibir um trilho compacto de 68px com ícones centralizados; ao passar o mouse, expande suavemente como um menu suspenso flutuante sobre a página sem deslocar o conteúdo.
- Botão de controle unificado: remoção do botão duplicado do cabeçalho da sidebar, mantendo o botão hambúrguer limpo e integrado na barra superior (topbar).
- Ícones em todos os itens do menu: 12 novos ícones SVG vetoriais adicionados à navegação administrativa e do portal do cliente.
- Agrupamento lógico de menus: itens organizados em seções estruturadas (`Principal`, `Operações & Finanças` e `Gestão & Segurança`).
- Simplificação definitiva de versionamento: remoção de metadados de build, adotando versão semântica direta (`v2.4.0`).

## 2.3.0 — 2026-10-05

- Novo gerenciamento de perfil: páginas dedicadas e seguras `/perfil` (Administrador) e `/portal/perfil` (Cliente), permitindo edição de dados cadastrais e alteração de senha de acesso com confirmação da senha atual.
- Barra lateral retrátil (Sidebar): inclusão de botão hambúrguer no menu e na barra superior permitindo recolher ou expandir a navegação com persistência em `localStorage`.
- Topbar minimalista: alternador de tema e botão de privacidade operando exclusivamente com ícones visuais modernos e acessíveis.
- Rodapé da sidebar refinado: substituição de link de texto por botão estilizado de Desconexão e ícone de engrenagem para acesso direto ao perfil do usuário/cliente.
- Auditoria com filtros em linha única: botões de ação substituídos por ícones (lupa para filtrar e pincel para limpar filtros).
- Rodapé de auditoria unificado na mesma linha: seletor compacto de quantidade de registros por página posicionado junto à paginação e indicador de total de itens.

## 2.2.1+build.1 — 2026-10-05

- Padronização estrita de data e hora no fuso horário oficial de Fortaleza/CE/Brasil (`America/Fortaleza`, UTC-3) em toda a aplicação.
- Correção de exibição na Auditoria: timestamps em UTC do banco agora são convertidos dinamicamente e com precisão para o horário local.
- Proteção financeira contra cobrança indevida: `hoje_brasil()` substitui `date.today()` do servidor, impedindo que títulos vençam antes da meia-noite local e evitando juros de atraso calculados prematuramente.
- Sincronização do fuso horário nas conexões PostgreSQL (`SET TIME ZONE 'America/Fortaleza'`).
- Novo módulo central `timezone_utils.py` com cobertura completa de testes unitários.

## 2.2.0+build.1 — 2026-10-05

- Transição completa para a identidade visual Facilita e redesign moderno (paleta inspirada em Conta Azul e Asaas com temas Claro e Escuro refinados).
- Página de Auditoria com filtros avançados: período (data inicial e final), tipo de ação, responsável, módulo/origem e pesquisa textual em tempo real.
- Paginação dinâmica na Auditoria com seletor de limite por página (20, 25, 40, 50, 60, 100, 200 itens) e navegação completa entre páginas.
- Humanização detalhada dos registros de auditoria em linguagem natural e amigável.
- Recursos avançados de compensação: abono integral, recálculo e desconto proporcional em recebimentos.
- Deploy em produção 24/7 na Vercel Serverless com PostgreSQL Supabase e segurança multicamadas.

## 2.1.1+build.3 — 2026-09-20

- Caminho padrão macOS corrigido para ~/Applications.
- Migração confirmada do caminho antigo, com backup, proteção de instalações
  existentes e recriação do ambiente Python/LaunchAgent. Dados permanecem no lugar.


## 2.1.0+build.2 — 2026-09-20

- Gerenciador macOS: instalação, consulta de atualização, ativação confirmada,
  backup e importação inicial de base v1 com validação em cópia.
- Código por release, dados persistentes separados e execução com LaunchAgent.
- Runner Waitress com rotação de logs e versão discreta no rodapé.
- Testes de cópia SQLite/WAL, bloqueio de sobrescrita e cancelamento da ativação.
- Validação contínua também em macOS. Regras financeiras e schema preservados.


## Documentação multiplataforma — 2026-09-19

- Guias de instalação, execução automática, atualização e diagnóstico para
  Windows, macOS e Linux na branch release/v2.
- Nenhuma alteração de versão da aplicação, regra financeira ou esquema.

## 2.0.0+build.1 — 2026-09-19

- Publicação da versão 2 na branch release/v2, sem dados demonstrativos.
- Interface administrativa e portal do cliente completos.
- Juros de atraso proporcionais, prévia de reagendamento e recebimentos agrupados.
- Transações atômicas, proteções financeiras e migrações incrementais.
- Sincronização da agenda em lote e sem regravação de previsões inalteradas.
- Dependências de produção fixadas e gerenciador Windows direcionado à v2.
- Testes de restauração independentes de backups privados.


## 2026-09-02 — Arquitetura Python/SQLite

- substituição da arquitetura Next.js/NestJS/PostgreSQL/Docker por Flask + SQLite;
- autenticação local;
- clientes;
- empréstimos independentes;
- juros integrais por competência;
- abatimentos múltiplos;
- quitação;
- movimentações e auditoria básica;
- contas bancárias e chaves PIX com snapshots históricos;
- cartões, lançamentos parcelados e pagamentos;
- dashboard financeiro;
- documentação para agentes de IA;
- gerenciador Windows para instalação, atualização e desinstalação;
- Waitress + WinSW para execução como serviço `Emprestimo`.
