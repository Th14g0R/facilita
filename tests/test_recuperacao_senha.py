"""
Testes automatizados da recuperação de senha do portal de clientes e controle de bloqueio temporário.
"""
from __future__ import annotations

import unittest
from datetime import timedelta
from werkzeug.security import check_password_hash, generate_password_hash

import app as application
from tests import test_local as fixture
from timezone_utils import agora_brasil
from email_utils import formatar_tempo_espera


class RecuperacaoSenhaTest(fixture.ApplicationTests):

    def _garantir_cliente_teste(self):
        with self.app.app_context():
            db = application.get_db()
            db.execute("DELETE FROM clientes_acessos WHERE cliente_id = 1")
            db.execute(
                """
                INSERT INTO clientes_acessos (
                    cliente_id, usuario, email, telefone_informado, senha_hash, status
                ) VALUES (
                    1, 'clienteteste', 'cliente.teste@exemplo.com', '85988887777', ?, 'ATIVO'
                )
                """,
                (generate_password_hash('senhaOriginal123'),),
            )
            db.commit()

    def test_tela_login_contem_links_de_recuperacao(self):
        """Verifica se a tela de login do portal possui o link para recuperar senha."""
        res = self.client.get('/portal/login')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Esqueceu a senha?', html)
        self.assertIn('/portal/recuperar-senha', html)

    def test_mensagem_erro_sem_bloqueio_nao_menciona_bloqueio(self):
        """Ao errar credenciais sem bloqueio ativo, a mensagem não deve falar de bloqueio temporário."""
        self._garantir_cliente_teste()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['csrf_token'] = 'csrf-test'

        res = client.post(
            '/portal/login',
            data={'csrf_token': 'csrf-test', 'login': 'clienteteste', 'senha': 'senhaIncorreta'},
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 401)
        html = res.get_data(as_text=True)
        self.assertIn('E-mail/usuário ou senha inválidos.', html)
        self.assertNotIn('Se houver bloqueio temporário', html)
        self.assertNotIn('bloqueado', html.lower())

    def test_bloqueio_apos_5_tentativas_e_exibicao_tempo_espera(self):
        """
        Ao falhar 5 vezes seguidas:
        1. A 5ª tentativa bloqueia e informa o tempo de 15 minutos.
        2. Uma nova tentativa durante o bloqueio informa exatamente o tempo de espera.
        """
        self._garantir_cliente_teste()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['csrf_token'] = 'csrf-test'

        # Falhas 1 a 4
        for _ in range(4):
            r = client.post(
                '/portal/login',
                data={'csrf_token': 'csrf-test', 'login': 'clienteteste', 'senha': 'senhaIncorreta'},
                follow_redirects=True,
            )
            self.assertEqual(r.status_code, 401)
            self.assertIn('E-mail/usuário ou senha inválidos.', r.get_data(as_text=True))

        # 5ª falha -> bloqueia por 15 minutos
        r5 = client.post(
            '/portal/login',
            data={'csrf_token': 'csrf-test', 'login': 'clienteteste', 'senha': 'senhaIncorreta'},
            follow_redirects=True,
        )
        self.assertEqual(r5.status_code, 401)
        html5 = r5.get_data(as_text=True)
        self.assertIn('Limite de 5 tentativas incorretas atingido.', html5)
        self.assertIn('temporariamente bloqueado por 15 minutos', html5)

        # 6ª tentativa durante o bloqueio -> exibe que está bloqueado e o tempo de espera
        r6 = client.post(
            '/portal/login',
            data={'csrf_token': 'csrf-test', 'login': 'clienteteste', 'senha': 'senhaIncorreta'},
            follow_redirects=True,
        )
        self.assertEqual(r6.status_code, 401)
        html6 = r6.get_data(as_text=True)
        self.assertIn('Acesso temporariamente bloqueado por excesso de tentativas.', html6)
        self.assertIn('Aguarde', html6)
        self.assertIn('minuto', html6)

    def test_tela_recuperar_senha_exibe_duas_opcoes(self):
        """Verifica a renderização da tela de recuperação de senha com as Opções 1 (E-mail) e 2 (Administrador)."""
        res = self.client.get('/portal/recuperar-senha')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Recuperar por e-mail', html)
        self.assertIn('Falar com o administrador', html)

    def test_solicitar_recuperacao_por_email_e_redefinir_senha_completo(self):
        """
        Fluxo completo de recuperação:
        1. Cliente solicita recuperação via e-mail.
        2. Token criptográfico é gerado no banco de dados.
        3. Auditoria registra a solicitação.
        4. Cliente acessa a tela de redefinição com o token.
        5. Cliente define nova senha.
        6. Senha é atualizada, falhas e bloqueios são zerados.
        7. Cliente consegue logar com a nova senha.
        """
        self._garantir_cliente_teste()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['csrf_token'] = 'csrf-test'

        # 1. Solicita recuperação informando o e-mail
        res_post = client.post(
            '/portal/recuperar-senha',
            data={'csrf_token': 'csrf-test', 'login': 'cliente.teste@exemplo.com'},
            follow_redirects=True,
        )
        self.assertEqual(res_post.status_code, 200)
        html_post = res_post.get_data(as_text=True)
        self.assertTrue(
            'Instruções enviadas' in html_post or 'Solicitação de recuperação gerada' in html_post
        )

        # 2. Verifica token gerado no banco
        with self.app.app_context():
            db = application.get_db()
            acesso = db.execute(
                "SELECT * FROM clientes_acessos WHERE email = 'cliente.teste@exemplo.com'"
            ).fetchone()
            self.assertIsNotNone(acesso['reset_token'])
            self.assertIsNotNone(acesso['reset_token_expira'])
            token = acesso['reset_token']

        # 3. Acessa a página de redefinição com o token válido
        res_redef_get = client.get(f'/portal/redefinir-senha?token={token}')
        self.assertEqual(res_redef_get.status_code, 200)
        self.assertIn('Criar nova senha', res_redef_get.get_data(as_text=True))

        # 4. Salva a nova senha
        res_redef_post = client.post(
            '/portal/redefinir-senha',
            data={
                'csrf_token': 'csrf-test',
                'token': token,
                'nova_senha': 'novaSenhaSuperSegura123',
                'confirmar_senha': 'novaSenhaSuperSegura123',
            },
            follow_redirects=False,
        )
        self.assertEqual(res_redef_post.status_code, 302)
        self.assertEqual(res_redef_post.headers['Location'], '/portal/login')

        # 5. Token é consumido/limpo no banco
        with self.app.app_context():
            db = application.get_db()
            acesso_atualizado = db.execute(
                "SELECT * FROM clientes_acessos WHERE id = ?", (acesso['id'],)
            ).fetchone()
            self.assertIsNone(acesso_atualizado['reset_token'])
            self.assertIsNone(acesso_atualizado['reset_token_expira'])
            self.assertEqual(acesso_atualizado['tentativas_falhas'], 0)
            self.assertIsNone(acesso_atualizado['bloqueado_ate'])
            self.assertTrue(
                check_password_hash(acesso_atualizado['senha_hash'], 'novaSenhaSuperSegura123')
            )

        # 6. Login com a nova senha tem sucesso
        res_login_novo = client.post(
            '/portal/login',
            data={
                'csrf_token': 'csrf-test',
                'login': 'clienteteste',
                'senha': 'novaSenhaSuperSegura123',
            },
            follow_redirects=False,
        )
        self.assertEqual(res_login_novo.status_code, 302)
        self.assertEqual(res_login_novo.headers['Location'], '/portal')

    def test_token_invalido_ou_expirado_nao_permite_redefinicao(self):
        """Verifica se token inválido ou expirado é rejeitado com segurança."""
        self._garantir_cliente_teste()
        client = self.app.test_client()

        # Token inexistente
        res_inv = client.get('/portal/redefinir-senha?token=tokenQueNaoExiste123', follow_redirects=True)
        self.assertIn('link de recuperação é inválido ou já foi utilizado', res_inv.get_data(as_text=True))

        # Token expirado
        with self.app.app_context():
            db = application.get_db()
            expirado = (agora_brasil() - timedelta(minutes=5)).isoformat(timespec='seconds')
            db.execute(
                "UPDATE clientes_acessos SET reset_token = 'token_expirado', reset_token_expira = ? WHERE cliente_id = 1",
                (expirado,),
            )
            db.commit()

        res_exp = client.get('/portal/redefinir-senha?token=token_expirado', follow_redirects=True)
        self.assertIn('link de recuperação expirou', res_exp.get_data(as_text=True))

    def test_admin_gerar_link_recuperacao_para_o_cliente(self):
        """Verifica o recurso no painel do administrador para gerar link exclusivo para o cliente."""
        self._garantir_cliente_teste()
        with self.app.app_context():
            db = application.get_db()
            aid = db.execute("SELECT id FROM clientes_acessos WHERE cliente_id = 1").fetchone()['id']

        res = self.client.post(
            f'/acessos-clientes/{aid}/gerar-link-recuperacao',
            data={'csrf_token': 'csrf-test'},
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Link de recuperação gerado com sucesso', html)
        self.assertIn('/portal/redefinir-senha?token=', html)

    def test_cadastro_cliente_ja_ativo_redireciona_para_recuperacao(self):
        """Quando um cliente já tem acesso ativo e tenta solicitar cadastro, orienta a recuperação por e-mail ou admin."""
        self._garantir_cliente_teste()
        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['csrf_token'] = 'csrf-test'

        res = client.post(
            '/portal/cadastro',
            data={
                'csrf_token': 'csrf-test',
                'cpf': '52998224725',
                'email': 'cliente.teste@exemplo.com',
                'senha': 'senha12345678',
                'confirmar_senha': 'senha12345678',
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Este cliente já possui acesso ativo', html)
        self.assertIn('recuperação de senha por e-mail ou procure o administrador', html)

    def test_formatar_tempo_espera_utilitario(self):
        """Valida a precisão da formatação amigável do tempo de espera."""
        self.assertEqual(formatar_tempo_espera(0), 'alguns instantes')
        self.assertEqual(formatar_tempo_espera(45), '45 segundos')
        self.assertEqual(formatar_tempo_espera(1), '1 segundo')
        self.assertEqual(formatar_tempo_espera(60), '1 minuto')
        self.assertEqual(formatar_tempo_espera(900), '15 minutos')
        self.assertEqual(formatar_tempo_espera(850), '15 minutos')
        self.assertEqual(formatar_tempo_espera(120), '2 minutos')


if __name__ == '__main__':
    unittest.main()
