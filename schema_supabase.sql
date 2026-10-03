-- Schema PostgreSQL para o Facilita no Supabase
-- Compatível com centavos inteiros (BIGINT) e integridade referencial

CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    login TEXT NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    tentativas_falhas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate TEXT
);

CREATE TABLE IF NOT EXISTS clientes (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    cpf TEXT,
    telefone TEXT,
    email TEXT,
    endereco TEXT,
    bairro TEXT,
    cidade TEXT,
    estado TEXT,
    cep TEXT,
    observacoes TEXT,
    ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clientes_acessos (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    usuario TEXT UNIQUE,
    email TEXT NOT NULL UNIQUE,
    telefone_informado TEXT,
    senha_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDENTE' CHECK (status IN ('PENDENTE','ATIVO','REJEITADO','BLOQUEADO')),
    contato_validado INTEGER NOT NULL DEFAULT 0 CHECK (contato_validado IN (0,1)),
    tentativas_falhas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate TEXT,
    ultimo_login_at TEXT,
    solicitado_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    aprovado_at TEXT,
    aprovado_por_usuario_id INTEGER REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE SET NULL,
    observacao_admin TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contas_bancarias (
    id SERIAL PRIMARY KEY,
    tipo_titular TEXT NOT NULL CHECK (tipo_titular IN ('NOSSA', 'CLIENTE')),
    cliente_id INTEGER REFERENCES clientes(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    banco TEXT NOT NULL,
    descricao TEXT,
    agencia TEXT,
    conta TEXT,
    tipo_conta TEXT,
    chave_pix TEXT,
    principal INTEGER NOT NULL DEFAULT 0 CHECK (principal IN (0, 1)),
    ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cartoes_credito (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    descricao TEXT NOT NULL,
    ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dia_vencimento INTEGER
);

CREATE TABLE IF NOT EXISTS lancamentos_cartao (
    id SERIAL PRIMARY KEY,
    cartao_credito_id INTEGER NOT NULL REFERENCES cartoes_credito(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    descricao TEXT NOT NULL,
    valor_total_centavos BIGINT NOT NULL CHECK (valor_total_centavos > 0),
    quantidade_parcelas INTEGER NOT NULL CHECK (quantidade_parcelas > 0),
    data_compra TEXT NOT NULL,
    usuario_id INTEGER REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parcelas_cartao (
    id SERIAL PRIMARY KEY,
    lancamento_cartao_id INTEGER NOT NULL REFERENCES lancamentos_cartao(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    numero_parcela INTEGER NOT NULL CHECK (numero_parcela > 0),
    valor_centavos BIGINT NOT NULL CHECK (valor_centavos >= 0),
    vencimento TEXT NOT NULL,
    data_pagamento TEXT,
    conta_origem_id INTEGER REFERENCES contas_bancarias(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    conta_destino_id INTEGER REFERENCES contas_bancarias(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    origem_banco_snapshot TEXT,
    origem_pix_snapshot TEXT,
    destino_banco_snapshot TEXT,
    destino_pix_snapshot TEXT,
    usuario_pagamento_id INTEGER REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE SET NULL,
    pagamento_observacao TEXT,
    status TEXT NOT NULL DEFAULT 'PENDENTE' CHECK (status IN ('PENDENTE', 'PAGO', 'VENCIDO', 'CANCELADO')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (lancamento_cartao_id, numero_parcela)
);

CREATE TABLE IF NOT EXISTS emprestimos (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    descricao TEXT,
    data_emprestimo TEXT NOT NULL,
    valor_original_centavos BIGINT NOT NULL CHECK (valor_original_centavos > 0),
    saldo_atual_centavos BIGINT NOT NULL CHECK (saldo_atual_centavos >= 0),
    taxa_juros_mensal REAL NOT NULL CHECK (taxa_juros_mensal >= 0),
    data_primeiro_vencimento TEXT,
    dia_vencimento INTEGER CHECK (dia_vencimento IS NULL OR dia_vencimento BETWEEN 1 AND 31),
    status TEXT NOT NULL DEFAULT 'ATIVO' CHECK (status IN ('ATIVO', 'QUITADO', 'VENCIDO')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pagamentos_integrados (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    data_pagamento TEXT NOT NULL,
    valor_total_centavos BIGINT NOT NULL CHECK (valor_total_centavos > 0),
    conta_origem_id INTEGER NOT NULL REFERENCES contas_bancarias(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    conta_destino_id INTEGER NOT NULL REFERENCES contas_bancarias(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    origem_banco_snapshot TEXT,
    origem_pix_snapshot TEXT,
    destino_banco_snapshot TEXT,
    destino_pix_snapshot TEXT,
    observacao TEXT,
    usuario_id INTEGER REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movimentacoes_emprestimo (
    id SERIAL PRIMARY KEY,
    emprestimo_id INTEGER NOT NULL REFERENCES emprestimos(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    tipo TEXT NOT NULL CHECK (tipo IN ('EMPRESTIMO', 'JUROS', 'ABATIMENTO', 'QUITACAO')),
    data_movimento TEXT NOT NULL,
    valor_centavos BIGINT NOT NULL CHECK (valor_centavos >= 0),
    conta_origem_id INTEGER REFERENCES contas_bancarias(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    conta_destino_id INTEGER REFERENCES contas_bancarias(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    origem_banco_snapshot TEXT,
    origem_pix_snapshot TEXT,
    destino_banco_snapshot TEXT,
    destino_pix_snapshot TEXT,
    observacao TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    competencia TEXT,
    usuario_id INTEGER REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE SET NULL,
    saldo_antes_centavos BIGINT,
    saldo_depois_centavos BIGINT,
    updated_at TEXT,
    usuario_ultima_alteracao_id INTEGER REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE SET NULL,
    pagamento_integrado_id INTEGER REFERENCES pagamentos_integrados(id) ON UPDATE CASCADE ON DELETE SET NULL,
    titulo_receber_id INTEGER,
    valor_base_centavos BIGINT,
    data_base_atraso TEXT,
    dias_atraso INTEGER NOT NULL DEFAULT 0,
    juros_atraso_centavos BIGINT NOT NULL DEFAULT 0,
    data_calculo_atraso TEXT
);

CREATE TABLE IF NOT EXISTS titulos_receber (
    id SERIAL PRIMARY KEY,
    emprestimo_id INTEGER NOT NULL REFERENCES emprestimos(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    tipo TEXT NOT NULL DEFAULT 'JUROS' CHECK (tipo IN ('JUROS')),
    competencia TEXT NOT NULL,
    data_vencimento TEXT NOT NULL,
    valor_previsto_centavos BIGINT NOT NULL CHECK (valor_previsto_centavos >= 0),
    valor_recebido_centavos BIGINT NOT NULL DEFAULT 0 CHECK (valor_recebido_centavos >= 0),
    saldo_base_centavos BIGINT NOT NULL CHECK (saldo_base_centavos >= 0),
    taxa_juros_mensal REAL NOT NULL CHECK (taxa_juros_mensal >= 0),
    status TEXT NOT NULL DEFAULT 'PREVISTO' CHECK (status IN ('PREVISTO', 'VENCIDO', 'PARCIAL', 'RECEBIDO', 'CANCELADO')),
    movimentacao_id INTEGER REFERENCES movimentacoes_emprestimo(id) ON UPDATE CASCADE ON DELETE SET NULL,
    data_recebimento TEXT,
    observacao TEXT,
    ajuste_manual INTEGER NOT NULL DEFAULT 0 CHECK (ajuste_manual IN (0, 1)),
    titulo_origem_id INTEGER REFERENCES titulos_receber(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    natureza TEXT NOT NULL DEFAULT 'JUROS' CHECK (natureza IN ('JUROS', 'SALDO_JUROS')),
    sequencia INTEGER NOT NULL DEFAULT 1 CHECK (sequencia >= 1),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valor_base_centavos BIGINT,
    data_base_atraso TEXT,
    dias_atraso INTEGER NOT NULL DEFAULT 0,
    juros_atraso_centavos BIGINT NOT NULL DEFAULT 0,
    data_calculo_atraso TEXT
);

CREATE TABLE IF NOT EXISTS pagamentos_integrados_itens (
    id SERIAL PRIMARY KEY,
    pagamento_integrado_id INTEGER NOT NULL REFERENCES pagamentos_integrados(id) ON UPDATE CASCADE ON DELETE CASCADE,
    emprestimo_id INTEGER NOT NULL REFERENCES emprestimos(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    tipo TEXT NOT NULL DEFAULT 'JUROS' CHECK (tipo IN ('JUROS')),
    competencia TEXT NOT NULL,
    valor_centavos BIGINT NOT NULL CHECK (valor_centavos > 0),
    saldo_base_centavos BIGINT NOT NULL CHECK (saldo_base_centavos >= 0),
    movimentacao_id INTEGER NOT NULL UNIQUE REFERENCES movimentacoes_emprestimo(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    titulo_receber_id INTEGER,
    origem_item TEXT NOT NULL DEFAULT 'MANUAL',
    valor_base_centavos BIGINT,
    data_base_atraso TEXT,
    dias_atraso INTEGER NOT NULL DEFAULT 0,
    juros_atraso_centavos BIGINT NOT NULL DEFAULT 0,
    data_calculo_atraso TEXT,
    UNIQUE (pagamento_integrado_id, emprestimo_id, competencia)
);

CREATE TABLE IF NOT EXISTS comprovantes_pagamento (
    id SERIAL PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    cliente_acesso_id INTEGER NOT NULL REFERENCES clientes_acessos(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    data_pagamento TEXT NOT NULL,
    valor_total_centavos BIGINT NOT NULL CHECK (valor_total_centavos > 0),
    arquivo_nome TEXT NOT NULL,
    arquivo_original TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    tamanho_bytes BIGINT NOT NULL CHECK (tamanho_bytes > 0),
    status TEXT NOT NULL DEFAULT 'EM_ANALISE' CHECK (status IN ('EM_ANALISE','CONFIRMADO','REJEITADO')),
    observacao_cliente TEXT,
    observacao_admin TEXT,
    pagamento_integrado_id INTEGER REFERENCES pagamentos_integrados(id) ON UPDATE CASCADE ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    analisado_at TEXT,
    analisado_por_usuario_id INTEGER REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS comprovantes_pagamento_itens (
    id SERIAL PRIMARY KEY,
    comprovante_id INTEGER NOT NULL REFERENCES comprovantes_pagamento(id) ON UPDATE CASCADE ON DELETE CASCADE,
    titulo_receber_id INTEGER NOT NULL REFERENCES titulos_receber(id) ON UPDATE CASCADE ON DELETE RESTRICT,
    valor_centavos BIGINT NOT NULL CHECK (valor_centavos > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    valor_base_centavos BIGINT,
    data_base_atraso TEXT,
    dias_atraso INTEGER NOT NULL DEFAULT 0,
    juros_atraso_centavos BIGINT NOT NULL DEFAULT 0,
    data_calculo_atraso TEXT,
    UNIQUE (comprovante_id, titulo_receber_id)
);

CREATE TABLE IF NOT EXISTS auditoria (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE SET NULL,
    entidade TEXT NOT NULL,
    entidade_id INTEGER,
    acao TEXT NOT NULL,
    detalhes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS limites_publicos (
    chave TEXT PRIMARY KEY,
    inicio BIGINT NOT NULL,
    tentativas INTEGER NOT NULL
);
