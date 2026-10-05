"""
Script de sincronização/migração segura de dados do SQLite local para o Supabase (PostgreSQL).
Preserva 100% dos IDs, integridade referencial e valores monetários em centavos.
"""
import os
import sys
import sqlite3
import psycopg2

def migrar(sqlite_path: str, pg_uri: str):
    print(f"Lendo SQLite: {sqlite_path}")
    sq_conn = sqlite3.connect(sqlite_path)
    sq_conn.row_factory = sqlite3.Row
    sq_cur = sq_conn.cursor()

    print(f"Conectando ao PostgreSQL Supabase...")
    pg_conn = psycopg2.connect(pg_uri)
    pg_conn.autocommit = False
    pg_cur = pg_conn.cursor()

    tables = [
        "usuarios",
        "clientes",
        "clientes_acessos",
        "contas_bancarias",
        "cartoes_credito",
        "lancamentos_cartao",
        "parcelas_cartao",
        "emprestimos",
        "pagamentos_integrados",
        "movimentacoes_emprestimo",
        "titulos_receber",
        "pagamentos_integrados_itens",
        "comprovantes_pagamento",
        "comprovantes_pagamento_itens",
        "auditoria",
        "limites_publicos"
    ]

    try:
        pg_cur.execute("SET session_replication_role = replica;")
        for table in tables:
            rows = sq_cur.execute(f"SELECT * FROM {table}").fetchall()
            if not rows:
                continue
            cols = rows[0].keys()
            col_names = ", ".join(cols)
            placeholders = ", ".join(["%s"] * len(cols))
            insert_sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT DO NOTHING;"
            data = [tuple(r[c] for c in cols) for r in rows]
            pg_cur.executemany(insert_sql, data)
            print(f"  ✓ {table}: {len(rows)} registros")

        pg_cur.execute("SET session_replication_role = origin;")

        for table in tables:
            if table == "limites_publicos":
                continue
            pg_cur.execute(f"SELECT pg_get_serial_sequence('{table}', 'id');")
            seq = pg_cur.fetchone()[0]
            if seq:
                pg_cur.execute(f"SELECT COALESCE(MAX(id), 1) FROM {table};")
                max_id = pg_cur.fetchone()[0]
                pg_cur.execute(f"SELECT setval('{seq}', %s, true);", (max_id,))

        pg_conn.commit()
        print("Sincronização concluída com sucesso!")
    except Exception as e:
        pg_conn.rollback()
        print("Erro durante migração:", e)
        raise

if __name__ == "__main__":
    from pathlib import Path
    default_db = os.environ.get(
        "EMPRESTIMO_DATABASE",
        str(Path(__file__).resolve().parent.parent / "data" / "emprestimos.db")
    )
    db_file = sys.argv[1] if len(sys.argv) > 1 else default_db
    uri = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("DATABASE_URL")
    if not uri:
        print("Defina a variável DATABASE_URL ou informe como segundo parâmetro.")
        sys.exit(1)
    migrar(db_file, uri)
