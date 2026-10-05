import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from werkzeug.security import check_password_hash, generate_password_hash
import test_local as fixture
import app as application


class PerfilEAuditoriaTest(fixture.ApplicationTests):
    def test_admin_perfil_get_e_post(self):
        # 1. Acesso à página de perfil do admin
        res = self.client.get('/perfil')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Meu Perfil', html)
        self.assertIn('Dados do Usuário', html)

        # 2. Tentar alterar sem a senha atual correta deve falhar
        post_err = self.client.post(
            '/perfil',
            data={
                'csrf_token': 'csrf-test',
                'nome': 'Admin Novo Nome',
                'senha_atual': 'senha_errada_123',
                'nova_senha': '',
                'confirmacao_senha': '',
            },
            follow_redirects=True,
        )
        self.assertEqual(post_err.status_code, 200)
        self.assertIn('Senha atual incorreta', post_err.get_data(as_text=True))

        # 3. Alterar nome e senha com sucesso informando a senha correta
        nova_senha = 'novaSenhaForte123'
        post_ok = self.client.post(
            '/perfil',
            data={
                'csrf_token': 'csrf-test',
                'nome': 'Admin Nome Atualizado',
                'senha_atual': self.password,
                'nova_senha': nova_senha,
                'confirmacao_senha': nova_senha,
            },
            follow_redirects=True,
        )
        self.assertEqual(post_ok.status_code, 200)
        self.assertIn('Perfil atualizado com sucesso', post_ok.get_data(as_text=True))

        # Verifica alteração no banco
        with self.app.app_context():
            db = application.get_db()
            user = db.execute("SELECT * FROM usuarios WHERE id = 1").fetchone()
            self.assertEqual(user['nome'], 'Admin Nome Atualizado')
            self.assertTrue(check_password_hash(user['senha_hash'], nova_senha))

    def test_portal_perfil_get_e_post(self):
        # Cria credencial de cliente para teste
        with self.app.app_context():
            db = application.get_db()
            senha_cliente = 'senhaAntiga123'
            db.execute(
                """
                INSERT INTO clientes_acessos (cliente_id, usuario, email, senha_hash, status)
                VALUES (1, 'cliente_teste', 'cliente@teste.com', ?, 'ATIVO')
                """,
                (generate_password_hash(senha_cliente),),
            )
            db.commit()
            acesso_id = db.execute("SELECT id FROM clientes_acessos WHERE usuario = 'cliente_teste'").fetchone()['id']

        # Cliente acessa o portal
        portal_client = self.app.test_client()
        self.authenticate(portal_client, portal_id=acesso_id)

        res = portal_client.get('/portal/perfil')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Meus Dados de Acesso', html)
        self.assertIn('Alterar Senha do Portal', html)

        # Alterar senha com erro de senha atual
        post_err = portal_client.post(
            '/portal/perfil',
            data={
                'csrf_token': 'csrf-test',
                'senha_atual': 'errada123',
                'nova_senha': 'novaSenhaCliente123',
                'confirmacao_senha': 'novaSenhaCliente123',
            },
            follow_redirects=True,
        )
        self.assertEqual(post_err.status_code, 200)
        self.assertIn('Senha atual incorreta', post_err.get_data(as_text=True))

        # Alterar senha com sucesso
        post_ok = portal_client.post(
            '/portal/perfil',
            data={
                'csrf_token': 'csrf-test',
                'senha_atual': senha_cliente,
                'nova_senha': 'novaSenhaCliente123',
                'confirmacao_senha': 'novaSenhaCliente123',
            },
            follow_redirects=True,
        )
        self.assertEqual(post_ok.status_code, 200)
        self.assertIn('Senha de acesso atualizada com sucesso', post_ok.get_data(as_text=True))

        with self.app.app_context():
            db = application.get_db()
            acesso = db.execute("SELECT * FROM clientes_acessos WHERE id = ?", (acesso_id,)).fetchone()
            self.assertTrue(check_password_hash(acesso['senha_hash'], 'novaSenhaCliente123'))

    def test_auditoria_renderizacao_e_paginacao(self):
        res = self.client.get('/auditoria')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Histórico de Operações', html)
        self.assertIn('Exibir:', html)
        self.assertIn('btn-filter-icon', html)

        # Testa com parâmetro de busca
        res_search = self.client.get('/auditoria?q=admin')
        self.assertEqual(res_search.status_code, 200)

        # Testa com per_page customizado
        res_pp = self.client.get('/auditoria?per_page=20')
        self.assertEqual(res_pp.status_code, 200)
        self.assertIn('per_page=20', res_pp.get_data(as_text=True))
        self.assertIn('selected', res_pp.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
