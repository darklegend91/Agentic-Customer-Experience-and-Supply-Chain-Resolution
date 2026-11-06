import os, psycopg2
from dotenv import load_dotenv

load_dotenv('.env')
conn = psycopg2.connect(os.getenv('DATABASE_URL'), sslmode='require')
cur = conn.cursor()
cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public';")
for row in cur.fetchall():
    t = row[0]
    cur.execute(f"SELECT COUNT(*) FROM \"{t}\"")
    cnt = cur.fetchone()[0]
    print(t, cnt)
cur.close()
conn.close()
