"""Ponto de entrada Serverless WSGI para hospedagem na Vercel."""
import os
import sys
import traceback

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    from app import app as flask_app
    app = flask_app
    application = flask_app
except Exception:
    tb = traceback.format_exc()
    print("ERRO NA INICIALIZACAO NA VERCEL:", tb)
    def error_app(environ, start_response):
        start_response('500 Internal Server Error', [('Content-Type', 'text/plain; charset=utf-8')])
        return [f"Erro na inicialização da aplicação Facilita:\n\n{tb}".encode('utf-8')]
    app = error_app
    application = error_app
