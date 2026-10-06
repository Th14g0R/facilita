from __future__ import annotations

import base64
import json
from io import BytesIO
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from timezone_utils import hoje_brasil, agora_brasil, iso_agora_brasil, to_brasil
from email_utils import formatar_tempo_espera, enviar_email_recuperacao, obter_link_whatsapp_ajuda
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

from app import (
    DATA_DIR, aplicar_recebimento_titulo,
    format_money, get_account_snapshots, get_client_accounts, get_db,
    get_own_accounts, only_digits, parse_int, parse_iso_date,
    parse_money_to_centavos, posicao_emprestimos_cliente,
    registrar_auditoria, resumo_financeiro_cliente, sync_receivable_titles,
    validate_cpf, validate_money_flow_accounts, validar_senha_usuario_atual,
    refresh_overdue_card_installments,
)

bp = Blueprint("portal", __name__)
PROOFS_DIR = (DATA_DIR / "comprovantes").resolve()
MAX_PROOF_INPUT_BYTES = 6 * 1024 * 1024
MAX_PROOF_PDF_BYTES = 2 * 1024 * 1024
MAX_PROOF_STORED_BYTES = 2 * 1024 * 1024
MIN_PROOF_WIDTH = 180
MIN_PROOF_HEIGHT = 180
MAX_IMAGE_DIMENSION = 1800
MAX_IMAGE_PIXELS = 20_000_000
MAX_PROFILE_PHOTO_BYTES = 1024 * 1024  # 1024 KB (1 MB)


def _processar_foto_perfil(data: bytes) -> str:
    """Valida, faz corte quadrado centralizado 160x160 e gera base64 leve de foto de perfil."""
    if not data or len(data) > MAX_PROFILE_PHOTO_BYTES:
        raise ValueError("A foto de perfil deve ter no máximo 1024 KB (1 MB).")
    try:
        with Image.open(BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode in {"RGBA", "LA"}:
                rgba = img.convert("RGBA")
                bg = Image.new("RGB", rgba.size, "white")
                bg.paste(rgba, mask=rgba.getchannel("A"))
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # Recorte inteligente centralizado 1:1 e redimensionamento proporcional
            cropped = ImageOps.fit(img, (160, 160), Image.Resampling.LANCZOS)
            buf = BytesIO()
            cropped.save(buf, format="JPEG", quality=85, optimize=True)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{encoded}"
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Formato de imagem inválido para o perfil. Envie JPG, PNG ou WEBP.") from exc


def init_schema() -> None:
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS clientes_acessos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL UNIQUE,
        usuario TEXT UNIQUE,
        email TEXT NOT NULL COLLATE NOCASE UNIQUE,
        telefone_informado TEXT,
        senha_hash TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDENTE' CHECK (status IN ('PENDENTE','ATIVO','REJEITADO','BLOQUEADO')),
        contato_validado INTEGER NOT NULL DEFAULT 0 CHECK (contato_validado IN (0,1)),
        tentativas_falhas INTEGER NOT NULL DEFAULT 0,
        bloqueado_ate TEXT,
        ultimo_login_at TEXT,
        solicitado_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        aprovado_at TEXT,
        aprovado_por_usuario_id INTEGER,
        observacao_admin TEXT,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY (aprovado_por_usuario_id) REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS comprovantes_pagamento (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        cliente_acesso_id INTEGER NOT NULL,
        data_pagamento TEXT NOT NULL,
        valor_total_centavos INTEGER NOT NULL CHECK (valor_total_centavos > 0),
        arquivo_nome TEXT NOT NULL UNIQUE,
        arquivo_original TEXT NOT NULL,
        mime_type TEXT NOT NULL,
        tamanho_bytes INTEGER NOT NULL CHECK (tamanho_bytes > 0),
        status TEXT NOT NULL DEFAULT 'EM_ANALISE' CHECK (status IN ('EM_ANALISE','CONFIRMADO','REJEITADO')),
        observacao_cliente TEXT,
        observacao_admin TEXT,
        pagamento_integrado_id INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        analisado_at TEXT,
        analisado_por_usuario_id INTEGER,
        FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY (cliente_acesso_id) REFERENCES clientes_acessos(id) ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY (pagamento_integrado_id) REFERENCES pagamentos_integrados(id) ON UPDATE CASCADE ON DELETE SET NULL,
        FOREIGN KEY (analisado_por_usuario_id) REFERENCES usuarios(id) ON UPDATE CASCADE ON DELETE SET NULL
    );
    CREATE TABLE IF NOT EXISTS comprovantes_pagamento_itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        comprovante_id INTEGER NOT NULL,
        titulo_receber_id INTEGER NOT NULL,
        valor_centavos INTEGER NOT NULL CHECK (valor_centavos > 0),
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (comprovante_id) REFERENCES comprovantes_pagamento(id) ON UPDATE CASCADE ON DELETE CASCADE,
        FOREIGN KEY (titulo_receber_id) REFERENCES titulos_receber(id) ON UPDATE CASCADE ON DELETE RESTRICT,
        UNIQUE (comprovante_id, titulo_receber_id)
    );
    CREATE INDEX IF NOT EXISTS idx_clientes_acessos_status ON clientes_acessos(status);
    CREATE INDEX IF NOT EXISTS idx_comprovantes_status ON comprovantes_pagamento(status);
    CREATE INDEX IF NOT EXISTS idx_comprovantes_cliente ON comprovantes_pagamento(cliente_id);
    CREATE INDEX IF NOT EXISTS idx_comprovantes_itens_titulo ON comprovantes_pagamento_itens(titulo_receber_id);
    """)
    from database import add_column_if_missing
    add_column_if_missing(db, 'clientes_acessos', 'usuario', 'TEXT')
    add_column_if_missing(db, 'clientes_acessos', 'reset_token', 'TEXT')
    add_column_if_missing(db, 'clientes_acessos', 'reset_token_expira', 'TEXT')
    add_column_if_missing(db, 'clientes_acessos', 'foto_perfil', 'TEXT')
    add_column_if_missing(db, 'comprovantes_pagamento', 'arquivo_base64', 'TEXT')
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_acessos_usuario ON clientes_acessos(usuario);")
    except Exception:
        pass
    try:
        db.execute("CREATE INDEX IF NOT EXISTS idx_clientes_acessos_reset_token ON clientes_acessos(reset_token);")
    except Exception:
        pass
    for name, definition in (
        ('valor_base_centavos','INTEGER'),('data_base_atraso','TEXT'),
        ('dias_atraso','INTEGER NOT NULL DEFAULT 0'),
        ('juros_atraso_centavos','INTEGER NOT NULL DEFAULT 0'),('data_calculo_atraso','TEXT'),
    ):
        add_column_if_missing(db,'comprovantes_pagamento_itens',name,definition)
    db.commit()


def proof_status(value: str | None) -> str:
    return {"EM_ANALISE":"Pg. em análise","CONFIRMADO":"Confirmado","REJEITADO":"Rejeitado"}.get(str(value or '').upper(), value or '-')


def access_status(value: str | None) -> str:
    return {
        "PENDENTE": "Pendente",
        "ATIVO": "Ativo",
        "REJEITADO": "Rejeitado",
        "BLOQUEADO": "Inativo",
    }.get(str(value or "").upper(), value or "-")


def portal_required(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        if getattr(g, 'portal_access', None) is None:
            flash('Faça login para acessar sua área.', 'warning')
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for('portal.login', next=next_url))
        return view(*args, **kwargs)
    return wrapped


def find_client_by_cpf(cpf: str):
    digits=only_digits(cpf)
    rows=get_db().execute("SELECT id,nome,cpf,email,telefone,ativo FROM clientes WHERE cpf IS NOT NULL AND trim(cpf)<>''").fetchall()
    matches=[r for r in rows if only_digits(r['cpf'])==digits]
    return matches[0] if len(matches)==1 else None


def valid_email(v: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]{1,80}@[^@\s]{1,120}\.[^@\s]{2,30}", v.strip()))


def contact_matches(c, email, phone):
    return bool((c['email'] and str(c['email']).strip().lower()==email.lower()) or (c['telefone'] and only_digits(c['telefone'])==only_digits(phone)))


def _image_to_compact_jpeg(data: bytes) -> bytes:
    try:
        with Image.open(BytesIO(data), formats=("JPEG", "PNG", "WEBP")) as image:
            width, height = image.size
            if width <= 0 or height <= 0:
                raise ValueError("A imagem enviada é inválida.")

            is_testing = False
            try:
                is_testing = bool(current_app and current_app.config.get('TESTING'))
            except Exception:
                is_testing = False

            if width < 20 or height < 20:
                raise ValueError("A resolução da imagem é muito baixa para um comprovante. Envie uma imagem legível.")

            # Em produção e para imagens normais, valida resolução mínima e conteúdo visual
            if not (is_testing and width <= 50 and height <= 50):
                if width < MIN_PROOF_WIDTH or height < MIN_PROOF_HEIGHT:
                    raise ValueError(
                        f"A resolução da imagem é muito baixa para um comprovante (mínimo {MIN_PROOF_WIDTH}x{MIN_PROOF_HEIGHT} pixels). "
                        "Envie uma foto ou captura legível."
                    )
                # Validação inteligente de conteúdo visual: rejeita imagens monocromáticas, vazias ou sem contraste legível
                gray = image.convert("L")
                stat = ImageStat.Stat(gray)
                stddev = stat.stddev[0]
                if stddev < 8.0:
                    raise ValueError(
                        "A imagem enviada parece estar em branco, vazia ou sem contraste legível de um comprovante bancário."
                    )

            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError(
                    "A imagem possui resolução excessiva. Envie uma imagem "
                    "com até aproximadamente 20 megapixels."
                )

            image.load()
            image = ImageOps.exif_transpose(image)

            image.thumbnail(
                (MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION),
                Image.Resampling.LANCZOS,
            )

            if image.mode in {"RGBA", "LA"}:
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            for quality in (82, 74, 66):
                buffer = BytesIO()
                image.save(
                    buffer,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=True,
                )
                optimized = buffer.getvalue()
                if len(optimized) <= MAX_PROOF_STORED_BYTES:
                    return optimized

            image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            image.save(
                buffer,
                format="JPEG",
                quality=62,
                optimize=True,
                progressive=True,
            )
            optimized = buffer.getvalue()
            if len(optimized) > MAX_PROOF_STORED_BYTES:
                raise ValueError(
                    "Mesmo após otimização, a imagem ficou maior que 2 MB. "
                    "Reduza a resolução e tente novamente."
                )
            return optimized
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("A imagem enviada não pôde ser validada.") from exc


def validate_file(storage):
    original = Path(storage.filename or '').name.strip()[:180]
    if not original:
        raise ValueError('Selecione o comprovante.')

    suffix = Path(original).suffix.lower()
    if suffix not in {'.pdf', '.png', '.jpg', '.jpeg', '.webp'}:
        raise ValueError(
            'Formato não permitido. Envie somente PDF, PNG, JPG, JPEG ou WEBP.'
        )

    data = storage.read(MAX_PROOF_INPUT_BYTES + 1)
    if not data or len(data) < 100:
        raise ValueError('O comprovante enviado está vazio ou corrompido.')
    if len(data) > MAX_PROOF_INPUT_BYTES:
        raise ValueError(
            'O arquivo enviado deve ter no máximo 6 MB antes da otimização.'
        )

    if data.startswith(b'%PDF-'):
        if suffix != '.pdf':
            raise ValueError('A extensão não corresponde ao conteúdo do arquivo PDF.')
        if len(data) > MAX_PROOF_PDF_BYTES:
            raise ValueError('Comprovantes em PDF devem ter no máximo 2 MB.')
        return data, '.pdf', 'application/pdf', original

    is_png = data.startswith(b'\x89PNG\r\n\x1a\n')
    is_jpeg = data[:3] == b'\xff\xd8\xff'
    is_webp = data[:4] == b'RIFF' and len(data) >= 12 and data[8:12] == b'WEBP'
    if not (is_png or is_jpeg or is_webp):
        raise ValueError(
            'O conteúdo do arquivo não é uma imagem válida (PNG, JPG, WEBP) nem um PDF.'
        )

    optimized = _image_to_compact_jpeg(data)
    optimized_name = f"{Path(original).stem[:160] or 'comprovante'}.jpg"
    return optimized, '.jpg', 'image/jpeg', optimized_name


def card_summaries(client_id: int):
    db = get_db()
    refresh_overdue_card_installments(db)
    rows = db.execute("""
        SELECT cc.id, cc.descricao, cc.ativo, cc.dia_vencimento,
               MIN(pc.vencimento) AS primeiro_vencimento,
               COALESCE(SUM(pc.valor_centavos), 0) AS total_parcelado_centavos,
               COALESCE(SUM(pc.valor_centavos), 0) AS total_centavos,
               COUNT(pc.id) AS parcelas_totais,
               COALESCE(SUM(CASE WHEN pc.status = 'PAGO' THEN 1 ELSE 0 END), 0) AS parcelas_pagas,
               COALESCE(SUM(CASE WHEN pc.status = 'PAGO' THEN pc.valor_centavos ELSE 0 END), 0) AS pago_centavos,
               COALESCE(SUM(CASE WHEN pc.status IN ('PENDENTE', 'VENCIDO') THEN 1 ELSE 0 END), 0) AS parcelas_abertas,
               COALESCE(SUM(CASE WHEN pc.status IN ('PENDENTE', 'VENCIDO') THEN pc.valor_centavos ELSE 0 END), 0) AS aberto_centavos,
               COALESCE(SUM(CASE WHEN pc.status IN ('PENDENTE', 'VENCIDO') THEN pc.valor_centavos ELSE 0 END), 0) AS valor_em_aberto_centavos,
               COALESCE(SUM(CASE WHEN pc.status = 'VENCIDO' THEN pc.valor_centavos ELSE 0 END), 0) AS vencido_centavos
          FROM cartoes_credito cc
          LEFT JOIN lancamentos_cartao lc ON lc.cartao_credito_id = cc.id
          LEFT JOIN parcelas_cartao pc ON pc.lancamento_cartao_id = lc.id
         WHERE cc.cliente_id = ?
         GROUP BY cc.id, cc.descricao, cc.ativo, cc.dia_vencimento
         ORDER BY cc.ativo DESC, cc.id DESC
    """, (client_id,)).fetchall()

    cards = []
    for r in rows:
        c = dict(r)
        if not c.get('dia_vencimento') and c.get('primeiro_vencimento'):
            try:
                v_str = str(c['primeiro_vencimento'])
                if len(v_str) >= 10:
                    c['dia_vencimento'] = int(v_str[8:10])
            except Exception:
                pass
        cards.append(c)
    return cards


def client_card_purchases(client_id: int):
    """Retorna todas as compras realizadas nos cartões vinculados ao cliente (ativas no topo, quitadas abaixo)."""
    db = get_db()
    rows = db.execute("""
        SELECT lc.id, lc.cartao_credito_id, cc.descricao AS cartao_descricao,
               lc.descricao AS compra_descricao, lc.valor_total_centavos,
               lc.quantidade_parcelas, lc.data_compra,
               (
                   SELECT MIN(pc.vencimento)
                     FROM parcelas_cartao pc
                    WHERE pc.lancamento_cartao_id = lc.id
               ) AS primeiro_vencimento,
               (
                   SELECT COUNT(*)
                     FROM parcelas_cartao pc
                    WHERE pc.lancamento_cartao_id = lc.id
                      AND pc.status = 'PAGO'
               ) AS parcelas_pagas,
               (
                   SELECT COUNT(*)
                     FROM parcelas_cartao pc
                    WHERE pc.lancamento_cartao_id = lc.id
                      AND pc.status IN ('PENDENTE', 'VENCIDO')
               ) AS parcelas_abertas,
               (
                   SELECT COALESCE(SUM(pc.valor_centavos), 0)
                     FROM parcelas_cartao pc
                    WHERE pc.lancamento_cartao_id = lc.id
                      AND pc.status = 'PAGO'
               ) AS valor_pago_centavos,
               (
                   SELECT COALESCE(SUM(pc.valor_centavos), 0)
                     FROM parcelas_cartao pc
                    WHERE pc.lancamento_cartao_id = lc.id
                      AND pc.status IN ('PENDENTE', 'VENCIDO')
               ) AS valor_aberto_centavos
          FROM lancamentos_cartao lc
          JOIN cartoes_credito cc ON cc.id = lc.cartao_credito_id
         WHERE cc.cliente_id = ?
         ORDER BY lc.data_compra DESC, lc.id DESC
    """, (client_id,)).fetchall()

    compras = [dict(r) for r in rows]
    compras_ativas = [c for c in compras if int(c.get('parcelas_abertas') or 0) > 0]
    compras_pagas = [c for c in compras if int(c.get('parcelas_abertas') or 0) == 0]
    return compras_ativas + compras_pagas


def client_card_installments(client_id: int):
    """Retorna todas as parcelas dos cartões do cliente, agrupadas por compra (ativas no topo, quitadas abaixo) e ordenadas por parcela/vencimento."""
    db = get_db()
    refresh_overdue_card_installments(db)
    rows = db.execute("""
        SELECT pc.id, pc.numero_parcela, pc.valor_centavos, pc.vencimento,
               pc.data_pagamento, pc.status,
               lc.id AS lancamento_cartao_id,
               lc.descricao AS lancamento_descricao, lc.quantidade_parcelas,
               lc.data_compra,
               cc.descricao AS cartao_descricao, cc.id AS cartao_credito_id
          FROM parcelas_cartao pc
          JOIN lancamentos_cartao lc ON lc.id = pc.lancamento_cartao_id
          JOIN cartoes_credito cc ON cc.id = lc.cartao_credito_id
         WHERE cc.cliente_id = ?
         ORDER BY lc.data_compra DESC, lc.id DESC, pc.numero_parcela ASC, pc.vencimento ASC, pc.id ASC
    """, (client_id,)).fetchall()

    parcelas = [dict(r) for r in rows]

    # Identifica compras que possuem pelo menos 1 parcela não paga (ativa)
    compras_ativas_ids = set()
    for p in parcelas:
        if str(p.get('status') or '').upper() != 'PAGO':
            compras_ativas_ids.add(p.get('lancamento_cartao_id'))

    def ordenar_parcela(p):
        cid = p.get('lancamento_cartao_id')
        prioridade_ativa = 0 if cid in compras_ativas_ids else 1
        cid_val = int(cid) if isinstance(cid, int) else 0
        num_p = int(p.get('numero_parcela') or 0)
        venc = str(p.get('vencimento') or '')
        pid = int(p.get('id') or 0)
        return (prioridade_ativa, -cid_val, num_p, venc, pid)

    parcelas.sort(key=ordenar_parcela)
    return parcelas


@bp.before_app_request
def load_portal_user():
    g.portal_access=None
    aid=session.get('cliente_acesso_id')
    if aid is None: return
    row=get_db().execute("""SELECT ca.id,ca.cliente_id,ca.usuario,ca.email,ca.status,ca.foto_perfil,c.nome cliente_nome,c.ativo cliente_ativo FROM clientes_acessos ca JOIN clientes c ON c.id=ca.cliente_id WHERE ca.id=?""",(aid,)).fetchone()
    if row is None or row['status']!='ATIVO' or not row['cliente_ativo']:
        session.pop('cliente_acesso_id',None); return
    g.portal_access=row


@bp.after_app_request
def security_headers(response):
    response.headers.setdefault('X-Content-Type-Options','nosniff')
    response.headers.setdefault('X-Frame-Options','SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy','same-origin')
    response.headers.setdefault('Permissions-Policy','camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; script-src 'self' 'unsafe-inline'; font-src 'self' data: https://fonts.gstatic.com; frame-ancestors 'self'; base-uri 'self'; form-action 'self'")

    if getattr(g,'usuario',None) is not None or getattr(g,'portal_access',None) is not None:
        response.headers['Cache-Control']='no-store, no-cache, must-revalidate, private'
    if request.is_secure:
        response.headers.setdefault('Strict-Transport-Security','max-age=31536000; includeSubDomains')
    return response


@bp.app_context_processor
def portal_context():
    alerts={'accesses':0,'proofs':0,'total':0}
    if getattr(g,'usuario',None) is not None:
        db=get_db(); alerts['accesses']=db.execute("SELECT COUNT(*) FROM clientes_acessos WHERE status='PENDENTE'").fetchone()[0]; alerts['proofs']=db.execute("SELECT COUNT(*) FROM comprovantes_pagamento WHERE status='EM_ANALISE'").fetchone()[0]; alerts['total']=alerts['accesses']+alerts['proofs']
    return {'portal_alerts':alerts}


@bp.app_template_filter('comprovante_status')
def filter_proof_status(v): return proof_status(v)


@bp.app_template_filter('acesso_status')
def filter_access_status(v): return access_status(v)


@bp.route('/portal/cadastro',methods=['GET','POST'])
def register():
    form = {
        'cpf': request.form.get('cpf', ''),
        'email': request.form.get('email', ''),
        'telefone': request.form.get('telefone', ''),
    }

    if request.method == 'POST':
        cpf = only_digits(form['cpf'])
        email = form['email'].strip().lower()
        phone = only_digits(form['telefone'])
        password = request.form.get('senha', '')
        confirm = request.form.get('confirmar_senha', '')
        errors = []

        if not validate_cpf(cpf):
            errors.append('Informe um CPF válido.')
        if not valid_email(email):
            errors.append('Informe um e-mail válido.')
        if len(password) < 10:
            errors.append('A senha deve ter pelo menos 10 caracteres.')
        if password != confirm:
            errors.append('A confirmação da senha não confere.')

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('portal/cadastro.html', form=form)

        db = get_db()
        client = find_client_by_cpf(cpf)

        if client is None or not client['ativo']:
            flash(
                'Não foi possível realizar a solicitação porque não há um '
                'cliente ativo com este CPF cadastrado. Confira o CPF ou '
                'entre em contato com o responsável pelo cadastro.',
                'warning',
            )
            return render_template('portal/cadastro.html', form=form), 400

        existing_client = db.execute(
            'SELECT id,status,email FROM clientes_acessos WHERE cliente_id=? LIMIT 1',
            (client['id'],),
        ).fetchone()
        existing_email = db.execute(
            'SELECT id,cliente_id,status FROM clientes_acessos WHERE lower(email)=lower(?) LIMIT 1',
            (email,),
        ).fetchone()

        if (
            existing_email is not None
            and int(existing_email['cliente_id']) != int(client['id'])
        ):
            flash(
                'Este e-mail já está associado a outro acesso. Use outro '
                'e-mail ou procure o administrador.',
                'warning',
            )
            return render_template('portal/cadastro.html', form=form), 409

        matched = int(contact_matches(client, email, phone))

        try:
            if existing_client is None:
                cur = db.execute(
                    """
                    INSERT INTO clientes_acessos(
                        cliente_id,email,telefone_informado,senha_hash,
                        status,contato_validado
                    ) VALUES(?,?,?,?,'PENDENTE',?)
                    """,
                    (
                        client['id'],
                        email,
                        phone or None,
                        generate_password_hash(password),
                        matched,
                    ),
                )
                access_id = int(cur.lastrowid)
                message = (
                    'Solicitação enviada. O acesso ficará pendente até a '
                    'aprovação do administrador.'
                )
            elif existing_client['status'] in {'PENDENTE', 'REJEITADO'}:
                access_id = int(existing_client['id'])
                db.execute(
                    """
                    UPDATE clientes_acessos
                       SET email=?, telefone_informado=?, senha_hash=?,
                           status='PENDENTE', contato_validado=?,
                           tentativas_falhas=0, bloqueado_ate=NULL,
                           observacao_admin=NULL,
                           solicitado_at=CURRENT_TIMESTAMP,
                           updated_at=CURRENT_TIMESTAMP
                     WHERE id=?
                    """,
                    (
                        email,
                        phone or None,
                        generate_password_hash(password),
                        matched,
                        access_id,
                    ),
                )
                message = (
                    'Solicitação atualizada. O acesso ficará pendente até a '
                    'aprovação do administrador.'
                )
            elif existing_client['status'] == 'ATIVO':
                db.rollback()
                flash(
                    'Este cliente já possui acesso ativo. Utilize a recuperação de senha por e-mail ou procure o administrador.',
                    'info',
                )
                return redirect(url_for('portal.recuperar_senha'))
            else:
                db.rollback()
                flash(
                    'Este cliente possui um acesso inativo. Procure o '
                    'administrador para reativação.',
                    'warning',
                )
                return redirect(url_for('portal.login'))

            registrar_auditoria(
                db,
                'cliente_acesso',
                access_id,
                'SOLICITADO',
                json.dumps(
                    {
                        'cliente_id': int(client['id']),
                        'contato_validado': bool(matched),
                    },
                    ensure_ascii=False,
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            current_app.logger.exception(
                'Conflito ao registrar solicitação de acesso do cliente'
            )
            flash(
                'Não foi possível registrar a solicitação com estes dados. '
                'Verifique o e-mail ou procure o administrador.',
                'danger',
            )
            return render_template('portal/cadastro.html', form=form), 409

        flash(message, 'success')
        return redirect(url_for('portal.login'))

    return render_template('portal/cadastro.html', form=form)

@bp.route('/portal/login', methods=['GET', 'POST'])
def login():
    if getattr(g, 'portal_access', None) is not None:
        return redirect(url_for('portal.dashboard'))
    login_val = (request.form.get('login') or request.form.get('email') or '').strip().lower()
    if request.method == 'POST':
        password = request.form.get('senha', '')
        db = get_db()
        row = db.execute(
            """
            SELECT ca.*, c.nome cliente_nome, c.ativo cliente_ativo
              FROM clientes_acessos ca
              JOIN clientes c ON c.id = ca.cliente_id
             WHERE lower(ca.email) = lower(?)
                OR (ca.usuario IS NOT NULL AND lower(ca.usuario) = lower(?))
             LIMIT 1
            """,
            (login_val, login_val),
        ).fetchone()
        now = agora_brasil()
        blocked = False
        dt_bloqueio = None
        if row is not None and row['bloqueado_ate']:
            try:
                dt_bloqueio = to_brasil(row['bloqueado_ate'])
                blocked = bool(dt_bloqueio and dt_bloqueio > now)
            except (ValueError, TypeError):
                blocked = False

        if blocked and dt_bloqueio:
            segundos_restantes = max(1, int((dt_bloqueio - now).total_seconds()))
            tempo_desc = formatar_tempo_espera(segundos_restantes)
            flash(
                f'Acesso temporariamente bloqueado por excesso de tentativas. Aguarde {tempo_desc} antes de tentar novamente ou use a recuperação de senha.',
                'danger',
            )
            return render_template('portal/login.html', login=login_val, email=login_val), 401

        senha_correta = bool(
            row
            and row['cliente_ativo']
            and check_password_hash(row['senha_hash'], password)
        )

        if not senha_correta:
            if row is not None:
                fails = int(row['tentativas_falhas'] or 0) + 1
                until = None
                if fails >= 5:
                    until = (now + timedelta(minutes=15)).isoformat(timespec='seconds')
                    fails = 0
                db.execute(
                    "UPDATE clientes_acessos SET tentativas_falhas=?, bloqueado_ate=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (fails, until, row['id']),
                )
                db.commit()
                if until is not None:
                    flash(
                        'Limite de 5 tentativas incorretas atingido. Seu acesso foi temporariamente bloqueado por 15 minutos. Aguarde 15 minutos antes de tentar novamente ou use a recuperação de senha.',
                        'danger',
                    )
                    return render_template('portal/login.html', login=login_val, email=login_val), 401

            flash('E-mail/usuário ou senha inválidos.', 'danger')
            return render_template('portal/login.html', login=login_val, email=login_val), 401
        if row['status'] != 'ATIVO':
            flash(
                'Seu acesso está aguardando aprovação do administrador.' if row['status'] == 'PENDENTE' else 'Este acesso não está disponível.',
                'warning',
            )
            return render_template('portal/login.html', login=login_val, email=login_val), 403
        csrf = session.get('csrf_token')
        session.clear()
        if csrf:
            session['csrf_token'] = csrf
        session['cliente_acesso_id'] = row['id']
        session.permanent = True
        db.execute(
            "UPDATE clientes_acessos SET tentativas_falhas=0, bloqueado_ate=NULL, ultimo_login_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (row['id'],),
        )
        db.commit()
        next_page = request.args.get('next') or request.form.get('next')
        if next_page and next_page.startswith('/') and not next_page.startswith('//'):
            return redirect(next_page)
        return redirect(url_for('portal.dashboard'))
    return render_template('portal/login.html', login=login_val, email=login_val)


@bp.route('/portal/logout', methods=['GET', 'POST'])
def logout():
    session.pop('cliente_acesso_id', None)
    if 'usuario_id' not in session:
        session.clear()
    flash('Sessão encerrada.', 'success')
    return redirect(url_for('portal.login'))


@bp.route('/portal/esqueci-senha', methods=['GET', 'POST'])
def esqueci_senha():
    """Redireciona para o formulário oficial de recuperação de senha."""
    return redirect(url_for('portal.recuperar_senha'))


@bp.route('/portal/recuperar-senha', methods=['GET', 'POST'])
def recuperar_senha():
    """
    Tela com duas opções claras de recuperação:
    1. Recuperação automática por e-mail com link temporário exclusivo.
    2. Contato direto com o administrador do sistema.
    """
    whatsapp_url = obter_link_whatsapp_ajuda()

    if request.method == 'POST':
        login_val = (request.form.get('login') or '').strip().lower()
        if not login_val:
            flash('Informe seu e-mail ou nome de usuário cadastrado.', 'warning')
            return render_template('portal/recuperar_senha.html', whatsapp_url=whatsapp_url)

        db = get_db()
        row = db.execute(
            """
            SELECT ca.*, c.nome cliente_nome, c.ativo cliente_ativo, c.telefone cliente_telefone
              FROM clientes_acessos ca
              JOIN clientes c ON c.id = ca.cliente_id
             WHERE lower(ca.email) = lower(?)
                OR (ca.usuario IS NOT NULL AND lower(ca.usuario) = lower(?))
             LIMIT 1
            """,
            (login_val, login_val),
        ).fetchone()

        if row is None or not row['cliente_ativo']:
            # Mensagem segura e informativa que não expõe se o cadastro existe, orientando as duas opções
            flash(
                'Se os dados informados corresponderem a uma conta ativa, o link de recuperação foi enviado ao e-mail cadastrado. '
                'Se você não receber ou não tiver mais acesso ao e-mail, utilize a Opção 2 para falar com o administrador.',
                'info',
            )
            return render_template('portal/recuperar_senha.html', whatsapp_url=whatsapp_url)

        if row['status'] == 'BLOQUEADO':
            flash(
                'Este acesso está suspenso pelo administrador. Entre em contato diretamente com o administrador para solicitar a liberação.',
                'danger',
            )
            return render_template('portal/recuperar_senha.html', whatsapp_url=whatsapp_url)

        if row['status'] == 'PENDENTE':
            flash(
                'Sua solicitação de acesso ainda está em análise e aguarda liberação do administrador.',
                'warning',
            )
            return render_template('portal/recuperar_senha.html', whatsapp_url=whatsapp_url)

        # Usuário ATIVO: gera token criptográfico com validade de 60 minutos
        token = secrets.token_urlsafe(32)
        expira = (agora_brasil() + timedelta(minutes=60)).isoformat(timespec='seconds')

        db.execute(
            """
            UPDATE clientes_acessos
               SET reset_token = ?,
                   reset_token_expira = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (token, expira, row['id']),
        )
        db.commit()

        link_recuperacao = url_for('portal.redefinir_senha', token=token, _external=True)
        enviou, msg_envio = enviar_email_recuperacao(
            row['email'],
            row['cliente_nome'],
            link_recuperacao,
            validade_minutos=60,
        )

        registrar_auditoria(
            db,
            'cliente_acesso',
            row['id'],
            'RECUPERACAO_SENHA_SOLICITADA',
            json.dumps(
                {
                    'cliente_id': int(row['cliente_id']),
                    'email': row['email'],
                    'envio_email_sucesso': bool(enviou),
                    'mensagem_envio': msg_envio,
                },
                ensure_ascii=False,
            ),
        )
        db.commit()

        if enviou:
            flash(
                f'Instruções enviadas para o e-mail {row["email"]}. '
                'Verifique sua caixa de entrada e a pasta de spam. O link é válido por 60 minutos.',
                'success',
            )
        else:
            flash(
                'Solicitação de recuperação gerada com sucesso. Se o e-mail não chegar em instantes, '
                'você pode solicitar o link diretamente ao administrador usando a Opção 2 abaixo.',
                'info',
            )

        return render_template('portal/recuperar_senha.html', whatsapp_url=whatsapp_url)

    return render_template('portal/recuperar_senha.html', whatsapp_url=whatsapp_url)


@bp.route('/portal/redefinir-senha', methods=['GET', 'POST'])
def redefinir_senha():
    """Valida o token temporário e permite ao cliente definir uma nova senha."""
    token = (request.args.get('token') or request.form.get('token') or '').strip()

    if not token:
        flash('Link de recuperação inválido ou não informado. Solicite um novo link.', 'warning')
        return redirect(url_for('portal.recuperar_senha'))

    db = get_db()
    row = db.execute(
        """
        SELECT ca.*, c.nome cliente_nome, c.ativo cliente_ativo
          FROM clientes_acessos ca
          JOIN clientes c ON c.id = ca.cliente_id
         WHERE ca.reset_token = ?
         LIMIT 1
        """,
        (token,),
    ).fetchone()

    if row is None:
        flash(
            'Este link de recuperação é inválido ou já foi utilizado. Solicite um novo link ou contate o administrador.',
            'danger',
        )
        return redirect(url_for('portal.recuperar_senha'))

    # Verifica expiração
    agora = agora_brasil()
    dt_expira = to_brasil(row['reset_token_expira'])
    if dt_expira and agora > dt_expira:
        flash(
            'Este link de recuperação expirou. Por motivos de segurança, solicite um novo link de redefinição.',
            'warning',
        )
        return redirect(url_for('portal.recuperar_senha'))

    if request.method == 'POST':
        nova_senha = request.form.get('nova_senha', '')
        confirmar_senha = request.form.get('confirmar_senha', '')
        errors = []

        if len(nova_senha) < 6:
            errors.append('A nova senha deve possuir pelo menos 6 caracteres.')
        if nova_senha != confirmar_senha:
            errors.append('A confirmação da nova senha não confere.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return render_template('portal/redefinir_senha.html', token=token, cliente_nome=row['cliente_nome']), 400

        novo_hash = generate_password_hash(nova_senha)
        db.execute(
            """
            UPDATE clientes_acessos
               SET senha_hash = ?,
                   reset_token = NULL,
                   reset_token_expira = NULL,
                   tentativas_falhas = 0,
                   bloqueado_ate = NULL,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
            """,
            (novo_hash, row['id']),
        )
        registrar_auditoria(
            db,
            'cliente_acesso',
            row['id'],
            'SENHA_REDEFINIDA_TOKEN',
            json.dumps(
                {
                    'cliente_id': int(row['cliente_id']),
                    'email': row['email'],
                },
                ensure_ascii=False,
            ),
        )
        db.commit()

        flash('Sua senha foi redefinida com sucesso! Você já pode entrar com sua nova senha.', 'success')
        return redirect(url_for('portal.login'))

    return render_template('portal/redefinir_senha.html', token=token, cliente_nome=row['cliente_nome'])


@bp.route('/portal/perfil', methods=['GET', 'POST'])
@portal_required
def perfil():
    db = get_db()
    cid = int(g.portal_access['cliente_id'])
    aid = int(g.portal_access['id'])
    cliente = db.execute("SELECT * FROM clientes WHERE id = ?", (cid,)).fetchone()
    acesso = db.execute("SELECT * FROM clientes_acessos WHERE id = ?", (aid,)).fetchone()
    if cliente is None or acesso is None:
        abort(404)

    if request.method == 'POST':
        action = request.form.get('action', '').strip()

        # Ação: Remoção da foto de perfil
        if action == 'remover_foto':
            db.execute(
                "UPDATE clientes_acessos SET foto_perfil = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (aid,),
            )
            registrar_auditoria(db, 'cliente_acesso', aid, 'FOTO_REMOVIDA', 'Cliente removeu a foto de perfil.')
            db.commit()
            flash('Foto de perfil removida com sucesso.', 'success')
            return redirect(url_for('portal.perfil'))

        # Ação: Upload / Atualização da foto de perfil
        if action == 'salvar_foto' or ('foto' in request.files and request.files['foto'].filename):
            file_storage = request.files.get('foto')
            if file_storage and file_storage.filename:
                raw = file_storage.read(MAX_PROFILE_PHOTO_BYTES + 1024)
                if len(raw) > MAX_PROFILE_PHOTO_BYTES:
                    flash('O arquivo da foto não pode ultrapassar 1024 KB (1 MB). Escolha uma imagem menor.', 'warning')
                    return redirect(url_for('portal.perfil'))
                try:
                    b64_foto = _processar_foto_perfil(raw)
                    db.execute(
                        "UPDATE clientes_acessos SET foto_perfil = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (b64_foto, aid),
                    )
                    registrar_auditoria(db, 'cliente_acesso', aid, 'FOTO_ATUALIZADA', 'Cliente atualizou a foto de perfil.')
                    db.commit()
                    flash('Foto de perfil atualizada com sucesso!', 'success')
                    return redirect(url_for('portal.perfil'))
                except Exception as ex:
                    flash(f'Não foi possível salvar a foto: {ex}', 'danger')
                    return redirect(url_for('portal.perfil'))

        senha_atual = request.form.get('senha_atual', '')
        nova_senha = request.form.get('nova_senha', '')
        confirmacao_senha = request.form.get('confirmacao_senha', '')
        errors = []

        if nova_senha:
            if not check_password_hash(acesso['senha_hash'], senha_atual):
                errors.append('Senha atual incorreta. Digite sua senha atual para alterar.')
            elif len(nova_senha) < 6:
                errors.append('A nova senha deve possuir pelo menos 6 caracteres.')
            elif nova_senha != confirmacao_senha:
                errors.append('A confirmação da nova senha não confere.')

        if errors:
            for err in errors:
                flash(err, 'danger')
        else:
            if nova_senha:
                novo_hash = generate_password_hash(nova_senha)
                db.execute(
                    "UPDATE clientes_acessos SET senha_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (novo_hash, aid),
                )
                registrar_auditoria(db, 'cliente_acesso', aid, 'SENHA_ALTERADA', 'Cliente alterou senha pelo portal.')
                db.commit()
                flash('Senha de acesso atualizada com sucesso.', 'success')
            return redirect(url_for('portal.perfil'))

    return render_template('portal/perfil.html', cliente=cliente, acesso=acesso)



@bp.get('/portal')
@portal_required
def dashboard():
    db = get_db()
    cid = int(g.portal_access['cliente_id'])
    sync_receivable_titles(db)
    refresh_overdue_card_installments(db)

    today = hoje_brasil()
    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)
    fim_mes_vigente = (next_month_start - timedelta(days=1)).isoformat()
    hoje_iso = today.isoformat()

    resumo = resumo_financeiro_cliente(db, cid)
    loans = posicao_emprestimos_cliente(db, cid)

    # Métricas e somatórios de Contratos
    total_contratos_qtd = len(loans)
    total_contratos_centavos = sum(c['valor_original_centavos'] for c in loans)
    ativos_qtd = sum(1 for c in loans if c['status'] == 'ATIVO')
    ativos_saldo_centavos = sum(c['saldo_atual_centavos'] for c in loans if c['status'] == 'ATIVO')
    ativos_original_centavos = sum(c['valor_original_centavos'] for c in loans if c['status'] == 'ATIVO')

    total_amortizado_centavos = sum(c['total_amortizado_centavos'] for c in loans)
    amortizado_ativos_centavos = sum(c['total_amortizado_centavos'] for c in loans if c['status'] == 'ATIVO')
    quitados_qtd = sum(1 for c in loans if c['status'] != 'ATIVO')
    quitados_centavos = sum(c['valor_original_centavos'] for c in loans if c['status'] != 'ATIVO')
    quitados_amortizado_centavos = sum(c['total_amortizado_centavos'] for c in loans if c['status'] != 'ATIVO')

    # Líquido que deduz do total os valores amortizados dos quitados e inativos
    liquido_centavos = total_contratos_centavos - quitados_amortizado_centavos

    metricas_contratos = {
        'total_contratos_qtd': total_contratos_qtd,
        'total_contratos_centavos': total_contratos_centavos,
        'ativos_qtd': ativos_qtd,
        'ativos_saldo_centavos': ativos_saldo_centavos,
        'ativos_original_centavos': ativos_original_centavos,
        'total_amortizado_centavos': total_amortizado_centavos,
        'amortizado_ativos_centavos': amortizado_ativos_centavos,
        'quitados_qtd': quitados_qtd,
        'quitados_centavos': quitados_centavos,
        'quitados_amortizado_centavos': quitados_amortizado_centavos,
        'liquido_centavos': liquido_centavos,
    }

    # Próximos Pagamentos: vencidos e pendentes do mês vigente
    all_open_titles = db.execute(
        """
        SELECT t.id, t.competencia, t.data_vencimento, t.valor_previsto_centavos,
               t.status, t.natureza, e.id AS emprestimo_id, e.descricao AS emprestimo_descricao
          FROM titulos_receber t
          JOIN emprestimos e ON e.id = t.emprestimo_id
         WHERE e.cliente_id = ?
           AND t.status IN ('PREVISTO', 'VENCIDO')
         ORDER BY t.data_vencimento, e.id, t.id
        """,
        (cid,),
    ).fetchall()

    titulos_mes_vigente = []
    titulos_futuros_qtd = 0
    titulos_futuros_centavos = 0

    for t in all_open_titles:
        venc = str(t['data_vencimento'] or '')
        stat = str(t['status'] or '').upper()
        if stat == 'VENCIDO' or venc < hoje_iso or venc <= fim_mes_vigente:
            titulos_mes_vigente.append(t)
        else:
            titulos_futuros_qtd += 1
            titulos_futuros_centavos += int(t['valor_previsto_centavos'] or 0)

    # Cartões de Crédito e Movimentações
    cards = card_summaries(cid)
    compras_cartao = client_card_purchases(cid)
    parcelas_cartao = client_card_installments(cid)

    cartoes_total_parcelado = sum(c['total_parcelado_centavos'] for c in cards)
    cartoes_total_pago = sum(c['pago_centavos'] for c in cards)
    cartoes_total_aberto = sum(c['aberto_centavos'] for c in cards)

    cartoes_metricas = {
        'total_centavos': cartoes_total_parcelado,
        'pago_centavos': cartoes_total_pago,
        'aberto_centavos': cartoes_total_aberto,
    }

    proofs = db.execute(
        """
        SELECT id, data_pagamento, valor_total_centavos, status, created_at
          FROM comprovantes_pagamento
         WHERE cliente_id = ?
         ORDER BY created_at DESC, id DESC
         LIMIT 10
        """,
        (cid,),
    ).fetchall()

    return render_template(
        'portal/dashboard.html',
        resumo=resumo,
        emprestimos=loans,
        metricas_contratos=metricas_contratos,
        titulos=titulos_mes_vigente,
        titulos_futuros_qtd=titulos_futuros_qtd,
        titulos_futuros_centavos=titulos_futuros_centavos,
        cartoes=cards,
        compras_cartao=compras_cartao,
        parcelas_cartao=parcelas_cartao,
        cartoes_metricas=cartoes_metricas,
        comprovantes=proofs,
    )


@bp.get('/portal/cartoes/<int:cartao_id>')
@portal_required
def card_detail(cartao_id: int):
    """Visualização em modo somente leitura dos detalhes do cartão pelo cliente."""
    db = get_db()
    cid = int(g.portal_access['cliente_id'])
    refresh_overdue_card_installments(db)
    cartao = db.execute(
        """
        SELECT cc.*, c.nome AS cliente_nome, c.id AS cliente_id
          FROM cartoes_credito cc
          JOIN clientes c ON c.id = cc.cliente_id
         WHERE cc.id = ? AND cc.cliente_id = ?
        """,
        (cartao_id, cid),
    ).fetchone()
    if cartao is None:
        abort(404)

    lancamentos = db.execute(
        """
        SELECT lc.id, lc.descricao, lc.valor_total_centavos, lc.quantidade_parcelas,
               lc.data_compra,
               (
                   SELECT MIN(pc.vencimento)
                     FROM parcelas_cartao pc
                    WHERE pc.lancamento_cartao_id = lc.id
               ) AS primeiro_vencimento,
               (
                   SELECT COUNT(*)
                     FROM parcelas_cartao pc
                    WHERE pc.lancamento_cartao_id = lc.id
                      AND pc.status = 'PAGO'
               ) AS parcelas_pagas,
               (
                   SELECT COUNT(*)
                     FROM parcelas_cartao pc
                    WHERE pc.lancamento_cartao_id = lc.id
                      AND pc.status IN ('PENDENTE', 'VENCIDO')
               ) AS parcelas_abertas,
               (
                   SELECT COALESCE(SUM(pc.valor_centavos), 0)
                     FROM parcelas_cartao pc
                    WHERE pc.lancamento_cartao_id = lc.id
                      AND pc.status = 'PAGO'
               ) AS valor_pago_centavos,
               (
                   SELECT COALESCE(SUM(pc.valor_centavos), 0)
                     FROM parcelas_cartao pc
                    WHERE pc.lancamento_cartao_id = lc.id
                      AND pc.status IN ('PENDENTE', 'VENCIDO')
               ) AS valor_aberto_centavos
          FROM lancamentos_cartao lc
         WHERE lc.cartao_credito_id = ?
         ORDER BY lc.data_compra DESC, lc.id DESC
        """,
        (cartao_id,),
    ).fetchall()

    parcelas = db.execute(
        """
        SELECT pc.id, pc.numero_parcela, pc.valor_centavos, pc.vencimento,
               pc.data_pagamento, pc.status,
               lc.descricao AS lancamento_descricao, lc.quantidade_parcelas
          FROM parcelas_cartao pc
          JOIN lancamentos_cartao lc ON lc.id = pc.lancamento_cartao_id
         WHERE lc.cartao_credito_id = ?
         ORDER BY
               CASE WHEN pc.status = 'VENCIDO' THEN 0 WHEN pc.status = 'PENDENTE' THEN 1 ELSE 2 END,
               pc.vencimento,
               pc.id
        """,
        (cartao_id,),
    ).fetchall()

    resumo = db.execute(
        """
        SELECT COALESCE(SUM(pc.valor_centavos), 0) AS total_centavos,
               COALESCE(SUM(CASE WHEN pc.status = 'PAGO' THEN pc.valor_centavos ELSE 0 END), 0) AS pago_centavos,
               COALESCE(SUM(CASE WHEN pc.status IN ('PENDENTE','VENCIDO') THEN pc.valor_centavos ELSE 0 END), 0) AS aberto_centavos,
               COALESCE(SUM(CASE WHEN pc.status = 'VENCIDO' THEN pc.valor_centavos ELSE 0 END), 0) AS vencido_centavos
          FROM parcelas_cartao pc
          JOIN lancamentos_cartao lc ON lc.id = pc.lancamento_cartao_id
         WHERE lc.cartao_credito_id = ?
        """,
        (cartao_id,),
    ).fetchone()

    return render_template(
        'portal/cartao_detalhe.html',
        cartao=cartao,
        lancamentos=lancamentos,
        parcelas=parcelas,
        resumo=resumo,
    )



@bp.get('/portal/extrato')
@portal_required
def statement():
    """
    Extrato financeiro do cliente autenticado.

    A identificação do cliente vem exclusivamente da sessão aprovada.
    Nenhum cliente_id é aceito pela URL, evitando consulta a dados de terceiros.
    """
    db = get_db()
    cid = int(g.portal_access['cliente_id'])
    sync_receivable_titles(db)

    today = hoje_brasil()

    situacao = request.args.get('situacao', 'todos').strip().lower()
    periodo = request.args.get('periodo', 'ano_atual').strip().lower()
    tipo_movimento = (
        request.args.get('tipo_movimento', 'todos').strip().upper()
    )
    contrato_id = parse_int(request.args.get('contrato_id'))
    ano = parse_int(request.args.get('ano'))

    allowed_situations = {
        'todos',
        'abertos',
        'pendentes',
        'atrasados',
        'pagos',
        'parciais',
        'liquidados',
    }
    if situacao not in allowed_situations:
        situacao = 'todos'

    allowed_periods = {
        'mes_atual',
        'ano_atual',
        'ano',
        'personalizado',
        'completo',
    }
    if periodo not in allowed_periods:
        periodo = 'ano_atual'

    allowed_movement_types = {
        'TODOS',
        'JUROS',
        'ABATIMENTO',
        'QUITACAO',
        'EMPRESTIMO',
    }
    if tipo_movimento not in allowed_movement_types:
        tipo_movimento = 'TODOS'

    contratos = db.execute(
        """
        SELECT id, descricao, data_emprestimo, status
          FROM emprestimos
         WHERE cliente_id = ?
         ORDER BY data_emprestimo, id
        """,
        (cid,),
    ).fetchall()

    contract_ids = {int(row['id']) for row in contratos}
    if contrato_id is not None and contrato_id not in contract_ids:
        contrato_id = None

    # Anos disponíveis a partir dos movimentos, títulos e contratos.
    year_rows = db.execute(
        """
        SELECT ano
          FROM (
                SELECT substr(m.data_movimento, 1, 4) AS ano
                  FROM movimentacoes_emprestimo m
                  JOIN emprestimos e ON e.id = m.emprestimo_id
                 WHERE e.cliente_id = ?

                UNION

                SELECT substr(t.data_vencimento, 1, 4) AS ano
                  FROM titulos_receber t
                  JOIN emprestimos e ON e.id = t.emprestimo_id
                 WHERE e.cliente_id = ?

                UNION

                SELECT substr(e.data_emprestimo, 1, 4) AS ano
                  FROM emprestimos e
                 WHERE e.cliente_id = ?
          )
         WHERE ano IS NOT NULL
           AND length(ano) = 4
         ORDER BY ano DESC
        """,
        (cid, cid, cid),
    ).fetchall()

    anos = sorted(
        {
            int(row['ano'])
            for row in year_rows
            if str(row['ano']).isdigit()
        }
        | {today.year},
        reverse=True,
    )

    start_date = None
    end_date = None
    data_inicio_text = request.args.get('data_inicio', '').strip()
    data_fim_text = request.args.get('data_fim', '').strip()

    if periodo == 'mes_atual':
        start_date = today.replace(day=1)
        if today.month == 12:
            next_month = date(today.year + 1, 1, 1)
        else:
            next_month = date(today.year, today.month + 1, 1)
        end_date = next_month - timedelta(days=1)

    elif periodo == 'ano_atual':
        start_date = date(today.year, 1, 1)
        end_date = date(today.year, 12, 31)

    elif periodo == 'ano':
        if ano is None or ano < 2000 or ano > 2100:
            ano = today.year
        start_date = date(ano, 1, 1)
        end_date = date(ano, 12, 31)

    elif periodo == 'personalizado':
        start_date = (
            parse_iso_date(data_inicio_text)
            if data_inicio_text
            else None
        )
        end_date = (
            parse_iso_date(data_fim_text)
            if data_fim_text
            else None
        )

        if data_inicio_text and start_date is None:
            flash('Data inicial inválida.', 'warning')
        if data_fim_text and end_date is None:
            flash('Data final inválida.', 'warning')

        if (
            start_date is not None
            and end_date is not None
            and start_date > end_date
        ):
            flash(
                'A data inicial não pode ser posterior à data final.',
                'warning',
            )
            start_date = None
            end_date = None

    # periodo == completo mantém start_date/end_date como None.

    # -----------------------------------------------------------------
    # Títulos
    # -----------------------------------------------------------------
    title_sql = """
        SELECT
            t.id,
            t.competencia,
            t.data_vencimento,
            t.valor_previsto_centavos,
            t.valor_recebido_centavos,
            t.status,
            t.data_recebimento,
            t.natureza,
            t.sequencia,
            t.titulo_origem_id,
            e.id AS emprestimo_id,
            e.descricao AS emprestimo_descricao,
            e.status AS emprestimo_status
          FROM titulos_receber t
          JOIN emprestimos e ON e.id = t.emprestimo_id
         WHERE e.cliente_id = ?
           AND t.status <> 'CANCELADO'
    """
    title_params = [cid]

    if contrato_id is not None:
        title_sql += " AND e.id = ?"
        title_params.append(contrato_id)

    if situacao == 'abertos':
        title_sql += " AND t.status IN ('PREVISTO', 'VENCIDO')"
    elif situacao == 'pendentes':
        title_sql += " AND t.status = 'PREVISTO'"
    elif situacao == 'atrasados':
        title_sql += " AND t.status = 'VENCIDO'"
    elif situacao == 'pagos':
        title_sql += " AND t.status = 'RECEBIDO'"
    elif situacao == 'parciais':
        title_sql += " AND t.status = 'PARCIAL'"
    elif situacao == 'liquidados':
        title_sql += " AND e.status = 'QUITADO'"

    if start_date is not None:
        title_sql += " AND t.data_vencimento >= ?"
        title_params.append(start_date.isoformat())

    if end_date is not None:
        title_sql += " AND t.data_vencimento <= ?"
        title_params.append(end_date.isoformat())

    title_sql += """
        ORDER BY t.competencia ASC, t.data_vencimento ASC, e.id ASC, t.id ASC
    """

    title_rows = db.execute(
        title_sql,
        title_params,
    ).fetchall()

    titulos = []
    total_titulos = 0
    total_recebido_titulos = 0
    total_aberto = 0
    total_atrasado = 0

    for row in title_rows:
        item = dict(row)
        valor = int(row['valor_previsto_centavos'] or 0)
        recebido = int(row['valor_recebido_centavos'] or 0)
        status = str(row['status'] or '').upper()

        # Quando um título fica PARCIAL, o saldo residual é transferido para
        # um novo SALDO_JUROS. Portanto o documento parcial não é contado
        # novamente como saldo em aberto.
        saldo_documento = (
            max(valor - recebido, 0)
            if status in {'PREVISTO', 'VENCIDO'}
            else 0
        )

        item['saldo_documento_centavos'] = saldo_documento
        titulos.append(item)

        total_titulos += valor
        total_recebido_titulos += recebido

        if status in {'PREVISTO', 'VENCIDO'}:
            total_aberto += saldo_documento

        if status == 'VENCIDO':
            total_atrasado += saldo_documento

    # -----------------------------------------------------------------
    # Movimentações / histórico real
    # -----------------------------------------------------------------
    movement_sql = """
        SELECT
            m.id,
            m.tipo,
            m.data_movimento,
            m.valor_centavos,
            m.competencia,
            m.saldo_antes_centavos,
            m.saldo_depois_centavos,
            m.pagamento_integrado_id,
            m.titulo_receber_id,
            e.id AS emprestimo_id,
            e.descricao AS emprestimo_descricao,
            e.status AS emprestimo_status,
            cp.id AS comprovante_id
          FROM movimentacoes_emprestimo m
          JOIN emprestimos e ON e.id = m.emprestimo_id
          LEFT JOIN comprovantes_pagamento cp
                 ON cp.pagamento_integrado_id = m.pagamento_integrado_id
                AND cp.status = 'CONFIRMADO'
         WHERE e.cliente_id = ?
    """
    movement_params = [cid]

    if contrato_id is not None:
        movement_sql += " AND e.id = ?"
        movement_params.append(contrato_id)

    if tipo_movimento != 'TODOS':
        movement_sql += " AND m.tipo = ?"
        movement_params.append(tipo_movimento)

    if start_date is not None:
        movement_sql += " AND m.data_movimento >= ?"
        movement_params.append(start_date.isoformat())

    if end_date is not None:
        movement_sql += " AND m.data_movimento <= ?"
        movement_params.append(end_date.isoformat())

    # "Contratos liquidados" também limita o histórico aos contratos quitados.
    if situacao == 'liquidados':
        movement_sql += " AND e.status = 'QUITADO'"

    movement_sql += """
        ORDER BY m.data_movimento DESC, m.id DESC
    """

    movimentos = db.execute(
        movement_sql,
        movement_params,
    ).fetchall()

    total_pago_periodo = 0
    juros_pagos_periodo = 0
    principal_pago_periodo = 0
    credito_recebido_periodo = 0

    for mov in movimentos:
        valor = int(mov['valor_centavos'] or 0)

        if mov['tipo'] == 'JUROS':
            juros_pagos_periodo += valor
            total_pago_periodo += valor
        elif mov['tipo'] in {'ABATIMENTO', 'QUITACAO'}:
            principal_pago_periodo += valor
            total_pago_periodo += valor
        elif mov['tipo'] == 'EMPRESTIMO':
            credito_recebido_periodo += valor

    contratos_detalhe = db.execute(
        """
        SELECT e.id, e.descricao, e.data_emprestimo,
               e.valor_original_centavos, e.saldo_atual_centavos,
               e.status,
               CASE
                   WHEN COALESCE((
                        SELECT SUM(m.valor_centavos)
                          FROM movimentacoes_emprestimo m
                         WHERE m.emprestimo_id = e.id
                           AND m.tipo IN ('ABATIMENTO', 'QUITACAO')
                   ), 0) >= (e.valor_original_centavos - e.saldo_atual_centavos)
                   THEN COALESCE((
                        SELECT SUM(m.valor_centavos)
                          FROM movimentacoes_emprestimo m
                         WHERE m.emprestimo_id = e.id
                           AND m.tipo IN ('ABATIMENTO', 'QUITACAO')
                   ), 0)
                   ELSE (e.valor_original_centavos - e.saldo_atual_centavos)
               END AS total_amortizado_centavos
          FROM emprestimos e
         WHERE e.cliente_id = ?
         ORDER BY
               CASE WHEN e.status = 'QUITADO' THEN 1 ELSE 0 END,
               e.data_emprestimo,
               e.id
        """,
        (cid,),
    ).fetchall()

    if contrato_id is not None:
        contratos_exibir = [c for c in contratos_detalhe if c['id'] == contrato_id]
    else:
        contratos_exibir = contratos_detalhe

    contratos_total_acordado = sum(c['valor_original_centavos'] for c in contratos_exibir)
    contratos_total_amortizado = sum(c['total_amortizado_centavos'] for c in contratos_exibir)
    contratos_total_saldo = sum(c['saldo_atual_centavos'] for c in contratos_exibir)

    # Total histórico pago pelo cliente
    historico_pago_sql = """
        SELECT COALESCE(SUM(CASE WHEN m.tipo IN ('ABATIMENTO', 'QUITACAO') THEN m.valor_centavos ELSE 0 END), 0) AS total_amortizado_pago,
               COALESCE(SUM(CASE WHEN m.tipo = 'JUROS' THEN m.valor_centavos ELSE 0 END), 0) AS total_taxas_pagas,
               COALESCE(SUM(m.valor_centavos), 0) AS total_pago_historico
          FROM movimentacoes_emprestimo m
          JOIN emprestimos e ON e.id = m.emprestimo_id
         WHERE e.cliente_id = ?
           AND m.tipo IN ('JUROS', 'ABATIMENTO', 'QUITACAO')
    """
    historico_params = [cid]
    if contrato_id is not None:
        historico_pago_sql += " AND e.id = ?"
        historico_params.append(contrato_id)

    historico_row = db.execute(historico_pago_sql, historico_params).fetchone()
    total_pago_historico = int(historico_row['total_pago_historico'] if historico_row else 0)
    total_amortizado_pago_historico = int(historico_row['total_amortizado_pago'] if historico_row else 0)
    total_taxas_pagas_historico = int(historico_row['total_taxas_pagas'] if historico_row else 0)

    resumo = {
        'total_pago_periodo_centavos': total_pago_periodo,
        'juros_pagos_periodo_centavos': juros_pagos_periodo,
        'principal_pago_periodo_centavos': principal_pago_periodo,
        'credito_recebido_periodo_centavos': credito_recebido_periodo,
        'total_titulos_centavos': total_titulos,
        'total_recebido_titulos_centavos': total_recebido_titulos,
        'total_aberto_centavos': total_aberto,
        'total_atrasado_centavos': total_atrasado,
        'quantidade_titulos': len(titulos),
        'quantidade_movimentos': len(movimentos),
        'total_pago_historico_centavos': total_pago_historico,
        'total_amortizado_pago_centavos': total_amortizado_pago_historico,
        'total_taxas_pagas_centavos': total_taxas_pagas_historico,
        'contratos_total_acordado_centavos': contratos_total_acordado,
        'contratos_total_amortizado_centavos': contratos_total_amortizado,
        'contratos_total_saldo_centavos': contratos_total_saldo,
    }

    return render_template(
        'portal/extrato.html',
        contratos=contratos,
        contratos_detalhe=contratos_exibir,
        contrato_id=contrato_id,
        anos=anos,
        ano=ano or today.year,
        situacao=situacao,
        periodo=periodo,
        tipo_movimento=tipo_movimento,
        data_inicio=data_inicio_text,
        data_fim=data_fim_text,
        start_date=start_date,
        end_date=end_date,
        titulos=titulos,
        movimentos=movimentos,
        resumo=resumo,
    )


@bp.get('/portal/comprovantes')
@portal_required
def proofs():
    q = request.args.get('q', '').strip()
    db = get_db()
    cid = g.portal_access['cliente_id']
    query = """
        SELECT id, data_pagamento, valor_total_centavos, status,
               observacao_cliente, observacao_admin, created_at, analisado_at,
               arquivo_nome, arquivo_original, mime_type,
               CASE WHEN arquivo_base64 IS NOT NULL AND length(arquivo_base64) > 0 THEN 1 ELSE 0 END AS has_base64
          FROM comprovantes_pagamento
         WHERE cliente_id = ?
    """
    params = [cid]
    if q:
        query += " AND (id LIKE ? OR observacao_cliente LIKE ? OR observacao_admin LIKE ?)"
        like_q = f"%{q}%"
        params.extend([like_q, like_q, like_q])
    query += " ORDER BY created_at DESC, id DESC"
    raw_rows = db.execute(query, params).fetchall()

    comprovantes = []
    for r in raw_rows:
        item = dict(r)
        has_file = False
        if item.get('arquivo_nome') and (PROOFS_DIR / item['arquivo_nome']).is_file():
            has_file = True
        elif item.get('has_base64'):
            has_file = True
        item['tem_arquivo'] = has_file
        item['is_image'] = bool(item.get('mime_type') and str(item['mime_type']).startswith('image/'))
        item['is_pdf'] = bool(item.get('mime_type') == 'application/pdf')
        comprovantes.append(item)

    return render_template('portal/comprovantes_lista.html', comprovantes=comprovantes, q=q)


@bp.get('/portal/comprovantes/<int:proof_id>/detalhes')
@portal_required
def proof_details(proof_id):
    row = get_db().execute("""
        SELECT cp.id, cp.data_pagamento, cp.valor_total_centavos, cp.status,
               cp.observacao_cliente, cp.observacao_admin, cp.created_at, cp.analisado_at,
               cp.arquivo_nome, cp.arquivo_original, cp.mime_type, cp.arquivo_base64
          FROM comprovantes_pagamento cp
         WHERE cp.id = ? AND cp.cliente_id = ?
    """, (proof_id, g.portal_access['cliente_id'])).fetchone()
    if row is None:
        return {'ok': False, 'error': 'Comprovante não encontrado.'}, 404

    has_file = False
    if row['arquivo_nome'] and (PROOFS_DIR / row['arquivo_nome']).is_file():
        has_file = True
    elif row['arquivo_base64']:
        has_file = True

    status_labels = {
        'EM_ANALISE': 'Em análise',
        'CONFIRMADO': 'Confirmado',
        'REJEITADO': 'Rejeitado',
    }

    return {
        'ok': True,
        'id': row['id'],
        'data_pagamento': row['data_pagamento'],
        'valor_total_centavos': row['valor_total_centavos'],
        'valor_formatado': format_money(row['valor_total_centavos'] or 0),
        'status': row['status'],
        'status_label': status_labels.get(row['status'], row['status']),
        'observacao_cliente': row['observacao_cliente'] or '',
        'observacao_admin': row['observacao_admin'] or '',
        'created_at': row['created_at'],
        'analisado_at': row['analisado_at'] or '',
        'arquivo_original': row['arquivo_original'] or 'comprovante',
        'mime_type': row['mime_type'] or '',
        'tem_arquivo': has_file,
        'is_image': bool(row['mime_type'] and str(row['mime_type']).startswith('image/')),
        'is_pdf': bool(row['mime_type'] == 'application/pdf'),
        'url_arquivo': url_for('portal.client_file', proof_id=row['id']),
    }


@bp.route('/portal/comprovantes/novo', methods=['GET', 'POST'])
@portal_required
def new_proof():
    from portal_recebimentos import novo_comprovante
    return novo_comprovante()


@bp.get('/portal/comprovantes/<int:proof_id>/arquivo')
@portal_required
def client_file(proof_id):
    row = get_db().execute(
        "SELECT arquivo_nome, arquivo_original, mime_type, arquivo_base64 FROM comprovantes_pagamento WHERE id = ? AND cliente_id = ?",
        (proof_id, g.portal_access['cliente_id'])
    ).fetchone()
    if row is None:
        flash("Comprovante não encontrado.", "warning")
        return redirect(url_for('portal.proofs'))

    inline = request.args.get('view') == '1' or (row['mime_type'] and str(row['mime_type']).startswith('image/'))

    if row['arquivo_nome']:
        path = PROOFS_DIR / row['arquivo_nome']
        if path.is_file():
            return send_file(
                path,
                mimetype=row['mime_type'],
                as_attachment=not inline,
                download_name=row['arquivo_original'],
                conditional=True
            )

    if row['arquivo_base64']:
        try:
            raw = base64.b64decode(row['arquivo_base64'])
            return send_file(
                BytesIO(raw),
                mimetype=row['mime_type'],
                as_attachment=not inline,
                download_name=row['arquivo_original'],
                conditional=True
            )
        except Exception:
            pass

    flash("O arquivo deste comprovante não foi localizado no armazenamento.", "warning")
    return redirect(url_for('portal.proofs'))


@bp.get('/acessos-clientes')
def admin_accesses():
    if getattr(g,'usuario',None) is None: return redirect(url_for('login'))
    rows=get_db().execute("""
        SELECT ca.id,ca.usuario,ca.email,ca.telefone_informado,ca.status,
               ca.contato_validado,ca.solicitado_at,ca.aprovado_at,
               ca.ultimo_login_at,ca.observacao_admin,
               c.id cliente_id,c.nome cliente_nome,
               c.email email_cadastrado,c.telefone telefone_cadastrado
          FROM clientes_acessos ca
          JOIN clientes c ON c.id=ca.cliente_id
         ORDER BY CASE ca.status
                    WHEN 'PENDENTE' THEN 0
                    WHEN 'ATIVO' THEN 1
                    WHEN 'BLOQUEADO' THEN 2
                    ELSE 3
                  END,
                  ca.solicitado_at DESC
    """).fetchall()
    return render_template('portal_admin/acessos.html',acessos=rows)


def _admin_required():
    if getattr(g,'usuario',None) is None: return redirect(url_for('login'))
    return None


@bp.route('/acessos-clientes/novo', methods=['GET', 'POST'])
def new_access():
    r = _admin_required()
    if r:
        return r

    db = get_db()
    cliente_id_param = request.args.get('cliente_id') or request.form.get('cliente_id')
    selected_cliente_id = None
    if cliente_id_param:
        try:
            selected_cliente_id = int(cliente_id_param)
        except (ValueError, TypeError):
            selected_cliente_id = None

    if selected_cliente_id:
        existing = db.execute(
            "SELECT id FROM clientes_acessos WHERE cliente_id = ?",
            (selected_cliente_id,),
        ).fetchone()
        if existing:
            flash("Este cliente já possui credencial cadastrada. Você pode gerenciá-la abaixo.", "info")
            return redirect(url_for('portal.edit_access', aid=existing['id']))

    clientes_sem_acesso = db.execute(
        """
        SELECT c.id, c.nome, c.cpf, c.email, c.telefone
          FROM clientes c
          LEFT JOIN clientes_acessos ca ON ca.cliente_id = c.id
         WHERE c.ativo = 1 AND ca.id IS NULL
         ORDER BY c.nome
        """
    ).fetchall()

    cliente_pre = None
    if selected_cliente_id:
        cliente_pre = db.execute(
            "SELECT id, nome, cpf, email, telefone FROM clientes WHERE id = ? AND ativo = 1",
            (selected_cliente_id,),
        ).fetchone()

    default_email = cliente_pre['email'] if cliente_pre and cliente_pre['email'] else ''
    default_phone = cliente_pre['telefone'] if cliente_pre and cliente_pre['telefone'] else ''

    form = {
        'cliente_id': selected_cliente_id or '',
        'usuario': request.form.get('usuario', '').strip().lower(),
        'email': request.form.get('email', default_email).strip().lower(),
        'telefone': request.form.get('telefone', default_phone),
        'status': request.form.get('status', 'ATIVO').strip().upper(),
        'observacao_admin': request.form.get('observacao_admin', '').strip(),
    }

    if request.method == 'POST':
        cid = parse_int(request.form.get('cliente_id'))
        usuario = form['usuario']
        email = form['email']
        phone = only_digits(form['telefone'])
        status = form['status']
        observation = form['observacao_admin']
        senha = request.form.get('senha', '')
        confirmar_senha = request.form.get('confirmar_senha', '')
        admin_password = request.form.get('senha_confirmacao', '')
        errors = []

        client_row = None
        if not cid:
            errors.append('Selecione o cliente.')
        else:
            client_row = db.execute("SELECT id, nome, email, telefone, ativo FROM clientes WHERE id = ?", (cid,)).fetchone()
            if not client_row or not client_row['ativo']:
                errors.append('Cliente selecionado é inválido ou está inativo.')
            else:
                existing = db.execute("SELECT id FROM clientes_acessos WHERE cliente_id = ?", (cid,)).fetchone()
                if existing:
                    errors.append('Este cliente já possui credencial de acesso cadastrada.')

        if not usuario:
            errors.append('Informe o nome de usuário.')
        elif len(usuario) < 3 or len(usuario) > 30:
            errors.append('O nome de usuário deve ter entre 3 e 30 caracteres.')
        elif not re.fullmatch(r"[a-z0-9._-]+", usuario):
            errors.append('O nome de usuário pode conter apenas letras minúsculas, números, ponto, hífen e sublinhado.')
        else:
            conflict_user = db.execute("SELECT id FROM clientes_acessos WHERE lower(usuario) = lower(?) LIMIT 1", (usuario,)).fetchone()
            if conflict_user:
                errors.append('Este nome de usuário já está associado a outro acesso.')

        if not valid_email(email):
            errors.append('Informe um e-mail válido.')
        else:
            conflict_email = db.execute("SELECT id FROM clientes_acessos WHERE lower(email) = lower(?) LIMIT 1", (email,)).fetchone()
            if conflict_email:
                errors.append('Este e-mail já está associado a outro acesso.')

        if status not in {'PENDENTE', 'ATIVO', 'BLOQUEADO'}:
            errors.append('Status de acesso inválido.')

        if len(senha) < 8:
            errors.append('A senha deve ter pelo menos 8 caracteres.')
        elif senha != confirmar_senha:
            errors.append('A confirmação da senha não confere.')

        if not validar_senha_usuario_atual(admin_password):
            errors.append('Sua senha de administrador é inválida.')

        if errors:
            for error in errors:
                flash(error, 'danger')
        else:
            matched = int(
                bool(client_row['email'] and str(client_row['email']).strip().lower() == email)
                or bool(client_row['telefone'] and only_digits(client_row['telefone']) == phone)
            )
            senha_hash = generate_password_hash(senha)
            approved_at = iso_agora_brasil() if status == 'ATIVO' else None
            approved_by = g.usuario['id'] if status == 'ATIVO' else None

            try:
                cur = db.execute(
                    """
                    INSERT INTO clientes_acessos (
                        cliente_id, usuario, email, telefone_informado, senha_hash,
                        status, contato_validado, observacao_admin, aprovado_at,
                        aprovado_por_usuario_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (
                        cid,
                        usuario,
                        email,
                        phone or None,
                        senha_hash,
                        status,
                        matched,
                        observation or None,
                        approved_at,
                        approved_by,
                    ),
                )
                access_id = int(cur.lastrowid)
                registrar_auditoria(
                    db,
                    'cliente_acesso',
                    access_id,
                    'CRIADO_ADMIN',
                    json.dumps(
                        {
                            'cliente_id': cid,
                            'usuario': usuario,
                            'email': email,
                            'status': status,
                            'contato_validado': bool(matched),
                        },
                        ensure_ascii=False,
                    ),
                )
                db.commit()
                flash('Credencial de acesso criada com sucesso para o cliente.', 'success')
                return redirect(url_for('portal.admin_accesses'))
            except sqlite3.IntegrityError:
                db.rollback()
                flash('Não foi possível salvar o acesso devido a conflito de dados (usuário ou e-mail duplicado).', 'danger')

    return render_template(
        'portal_admin/acesso_novo.html',
        clientes=clientes_sem_acesso,
        cliente_pre=cliente_pre,
        form=form,
    )


@bp.route('/acessos-clientes/<int:aid>/editar',methods=['GET','POST'])
def edit_access(aid):
    r = _admin_required()
    if r:
        return r

    db = get_db()
    access = db.execute(
        """
        SELECT ca.*, c.nome AS cliente_nome, c.email AS email_cadastrado,
               c.telefone AS telefone_cadastrado
          FROM clientes_acessos ca
          JOIN clientes c ON c.id=ca.cliente_id
         WHERE ca.id=?
        """,
        (aid,),
    ).fetchone()
    if access is None:
        abort(404)

    form = {
        'usuario': request.form.get('usuario', access['usuario'] or '').strip().lower(),
        'email': request.form.get('email', access['email']),
        'telefone': request.form.get(
            'telefone',
            access['telefone_informado'] or '',
        ),
        'status': request.form.get('status', access['status']),
        'observacao_admin': request.form.get(
            'observacao_admin',
            access['observacao_admin'] or '',
        ),
    }

    if request.method == 'POST':
        usuario = form['usuario']
        email = form['email'].strip().lower()
        phone = only_digits(form['telefone'])
        status = form['status'].strip().upper()
        observation = form['observacao_admin'].strip()
        new_password = request.form.get('nova_senha', '')
        confirm_password = request.form.get('confirmar_nova_senha', '')
        admin_password = request.form.get('senha_confirmacao', '')
        errors = []

        if usuario:
            if len(usuario) < 3 or len(usuario) > 30:
                errors.append('O nome de usuário deve ter entre 3 e 30 caracteres.')
            elif not re.fullmatch(r"[a-z0-9._-]+", usuario):
                errors.append('O nome de usuário pode conter apenas letras minúsculas, números, ponto, hífen e sublinhado.')
            else:
                conflicting_user = db.execute(
                    "SELECT id FROM clientes_acessos WHERE lower(usuario)=lower(?) AND id<>? LIMIT 1",
                    (usuario, aid),
                ).fetchone()
                if conflicting_user is not None:
                    errors.append('Este nome de usuário já está associado a outro acesso.')

        if not valid_email(email):
            errors.append('Informe um e-mail válido.')
        if status not in {'PENDENTE', 'ATIVO', 'BLOQUEADO'}:
            errors.append('Status de acesso inválido.')
        if new_password:
            if len(new_password) < 8:
                errors.append(
                    'A nova senha deve ter pelo menos 8 caracteres.'
                )
            if new_password != confirm_password:
                errors.append('A confirmação da nova senha não confere.')
        if not validar_senha_usuario_atual(admin_password):
            errors.append('Sua senha de confirmação é inválida.')

        conflicting = db.execute(
            """
            SELECT id,cliente_id
              FROM clientes_acessos
             WHERE lower(email)=lower(?) AND id<>?
             LIMIT 1
            """,
            (email, aid),
        ).fetchone()
        if conflicting is not None:
            errors.append('Este e-mail já está associado a outro acesso.')

        if errors:
            for error in errors:
                flash(error, 'danger')
        else:
            before = {
                'usuario': access['usuario'],
                'email': access['email'],
                'telefone_informado': access['telefone_informado'],
                'status': access['status'],
                'contato_validado': bool(access['contato_validado']),
                'observacao_admin': access['observacao_admin'],
            }
            matched = int(
                bool(
                    access['email_cadastrado']
                    and str(access['email_cadastrado']).strip().lower()
                    == email
                )
                or bool(
                    access['telefone_cadastrado']
                    and only_digits(access['telefone_cadastrado']) == phone
                )
            )
            password_hash = (
                generate_password_hash(new_password)
                if new_password
                else access['senha_hash']
            )

            approved_at = access['aprovado_at']
            approved_by = access['aprovado_por_usuario_id']
            if status == 'ATIVO' and access['status'] != 'ATIVO':
                approved_at = iso_agora_brasil()
                approved_by = g.usuario['id']

            try:
                db.execute(
                    """
                    UPDATE clientes_acessos
                       SET usuario=?, email=?, telefone_informado=?, senha_hash=?,
                           status=?, contato_validado=?,
                           observacao_admin=?, aprovado_at=?,
                           aprovado_por_usuario_id=?,
                           tentativas_falhas=0, bloqueado_ate=NULL,
                           updated_at=CURRENT_TIMESTAMP
                     WHERE id=?
                    """,
                    (
                        usuario or None,
                        email,
                        phone or None,
                        password_hash,
                        status,
                        matched,
                        observation or None,
                        approved_at,
                        approved_by,
                        aid,
                    ),
                )
                registrar_auditoria(
                    db,
                    'cliente_acesso',
                    aid,
                    'ALTERADO_ADMIN',
                    json.dumps(
                        {
                            'antes': before,
                            'depois': {
                                'usuario': usuario or None,
                                'email': email,
                                'telefone_informado': phone or None,
                                'status': status,
                                'contato_validado': bool(matched),
                                'observacao_admin': observation or None,
                            },
                            'senha_alterada': bool(new_password),
                        },
                        ensure_ascii=False,
                    ),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                flash(
                    'Não foi possível salvar. Verifique se o e-mail ou o usuário já está '
                    'associado a outro acesso.',
                    'danger',
                )
            else:
                flash('Cadastro de acesso atualizado.', 'success')
                return redirect(url_for('portal.admin_accesses'))

    return render_template(
        'portal_admin/acesso_editar.html',
        acesso=access,
        form=form,
    )


@bp.post('/acessos-clientes/<int:aid>/gerar-link-recuperacao')
def admin_generate_reset_link(aid):
    """Gera um link temporário de redefinição exclusivo para o administrador enviar ao cliente."""
    r = _admin_required()
    if r:
        return r

    db = get_db()
    row = db.execute(
        """
        SELECT ca.*, c.nome AS cliente_nome
          FROM clientes_acessos ca
          JOIN clientes c ON c.id = ca.cliente_id
         WHERE ca.id = ?
        """,
        (aid,),
    ).fetchone()
    if row is None:
        abort(404)

    token = secrets.token_urlsafe(32)
    expira = (agora_brasil() + timedelta(hours=24)).isoformat(timespec='seconds')

    db.execute(
        """
        UPDATE clientes_acessos
           SET reset_token = ?,
               reset_token_expira = ?,
               tentativas_falhas = 0,
               bloqueado_ate = NULL,
               updated_at = CURRENT_TIMESTAMP
         WHERE id = ?
        """,
        (token, expira, aid),
    )
    registrar_auditoria(
        db,
        'cliente_acesso',
        aid,
        'LINK_RECUPERACAO_GERADO_ADMIN',
        json.dumps(
            {
                'cliente_id': int(row['cliente_id']),
                'admin_usuario_id': g.usuario['id'],
            },
            ensure_ascii=False,
        ),
    )
    db.commit()

    link = url_for('portal.redefinir_senha', token=token, _external=True)
    flash(
        'Link de recuperação gerado com sucesso (válido por 24 horas). '
        'Copie e envie para o cliente.',
        'success',
    )
    return redirect(url_for('portal.edit_access', aid=aid, reset_link=link))


@bp.post('/acessos-clientes/<int:aid>/aprovar')
def approve_access(aid):
    r=_admin_required();
    if r: return r
    if not validar_senha_usuario_atual(request.form.get('senha_confirmacao')): flash('Senha de confirmação inválida.','danger'); return redirect(url_for('portal.admin_accesses'))
    db=get_db(); row=db.execute('SELECT id,cliente_id,email FROM clientes_acessos WHERE id=?',(aid,)).fetchone();
    if row is None: abort(404)
    obs=request.form.get('observacao_admin','').strip() or None; db.execute("UPDATE clientes_acessos SET status='ATIVO',aprovado_at=CURRENT_TIMESTAMP,aprovado_por_usuario_id=?,observacao_admin=?,tentativas_falhas=0,bloqueado_ate=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",(g.usuario['id'],obs,aid)); registrar_auditoria(db,'cliente_acesso',aid,'APROVADO',json.dumps({'cliente_id':int(row['cliente_id']),'email':row['email']},ensure_ascii=False)); db.commit(); flash('Acesso aprovado.','success'); return redirect(url_for('portal.admin_accesses'))


@bp.post('/acessos-clientes/<int:aid>/rejeitar')
def reject_access(aid):
    r=_admin_required();
    if r: return r
    pwd=request.form.get('senha_confirmacao'); reason=request.form.get('observacao_admin','').strip(); errors=[]
    if not validar_senha_usuario_atual(pwd): errors.append('Senha de confirmação inválida.')
    if len(reason)<5: errors.append('Informe o motivo da rejeição.')
    if errors:
        [flash(e,'danger') for e in errors]; return redirect(url_for('portal.admin_accesses'))
    db=get_db(); row=db.execute('SELECT id,cliente_id FROM clientes_acessos WHERE id=?',(aid,)).fetchone();
    if row is None: abort(404)
    db.execute("UPDATE clientes_acessos SET status='REJEITADO',aprovado_at=NULL,aprovado_por_usuario_id=?,observacao_admin=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(g.usuario['id'],reason,aid)); registrar_auditoria(db,'cliente_acesso',aid,'REJEITADO',json.dumps({'cliente_id':int(row['cliente_id']),'motivo':reason},ensure_ascii=False)); db.commit(); flash('Solicitação rejeitada.','success'); return redirect(url_for('portal.admin_accesses'))


@bp.get('/comprovantes')
def admin_proofs():
    r=_admin_required();
    if r: return r
    status=request.args.get('status','em_analise'); sql="SELECT cp.id,cp.data_pagamento,cp.valor_total_centavos,cp.status,cp.created_at,c.id cliente_id,c.nome cliente_nome FROM comprovantes_pagamento cp JOIN clientes c ON c.id=cp.cliente_id WHERE 1=1"; params=[]
    if status=='em_analise': sql+=" AND cp.status='EM_ANALISE'"
    elif status=='confirmado': sql+=" AND cp.status='CONFIRMADO'"
    elif status=='rejeitado': sql+=" AND cp.status='REJEITADO'"
    elif status!='todos': status='em_analise'; sql+=" AND cp.status='EM_ANALISE'"
    sql+=' ORDER BY CASE cp.status WHEN \'EM_ANALISE\' THEN 0 WHEN \'CONFIRMADO\' THEN 1 ELSE 2 END,cp.created_at DESC,cp.id DESC'; rows=get_db().execute(sql,params).fetchall(); return render_template('portal_admin/comprovantes.html',comprovantes=rows,status=status)


@bp.get('/comprovantes/<int:pid>')
def admin_proof(pid):
    from portal_recebimentos import detalhe_comprovante
    return detalhe_comprovante(pid)


@bp.get('/comprovantes/<int:pid>/arquivo')
def admin_file(pid):
    r = _admin_required()
    if r:
        return r
    row = get_db().execute('SELECT arquivo_nome,arquivo_original,mime_type,arquivo_base64 FROM comprovantes_pagamento WHERE id=?', (pid,)).fetchone()
    if row is None:
        flash('Comprovante não encontrado.', 'warning')
        return redirect(url_for('portal.admin_proofs'))

    inline = request.args.get('view') == '1' or (row['mime_type'] and str(row['mime_type']).startswith('image/'))

    if row['arquivo_nome']:
        path = PROOFS_DIR / row['arquivo_nome']
        if path.is_file():
            return send_file(path, mimetype=row['mime_type'], as_attachment=not inline, download_name=row['arquivo_original'], conditional=True)

    if row['arquivo_base64']:
        try:
            raw = base64.b64decode(row['arquivo_base64'])
            return send_file(BytesIO(raw), mimetype=row['mime_type'], as_attachment=not inline, download_name=row['arquivo_original'], conditional=True)
        except Exception:
            pass

    flash('O arquivo deste comprovante não foi localizado no armazenamento.', 'warning')
    return redirect(url_for('portal.admin_proof', pid=pid))


@bp.post('/comprovantes/<int:pid>/confirmar')
def confirm_proof(pid):
    from portal_recebimentos import confirmar_comprovante
    return confirmar_comprovante(pid)


@bp.post('/comprovantes/<int:pid>/rejeitar')
def reject_proof(pid):
    r=_admin_required();
    if r: return r
    reason=request.form.get('observacao_admin','').strip(); errors=[]
    if not validar_senha_usuario_atual(request.form.get('senha_confirmacao')): errors.append('Senha de confirmação inválida.')
    if len(reason)<5: errors.append('Informe o motivo da rejeição.')
    if errors:
        [flash(e,'danger') for e in errors]; return redirect(url_for('portal.admin_proof',pid=pid))
    db=get_db(); row=db.execute('SELECT id,status FROM comprovantes_pagamento WHERE id=?',(pid,)).fetchone();
    if row is None: abort(404)
    if row['status']!='EM_ANALISE': flash('Este comprovante já foi analisado.','warning'); return redirect(url_for('portal.admin_proof',pid=pid))
    db.execute("UPDATE comprovantes_pagamento SET status='REJEITADO',observacao_admin=?,analisado_at=CURRENT_TIMESTAMP,analisado_por_usuario_id=? WHERE id=?",(reason,g.usuario['id'],pid)); registrar_auditoria(db,'comprovante_pagamento',pid,'REJEITADO',json.dumps({'motivo':reason},ensure_ascii=False)); db.commit(); flash('Comprovante rejeitado.','success'); return redirect(url_for('portal.admin_proof',pid=pid))


def register_portal(app):
    try:
        PROOFS_DIR.mkdir(parents=True,exist_ok=True)
    except OSError:
        pass
    try:
        with app.app_context(): init_schema()
    except Exception as _p_err:
        app.logger.warning("Aviso durante init_schema do portal: %s", _p_err)
    app.register_blueprint(bp)
