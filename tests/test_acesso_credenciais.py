import io
import unittest
from werkzeug.security import generate_password_hash
import test_local as fixture
import app as application


class AcessoCredenciaisTest(fixture.ApplicationTests):
    def test_criar_credencial_admin_e_login_com_usuario_e_email(self):
        # 1. Admin acessa a tela de novo acesso
        get_res = self.client.get('/acessos-clientes/novo?cliente_id=1')
        self.assertEqual(get_res.status_code, 200)
        self.assertIn('Nova credencial de cliente', get_res.get_data(as_text=True))

        # 2. Admin cria credencial com usuário 'joaosilva'
        post_data = {
            'csrf_token': 'csrf-test',
            'cliente_id': '1',
            'usuario': 'joaosilva',
            'email': 'joao.silva@exemplo.com',
            'telefone': '11999998888',
            'status': 'ATIVO',
            'senha': 'senhaCliente123',
            'confirmar_senha': 'senhaCliente123',
            'observacao_admin': 'Acesso criado diretamente pelo admin',
            'senha_confirmacao': self.password,
        }
        res = self.client.post('/acessos-clientes/novo', data=post_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn('Credencial de acesso criada com sucesso', res.get_data(as_text=True))

        # Verifica persistência no banco
        with self.app.app_context():
            db = application.get_db()
            acesso = db.execute("SELECT * FROM clientes_acessos WHERE cliente_id = 1").fetchone()
            self.assertIsNotNone(acesso)
            self.assertEqual(acesso['usuario'], 'joaosilva')
            self.assertEqual(acesso['email'], 'joao.silva@exemplo.com')
            self.assertEqual(acesso['status'], 'ATIVO')

        # 3. Cliente faz login usando o NOME DE USUÁRIO
        client_user = self.app.test_client()
        with client_user.session_transaction() as sess:
            sess['csrf_token'] = 'csrf-test'

        login_res_user = client_user.post(
            '/portal/login',
            data={'csrf_token': 'csrf-test', 'login': 'joaosilva', 'senha': 'senhaCliente123'},
            follow_redirects=False,
        )
        self.assertEqual(login_res_user.status_code, 302)
        self.assertEqual(login_res_user.headers['Location'], '/portal')

        # 4. Cliente faz login usando o E-MAIL
        client_email = self.app.test_client()
        with client_email.session_transaction() as sess:
            sess['csrf_token'] = 'csrf-test'

        login_res_email = client_email.post(
            '/portal/login',
            data={'csrf_token': 'csrf-test', 'login': 'joao.silva@exemplo.com', 'senha': 'senhaCliente123'},
            follow_redirects=False,
        )
        self.assertEqual(login_res_email.status_code, 302)
        self.assertEqual(login_res_email.headers['Location'], '/portal')

        # 5. Cliente tenta login com senha incorreta
        client_fail = self.app.test_client()
        with client_fail.session_transaction() as sess:
            sess['csrf_token'] = 'csrf-test'

        fail_res = client_fail.post(
            '/portal/login',
            data={'csrf_token': 'csrf-test', 'login': 'joaosilva', 'senha': 'senhaErrada'},
            follow_redirects=False,
        )
        self.assertEqual(fail_res.status_code, 401)

    def test_editar_credencial_alterando_usuario(self):
        with self.app.app_context():
            db = application.get_db()
            db.execute(
                "INSERT INTO clientes_acessos (cliente_id, usuario, email, senha_hash, status) VALUES (1, 'useroriginal', 'orig@exemplo.com', ?, 'ATIVO')",
                (generate_password_hash('senha12345'),),
            )
            db.commit()
            aid = db.execute("SELECT id FROM clientes_acessos WHERE cliente_id = 1").fetchone()['id']

        edit_data = {
            'csrf_token': 'csrf-test',
            'usuario': 'usermodificado',
            'email': 'orig@exemplo.com',
            'telefone': '',
            'status': 'ATIVO',
            'observacao_admin': '',
            'nova_senha': '',
            'confirmar_nova_senha': '',
            'senha_confirmacao': self.password,
        }
        res = self.client.post(f'/acessos-clientes/{aid}/editar', data=edit_data, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # Login agora funciona com o novo nome de usuário
        client_mod = self.app.test_client()
        with client_mod.session_transaction() as sess:
            sess['csrf_token'] = 'csrf-test'

        login_res = client_mod.post(
            '/portal/login',
            data={'csrf_token': 'csrf-test', 'login': 'usermodificado', 'senha': 'senha12345'},
            follow_redirects=False,
        )
        self.assertEqual(login_res.status_code, 302)

    def test_clientes_lista_e_detalhe_e_edicao(self):
        # 1. Acesso à listagem de clientes
        res_lista = self.client.get('/clientes')
        self.assertEqual(res_lista.status_code, 200)
        html_lista = res_lista.get_data(as_text=True)
        self.assertIn('Usuário Portal', html_lista)
        self.assertIn('Acesso recente', html_lista)

        # 2. Acesso aos detalhes do cliente 1
        res_detalhe = self.client.get('/clientes/1')
        self.assertEqual(res_detalhe.status_code, 200)
        html_detalhe = res_detalhe.get_data(as_text=True)
        self.assertIn('Editar cliente', html_detalhe)
        self.assertIn('Acesso ao Portal', html_detalhe)

        # 3. Acesso à edição do cliente 1
        res_edit_get = self.client.get('/clientes/1/editar')
        self.assertEqual(res_edit_get.status_code, 200)
        self.assertIn('Editar cliente', res_edit_get.get_data(as_text=True))

        # 4. Salvar edição do cliente
        edit_form = {
            'csrf_token': 'csrf-test',
            'nome': 'Cliente Nome Alterado',
            'cpf': '52998224725',
            'telefone': '85988887777',
            'email': 'alterado@example.com',
            'endereco': 'Rua Teste 123',
            'cidade': 'Fortaleza',
            'estado': 'CE',
            'cep': '60000000',
            'observacoes': 'Observação teste',
        }
        res_edit_post = self.client.post('/clientes/1/editar', data=edit_form, follow_redirects=True)
        self.assertEqual(res_edit_post.status_code, 200)
        self.assertIn('Cliente atualizado com sucesso', res_edit_post.get_data(as_text=True))
        self.assertIn('Cliente Nome Alterado', res_edit_post.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
