from http.server import BaseHTTPRequestHandler
import sys
import os
import traceback

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        
        output = []
        output.append("=== DIAGNÓSTICO VERCEL PYTHON ===")
        output.append(f"Python Version: {sys.version}")
        output.append(f"Current Dir: {os.getcwd()}")
        output.append(f"Sys Path: {sys.path[:3]}")
        output.append(f"VERCEL: {os.environ.get('VERCEL')}")
        output.append(f"DATABASE_URL definida: {bool(os.environ.get('DATABASE_URL'))}")
        
        # Teste 1: Importar Flask
        try:
            import flask
            output.append(f"Flask: OK (versao {flask.__version__})")
        except Exception as e:
            output.append(f"Flask: ERRO ({e})")
            
        # Teste 2: Importar psycopg2
        try:
            import psycopg2
            output.append(f"psycopg2: OK (versao {psycopg2.__version__})")
        except Exception as e:
            output.append(f"psycopg2: ERRO ({e})")
            
        # Teste 3: Importar app
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if root_dir not in sys.path:
                sys.path.insert(0, root_dir)
            import app
            output.append("app: OK (importado com sucesso)")
            
            # Teste 4: Conectar ao banco
            with app.app.app_context():
                db = app.get_db()
                row = db.execute("SELECT 1 as teste;").fetchone()
                output.append(f"banco: OK (resposta={dict(row) if hasattr(row, 'keys') else row})")
        except Exception as e:
            output.append(f"app/banco: ERRO ->\n{traceback.format_exc()}")
            
        self.wfile.write("\n".join(output).encode('utf-8'))
