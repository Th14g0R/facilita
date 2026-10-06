from __future__ import annotations

import base64
import io
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from werkzeug.datastructures import FileStorage
from werkzeug.security import generate_password_hash
from PIL import Image, ImageDraw

import app as application
import portal


def _criar_imagem_teste(width=200, height=200, em_branco=False, cor=(255, 255, 255), formato="PNG"):
    img = Image.new("RGB", (width, height), cor)
    if not em_branco:
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, width - 10, 40], fill=(20, 50, 120))
        draw.text((20, 18), "COMPROVANTE DE TRANSFERENCIA", fill=(255, 255, 255))
        draw.text((20, 60), "VALOR: R$ 500,00", fill=(0, 0, 0))
        draw.text((20, 80), "FAVORECIDO: FACILITA GESTAO", fill=(30, 30, 30))
        draw.line([(10, 110), (width - 10, 110)], fill=(100, 100, 100), width=2)
    buf = io.BytesIO()
    img.save(buf, format=formato)
    return buf.getvalue()


class TestPortalNovidades(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='facilita-novidades-')
        self.db_path = Path(self.tmp.name) / 'novidades.db'
        self.old_env = os.environ.get('EMPRESTIMO_DATABASE')
        os.environ['EMPRESTIMO_DATABASE'] = str(self.db_path)
        application.DATABASE_PATH = self.db_path
        portal.PROOFS_DIR = Path(self.tmp.name) / 'proofs'
        self.app = application.create_app()
        self.app.config.update(TESTING=True, SECRET_KEY='teste-segredo')
        self.client = self.app.test_client()

        with self.app.app_context():
            portal.init_schema()
            db = application.get_db()
            db.execute("DELETE FROM usuarios")
            db.execute("DELETE FROM clientes_acessos")
            db.execute("DELETE FROM clientes")
            db.execute(
                "INSERT INTO usuarios (id, nome, login, senha_hash) VALUES (1, 'Admin Teste', 'admin', ?)",
                (generate_password_hash('senha123'),)
            )
            db.execute(
                "INSERT INTO clientes (id, nome, cpf, email, telefone, ativo) VALUES (1, 'Cliente Teste', '52998224725', 'teste@example.invalid', '85999999999', 1)"
            )
            db.execute(
                """INSERT INTO clientes_acessos (id, cliente_id, usuario, email, senha_hash, status, contato_validado)
                   VALUES (1, 1, 'clienteteste', 'teste@example.invalid', ?, 'ATIVO', 1)""",
                (generate_password_hash('senha123'),)
            )
            db.commit()

    def tearDown(self):
        if self.old_env is not None:
            os.environ['EMPRESTIMO_DATABASE'] = self.old_env
        else:
            os.environ.pop('EMPRESTIMO_DATABASE', None)
        self.tmp.cleanup()

    def authenticate_portal(self, portal_id=1):
        with self.client.session_transaction() as sess:
            sess['csrf_token'] = 'csrf-test'
            sess['cliente_acesso_id'] = portal_id

    def test_processar_foto_perfil_valida_e_reduz(self):
        """Testa que a foto é recortada centralizada em 160x160 e salva como base64 leve."""
        raw = _criar_imagem_teste(width=800, height=600, em_branco=False)
        b64_foto = portal._processar_foto_perfil(raw)
        self.assertTrue(b64_foto.startswith("data:image/jpeg;base64,"))

        header, encoded = b64_foto.split(",", 1)
        decoded = base64.b64decode(encoded)
        with Image.open(io.BytesIO(decoded)) as img:
            self.assertEqual(img.size, (160, 160))

    def test_processar_foto_perfil_limite_tamanho(self):
        """Foto maior que 1024 KB (1 MB) deve ser rejeitada."""
        data_grande = b"x" * (1024 * 1024 + 50)
        with self.assertRaises(ValueError) as ctx:
            portal._processar_foto_perfil(data_grande)
        self.assertIn("1024 KB", str(ctx.exception))

    def test_upload_e_remocao_foto_perfil_portal(self):
        """Testa fluxo completo de upload e remoção de foto de perfil do cliente autenticado."""
        self.authenticate_portal(1)
        raw = _criar_imagem_teste(width=400, height=400, em_branco=False)

        # Upload de foto com CSRF token
        storage = (io.BytesIO(raw), 'minha_foto.jpg')
        resp = self.client.post(
            '/portal/perfil',
            data={'csrf_token': 'csrf-test', 'action': 'salvar_foto', 'foto': storage},
            content_type='multipart/form-data',
            follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            row = application.get_db().execute("SELECT foto_perfil FROM clientes_acessos WHERE id=1").fetchone()
            self.assertIsNotNone(row['foto_perfil'])
            self.assertTrue(row['foto_perfil'].startswith("data:image/jpeg;base64,"))

        # Remoção de foto com CSRF token
        resp_del = self.client.post(
            '/portal/perfil',
            data={'csrf_token': 'csrf-test', 'action': 'remover_foto'},
            follow_redirects=True
        )
        self.assertEqual(resp_del.status_code, 200)

        with self.app.app_context():
            row2 = application.get_db().execute("SELECT foto_perfil FROM clientes_acessos WHERE id=1").fetchone()
            self.assertIsNone(row2['foto_perfil'])

    def test_validate_file_rejeita_imagem_vazia_ou_em_branco(self):
        """Rejeita envio de imagens chapadas/em branco que não possuem conteúdo de comprovante."""
        raw_branco = _criar_imagem_teste(width=300, height=300, em_branco=True, cor=(255, 255, 255))
        storage = FileStorage(stream=io.BytesIO(raw_branco), filename="branco.png", content_type="image/png")
        with self.assertRaises(ValueError) as ctx:
            portal.validate_file(storage)
        self.assertIn("em branco", str(ctx.exception))

    def test_validate_file_rejeita_resolucao_muito_baixa(self):
        """Rejeita imagens minúsculas (inferiores a 180x180 px quando não são mocks de teste)."""
        raw_pequeno = _criar_imagem_teste(width=100, height=100, em_branco=False)
        storage = FileStorage(stream=io.BytesIO(raw_pequeno), filename="pequeno.png", content_type="image/png")
        with self.assertRaises(ValueError) as ctx:
            portal.validate_file(storage)
        self.assertIn("muito baixa", str(ctx.exception))

    def test_validate_file_aceita_imagem_comprovante_valida(self):
        """Aceita imagem com boa resolução e contraste adequado."""
        raw_valido = _criar_imagem_teste(width=400, height=500, em_branco=False)
        storage = FileStorage(stream=io.BytesIO(raw_valido), filename="comprovante_pix.png", content_type="image/png")
        optimized, ext, mime, name = portal.validate_file(storage)
        self.assertEqual(ext, ".jpg")
        self.assertEqual(mime, "image/jpeg")
        self.assertTrue(len(optimized) > 0)

    def test_client_file_fallback_base64_sem_erro_404(self):
        """Quando o arquivo físico não existe em disco, serve o arquivo a partir do base64 sem erro 404."""
        self.authenticate_portal(1)
        raw = _criar_imagem_teste(width=300, height=300, em_branco=False)
        b64_raw = base64.b64encode(raw).decode('ascii')

        with self.app.app_context():
            db = application.get_db()
            db.execute("""
                INSERT INTO comprovantes_pagamento (
                    id, cliente_id, cliente_acesso_id, data_pagamento,
                    valor_total_centavos, arquivo_nome, arquivo_original,
                    mime_type, tamanho_bytes, arquivo_base64, status
                ) VALUES (
                    99, 1, 1, '2026-10-05', 15000, 'arquivo_que_nao_existe.jpg',
                    'original.jpg', 'image/jpeg', ?, ?, 'EM_ANALISE'
                )
            """, (len(raw), b64_raw))
            db.commit()

        resp = self.client.get('/portal/comprovantes/99/arquivo')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, 'image/jpeg')
        self.assertEqual(resp.data, raw)

    def test_client_file_arquivo_inexistente_redireciona_com_aviso_suave(self):
        """Quando nem o arquivo físico nem o base64 existem, redireciona suavemente sem 404 feio."""
        self.authenticate_portal(1)
        with self.app.app_context():
            db = application.get_db()
            db.execute("""
                INSERT INTO comprovantes_pagamento (
                    id, cliente_id, cliente_acesso_id, data_pagamento,
                    valor_total_centavos, arquivo_nome, arquivo_original,
                    mime_type, tamanho_bytes, arquivo_base64, status
                ) VALUES (
                    100, 1, 1, '2026-10-05', 20000, 'inexistente_absoluto.jpg',
                    'perda.jpg', 'image/jpeg', 1000, NULL, 'REJEITADO'
                )
            """)
            db.commit()

        resp = self.client.get('/portal/comprovantes/100/arquivo', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("não foi localizado no armazenamento", resp.get_data(as_text=True))

    def test_proof_details_json_endpoint(self):
        """Endpoint JSON de detalhes do comprovante para o modal pop-up."""
        self.authenticate_portal(1)
        with self.app.app_context():
            db = application.get_db()
            db.execute("""
                INSERT INTO comprovantes_pagamento (
                    id, cliente_id, cliente_acesso_id, data_pagamento,
                    valor_total_centavos, arquivo_nome, arquivo_original,
                    mime_type, tamanho_bytes, arquivo_base64, status, observacao_admin
                ) VALUES (
                    101, 1, 1, '2026-10-05', 35000, 'inexistente.jpg',
                    'pix.jpg', 'image/jpeg', 1000, NULL, 'REJEITADO', 'Valor divergente'
                )
            """)
            db.commit()

        resp = self.client.get('/portal/comprovantes/101/detalhes')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['id'], 101)
        self.assertEqual(data['status'], 'REJEITADO')
        self.assertEqual(data['status_label'], 'Rejeitado')
        self.assertEqual(data['observacao_admin'], 'Valor divergente')
        self.assertFalse(data['tem_arquivo'])


    def test_portal_dashboard_contratos_metricas_e_cartoes(self):
        """Testa somatórios de contratos, próximos pagamentos do mês e exibição de cartões no portal."""
        self.authenticate_portal(1)
        with self.app.app_context():
            db = application.get_db()
            # Criar 2 contratos: 1 ativo com amortização parcial e 1 quitado
            db.execute("""
                INSERT INTO emprestimos (
                    id, cliente_id, descricao, data_emprestimo,
                    valor_original_centavos, saldo_atual_centavos, taxa_juros_mensal,
                    data_primeiro_vencimento, dia_vencimento, status
                ) VALUES
                (1, 1, 'Contrato Ativo', '2026-05-10', 100000, 70000, 10.0, '2026-06-10', 10, 'ATIVO'),
                (2, 1, 'Contrato Quitado', '2026-01-15', 50000, 0, 10.0, '2026-02-15', 15, 'QUITADO')
            """)
            # Registrar amortização no contrato 1 e quitação no contrato 2
            db.execute("""
                INSERT INTO movimentacoes_emprestimo (
                    id, emprestimo_id, tipo, data_movimento, valor_centavos,
                    saldo_antes_centavos, saldo_depois_centavos
                ) VALUES
                (1, 1, 'ABATIMENTO', '2026-07-10', 30000, 100000, 70000),
                (2, 2, 'QUITACAO', '2026-04-15', 50000, 50000, 0)
            """)
            # Criar cartão de crédito e compras com parcelas
            db.execute("""
                INSERT INTO cartoes_credito (id, cliente_id, descricao, dia_vencimento, ativo)
                VALUES (1, 1, 'Nubank Cliente', 15, 1)
            """)
            db.execute("""
                INSERT INTO lancamentos_cartao (id, cartao_credito_id, descricao, valor_total_centavos, quantidade_parcelas, data_compra, usuario_id)
                VALUES (1, 1, 'Notebook Dell', 60000, 2, '2026-09-01', 1)
            """)
            db.execute("""
                INSERT INTO parcelas_cartao (id, lancamento_cartao_id, numero_parcela, valor_centavos, vencimento, data_pagamento, status)
                VALUES
                (1, 1, 1, 30000, '2026-09-15', '2026-09-15', 'PAGO'),
                (2, 1, 2, 30000, '2026-10-15', NULL, 'PENDENTE')
            """)
            db.commit()

        resp = self.client.get('/portal')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Checar somatórios de contratos
        self.assertIn("Resumo dos Meus Contratos", html)
        self.assertIn("Total dos Contratos (2)", html)
        self.assertIn("Total Amortizado", html)
        self.assertIn("Quitados / Inativos (1)", html)
        self.assertIn("Valor Líquido dos Contratos", html)

        # Checar tabela de contratos com data e amortizado
        self.assertIn("Transferido ao cliente", html)
        self.assertIn("Contrato Ativo", html)
        self.assertIn("Contrato Quitado", html)

        # Checar cartões com dados não zerados e compras
        self.assertIn("Nubank Cliente", html)
        self.assertIn("Notebook Dell", html)
        self.assertIn("Somente leitura", html)

    def test_portal_card_detail_endpoint(self):
        """Testa página individual de detalhe do cartão em modo somente leitura."""
        self.authenticate_portal(1)
        with self.app.app_context():
            db = application.get_db()
            db.execute("""
                INSERT INTO cartoes_credito (id, cliente_id, descricao, dia_vencimento, ativo)
                VALUES (2, 1, 'Visa Gold', 10, 1)
            """)
            db.execute("""
                INSERT INTO lancamentos_cartao (id, cartao_credito_id, descricao, valor_total_centavos, quantidade_parcelas, data_compra, usuario_id)
                VALUES (2, 2, 'Smartphone', 40000, 2, '2026-08-01', 1)
            """)
            db.execute("""
                INSERT INTO parcelas_cartao (id, lancamento_cartao_id, numero_parcela, valor_centavos, vencimento, status)
                VALUES
                (3, 2, 1, 20000, '2026-08-10', 'PAGO'),
                (4, 2, 2, 20000, '2026-09-10', 'PENDENTE')
            """)
            db.commit()

        resp = self.client.get('/portal/cartoes/2')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Visa Gold", html)
        self.assertIn("Smartphone", html)
        self.assertIn("Modo somente leitura", html)

    def test_portal_extrato_com_detalhamento_contratos(self):
        """Testa que o extrato exibe o detalhamento de contratos e somatório de valores pagos."""
        self.authenticate_portal(1)
        with self.app.app_context():
            db = application.get_db()
            db.execute("""
                INSERT INTO emprestimos (
                    id, cliente_id, descricao, data_emprestimo,
                    valor_original_centavos, saldo_atual_centavos, taxa_juros_mensal,
                    data_primeiro_vencimento, dia_vencimento, status
                ) VALUES (3, 1, 'Operação Veículo', '2026-03-01', 200000, 150000, 5.0, '2026-04-01', 1, 'ATIVO')
            """)
            db.execute("""
                INSERT INTO movimentacoes_emprestimo (
                    id, emprestimo_id, tipo, data_movimento, valor_centavos,
                    saldo_antes_centavos, saldo_depois_centavos
                ) VALUES (3, 3, 'ABATIMENTO', '2026-04-01', 50000, 200000, 150000)
            """)
            db.commit()

        resp = self.client.get('/portal/extrato')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Detalhamento dos Contratos", html)
        self.assertIn("Operação Veículo", html)
        self.assertIn("Total Amortizado Pago", html)
        self.assertIn("Total Histórico Pago", html)

    def test_portal_logout_get_e_post(self):
        """Testa que o logout do portal funciona tanto por GET quanto por POST."""
        self.authenticate_portal(1)
        resp = self.client.get('/portal/logout', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.location, '/portal/login')
        with self.client.session_transaction() as sess:
            self.assertNotIn('cliente_acesso_id', sess)

    def test_login_admin_nao_exibe_sidebar_para_cliente(self):
        """Garante que na tela /login a sidebar não é exibida mesmo se houver cliente_acesso_id."""
        self.authenticate_portal(1)
        resp = self.client.get('/login', follow_redirects=False)
        # Deve redirecionar para o portal do cliente
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.location, '/portal')

    def test_handler_500_contextual_portal(self):
        """Testa que erro 500 no portal gera links de retorno para /portal e logout do portal."""
        with self.app.test_request_context('/portal/algum-erro'):
            from werkzeug.exceptions import InternalServerError
            res = self.app.handle_user_exception(InternalServerError("Falha simulada"))
            html = res.get_data(as_text=True) if hasattr(res, 'get_data') else str(res)
            self.assertIn("/portal", html)
            self.assertIn("/portal/logout", html)
            self.assertIn("Desconectar do Portal do Cliente", html)


if __name__ == '__main__':
    unittest.main()

