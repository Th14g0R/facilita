import os
import sys
import traceback

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

try:
    from app import app
except Exception as _e:
    _init_trace = traceback.format_exc()

    def app(environ, start_response):
        status = '500 Internal Server Error'
        headers = [('Content-Type', 'text/html; charset=utf-8')]
        start_response(status, headers)
        html = f"""
        <!DOCTYPE html>
        <html lang="pt-BR">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Instabilidade na Inicialização - Facilita</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; margin: 0; }}
                .card {{ max-width: 800px; margin: 0 auto; background: #1e293b; border: 1px solid #ef4444; border-radius: 10px; padding: 2rem; }}
                h1 {{ color: #ef4444; margin-top: 0; font-size: 1.5rem; }}
                pre {{ background: #0b1120; color: #fca5a5; padding: 1rem; border-radius: 6px; overflow: auto; font-size: 0.9rem; }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1>Instabilidade na Inicialização na Nuvem</h1>
                <p>O servidor encontrou o seguinte detalhe durante o carregamento dos módulos:</p>
                <pre>{_init_trace}</pre>
            </div>
        </body>
        </html>
        """
        return [html.encode('utf-8')]

handler = app
