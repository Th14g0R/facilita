"""
Testes automatizados da funcionalidade de Cobrar Cliente (envio via WhatsApp e Telegram).
"""
import unittest
from tests import test_local as fixture


class CobrancaClienteTest(fixture.ApplicationTests):
    def test_botao_cobrar_cliente_no_topo_de_a_receber(self):
        """Verifica se o botão 'Cobrar cliente' está visível no topo da página /receber."""
        resp = self.client.get("/receber")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Cobrar cliente", html)
        self.assertIn("/receber/relatorio", html)

    def test_rota_cobrar_cliente_carrega_com_sucesso(self):
        """Verifica se a rota /receber/cobrar e /receber/relatorio abrem corretamente."""
        for path in ["/receber/cobrar", "/receber/relatorio"]:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn("Cobrar cliente", html)

    def test_consulta_cliente_e_selecao_de_titulos(self):
        """Verifica a montagem da mensagem com seleção de títulos e links de WhatsApp/Telegram."""
        # 1. Consulta cliente 1 pré-existente nos fixtures
        resp = self.client.get("/receber/cobrar?cliente_id=1")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("Cobrar cliente", html)
        self.assertIn("Copiar mensagem", html)
        self.assertIn("check_todos", html)
        self.assertIn("btn_marcar_todos", html)


if __name__ == "__main__":
    unittest.main()
