from __future__ import annotations

import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from werkzeug.security import generate_password_hash
from PIL import Image, ImageDraw

import app as application
import portal
from image_utils import processar_foto_perfil


def _gerar_foto_teste(width=180, height=180, cor=(100, 150, 200)):
    img = Image.new("RGB", (width, height), cor)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, width - 20, height - 20], fill=(240, 240, 240))
    draw.text((30, 30), "FOTO", fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestFotosELoginUnificado(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='facilita-fotos-')
        self.db_path = Path(self.tmp.name) / 'fotos_login.db'
        self.old_env = os.environ.get('EMPRESTIMO_DATABASE')
        os.environ['EMPRESTIMO_DATABASE'] = str(self.db_path)
        application.DATABASE_PATH = self.db_path
        portal.PROOFS_DIR = Path(self.tmp.name) / 'proofs'
        self.app = application.create_app()
        self.app.config.update(TESTING=True, SECRET_KEY='teste-segredo')
        self.client = self.app.test_client()

        with self.app.app_context():
            application.migrate_schema(application.get_db())
            portal.init_schema()
            db = application.get_db()
            db.execute("DELETE FROM usuarios")
            db.execute("DELETE FROM clientes_acessos")
            db.execute("DELETE FROM clientes")
            db.execute(
                "INSERT INTO usuarios (id, nome, login, senha_hash, ativo) VALUES (1, 'Admin Geral', 'admin', ?, 1)",
                (generate_password_hash('senhaAdmin123'),)
            )
            db.execute(
                "INSERT INTO clientes (id, nome, cpf, email, telefone, ativo) VALUES (1, 'Carlos Silva', '52998224725', 'carlos@example.invalid', '11999999999', 1)"
            )
            db.execute(
                """INSERT INTO clientes_acessos (id, cliente_id, usuario, email, senha_hash, status, contato_validado)
                   VALUES (1, 1, 'carlos', 'carlos@example.invalid', ?, 'ATIVO', 1)""",
                (generate_password_hash('senhaCliente123'),)
            )
            db.commit()

    def tearDown(self):
        if self.old_env is not None:
            os.environ['EMPRESTIMO_DATABASE'] = self.old_env
        else:
            os.environ.pop('EMPRESTIMO_DATABASE', None)
        self.tmp.cleanup()

    def auth_admin(self):
        with self.client.session_transaction() as sess:
            sess['csrf_token'] = 'csrf-test'
            sess['usuario_id'] = 1

    def test_administrador_edita_e_remove_propria_foto(self):
        """Item 3: Administrador pode salvar e remover sua foto em /perfil."""
        self.auth_admin()
        raw_foto = _gerar_foto_teste()
        storage = (io.BytesIO(raw_foto), 'foto_admin.jpg')

        # Upload de foto pelo administrador
        res = self.client.post(
            '/perfil',
            data={'csrf_token': 'csrf-test', 'action_foto': 'salvar_foto', 'foto': storage},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Foto de perfil atualizada com sucesso!', html)

        # Checa no banco de dados
        with self.app.app_context():
            u = application.get_db().execute("SELECT foto_perfil FROM usuarios WHERE id=1").fetchone()
            self.assertIsNotNone(u['foto_perfil'])
            self.assertTrue(u['foto_perfil'].startswith('data:image/jpeg;base64,'))

        # Acessa dashboard e confere que avatar do admin é exibido no menu
        res_dash = self.client.get('/dashboard')
        self.assertEqual(res_dash.status_code, 200)
        dash_html = res_dash.get_data(as_text=True)
        self.assertIn('user-avatar-img', dash_html)

        # Remoção da foto pelo administrador
        res_rem = self.client.post(
            '/perfil',
            data={'csrf_token': 'csrf-test', 'action_foto': 'remover_foto'},
            follow_redirects=True,
        )
        self.assertEqual(res_rem.status_code, 200)
        self.assertIn('Foto de perfil removida com sucesso.', res_rem.get_data(as_text=True))

        with self.app.app_context():
            u2 = application.get_db().execute("SELECT foto_perfil FROM usuarios WHERE id=1").fetchone()
            self.assertIsNone(u2['foto_perfil'])

    def test_administrador_edita_e_remove_foto_do_cliente_em_detalhe(self):
        """Item 1: Administrador visualiza, edita e remove foto do cliente em /clientes/<id>/foto."""
        self.auth_admin()
        raw_foto = _gerar_foto_teste(cor=(50, 180, 80))
        storage = (io.BytesIO(raw_foto), 'foto_carlos.jpg')

        # Salva foto do cliente
        res = self.client.post(
            '/clientes/1/foto',
            data={'csrf_token': 'csrf-test', 'foto': storage},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn('Foto do cliente atualizada com sucesso!', res.get_data(as_text=True))

        # Confere sincronia entre clientes e clientes_acessos
        with self.app.app_context():
            c = application.get_db().execute("SELECT foto_perfil FROM clientes WHERE id=1").fetchone()
            ca = application.get_db().execute("SELECT foto_perfil FROM clientes_acessos WHERE cliente_id=1").fetchone()
            self.assertIsNotNone(c['foto_perfil'])
            self.assertIsNotNone(ca['foto_perfil'])
            self.assertEqual(c['foto_perfil'], ca['foto_perfil'])

        # Remove foto do cliente
        res_del = self.client.post(
            '/clientes/1/foto',
            data={'csrf_token': 'csrf-test', 'action': 'remover_foto'},
            follow_redirects=True,
        )
        self.assertEqual(res_del.status_code, 200)
        self.assertIn('Foto do cliente removida com sucesso.', res_del.get_data(as_text=True))

        with self.app.app_context():
            c2 = application.get_db().execute("SELECT foto_perfil FROM clientes WHERE id=1").fetchone()
            ca2 = application.get_db().execute("SELECT foto_perfil FROM clientes_acessos WHERE cliente_id=1").fetchone()
            self.assertIsNone(c2['foto_perfil'])
            self.assertIsNone(ca2['foto_perfil'])

    def test_administrador_edita_foto_em_acessos_clientes_editar(self):
        """Item 1: Administrador edita foto do cliente em /acessos-clientes/<id>/editar."""
        self.auth_admin()
        raw_foto = _gerar_foto_teste(cor=(200, 80, 50))
        storage = (io.BytesIO(raw_foto), 'nova_foto_acesso.jpg')

        res = self.client.post(
            '/acessos-clientes/1/editar',
            data={'csrf_token': 'csrf-test', 'action_foto': 'salvar_foto', 'foto': storage},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertIn('Foto de perfil do cliente atualizada com sucesso!', res.get_data(as_text=True))

        with self.app.app_context():
            c = application.get_db().execute("SELECT foto_perfil FROM clientes WHERE id=1").fetchone()
            ca = application.get_db().execute("SELECT foto_perfil FROM clientes_acessos WHERE id=1").fetchone()
            self.assertIsNotNone(c['foto_perfil'])
            self.assertIsNotNone(ca['foto_perfil'])

    def test_miniaturas_de_fotos_em_listagens(self):
        """Item 2: Fotos em miniatura aparecem em /clientes e /acessos-clientes."""
        self.auth_admin()
        b64_foto = processar_foto_perfil(_gerar_foto_teste())
        with self.app.app_context():
            db = application.get_db()
            db.execute("UPDATE clientes SET foto_perfil=? WHERE id=1", (b64_foto,))
            db.execute("UPDATE clientes_acessos SET foto_perfil=? WHERE id=1", (b64_foto,))
            db.commit()

        # Verifica na lista de clientes
        res_clientes = self.client.get('/clientes')
        self.assertEqual(res_clientes.status_code, 200)
        html_clientes = res_clientes.get_data(as_text=True)
        self.assertIn('client-avatar-thumb', html_clientes)
        self.assertIn('Carlos Silva', html_clientes)
        self.assertIn('data:image/jpeg;base64,', html_clientes)

        # Verifica na lista de acessos
        res_acessos = self.client.get('/acessos-clientes')
        self.assertEqual(res_acessos.status_code, 200)
        html_acessos = res_acessos.get_data(as_text=True)
        self.assertIn('client-avatar-thumb', html_acessos)
        self.assertIn('Carlos Silva', html_acessos)
        self.assertIn('data:image/jpeg;base64,', html_acessos)

    def test_tela_login_unificada_com_perfil_cliente_padrao(self):
        """Itens 4, 5, 6 e 7: Tela de login unificada, cliente por padrão, eyebrow FACILITA, um só link de senha."""
        # Acesso via /login
        res_login = self.client.get('/login')
        self.assertEqual(res_login.status_code, 200)
        html_login = res_login.get_data(as_text=True)

        # Item 7: Eyebrow FACILITA
        self.assertIn('FACILITA', html_login)
        self.assertIn('Acesse sua conta', html_login)

        # Item 6: Abas de cliente e admin, com Área do Cliente ativa por padrão
        self.assertIn('Área do Cliente', html_login)
        self.assertIn('Administrador', html_login)
        self.assertIn('id="paneCliente" role="tabpanel" aria-labelledby="tabBtnCliente" class="login-tab-pane active"', html_login)

        # Item 5: Apenas um link "Esqueceu a senha?"
        self.assertIn('Esqueceu a senha?', html_login)
        self.assertEqual(html_login.count('Esqueceu a senha?'), 1)
        self.assertNotIn('Recuperar senha', html_login)

        # Item 6: Botão de solicitar acesso
        self.assertIn('Solicitar acesso', html_login)

        # Item 4: Na tela do portal também é unificada e permite alternar
        res_portal = self.client.get('/portal/login')
        self.assertEqual(res_portal.status_code, 200)
        html_portal = res_portal.get_data(as_text=True)
        self.assertIn('FACILITA', html_portal)
        self.assertIn('Área do Cliente', html_portal)
        self.assertIn('Administrador', html_portal)
        self.assertIn('id="paneCliente" role="tabpanel" aria-labelledby="tabBtnCliente" class="login-tab-pane active"', html_portal)
