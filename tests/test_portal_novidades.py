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


if __name__ == '__main__':
    unittest.main()
