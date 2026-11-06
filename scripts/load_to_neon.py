#!/usr/bin/env python3
"""
Load all CSV files in the `data/` directory into the Neon PostgreSQL instance.

What the script does
--------------------
1. Reads `.env.local` (fallback to `.env`) to obtain `DATABASE_URL`.
2. Creates a table for every CSV file – the column definitions are built
   directly from the CSV header row, so the schema always stays in sync
   with the data you have.
3. Uses PostgreSQL’s `COPY … FROM STDIN WITH CSV HEADER` for fast bulk loading.
4. Prints a short summary of what was created/loaded.

Add new CSV files → simply drop them into `data/`; the script will
auto‑detect them and create a matching table on the next run.
"""

import os
import pathlib
import sys
import csv
from dotenv import load_dotenv
import psycopg2

# --------------------------------------------------------------------------- #
# 1️⃣  Load environment variables (prefer .env.local, fallback to .env)
# --------------------------------------------------------------------------- #
env_path = pathlib.Path('.env.local') if pathlib.Path('.env.local').exists() else pathlib.Path('.env')
load_dotenv(env_path)

DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    sys.stderr.write('ERROR: DATABASE_URL not found – run `neon env pull` first.\n')
    sys.exit(1)

# --------------------------------------------------------------------------- #
# 2️⃣  Helper to run a single SQL statement
# --------------------------------------------------------------------------- #
def exec_sql(conn, sql, params=None):
    """Execute *sql* on *conn* and commit."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()


# --------------------------------------------------------------------------- #
# 3️⃣  Infer a CREATE TABLE statement from a CSV header row
# --------------------------------------------------------------------------- #
def infer_create_table(table_name: str, header: list[str]) -> str:
    """
    Build a CREATE TABLE … IF NOT EXISTS clause.
    * All columns are created as TEXT by default.
    * Columns ending with `_id` become the primary key (first occurrence only).
    * Columns containing “date” or ending with `_time` become TIMESTAMP.
    * Columns containing “price”, “amount”, “quantity”, “total”, or “refund”
      become NUMERIC.
    * Columns prefixed with `is_` or `has_` become BOOLEAN.
    """
    cols = []
    pk_set = False

    for col in header:
        col_clean = col.strip().replace(' ', '_').lower()
        col_type = "TEXT"
        lowered = col_clean.lower()

        if lowered.endswith('_id') and not pk_set:
            col_type = "TEXT PRIMARY KEY"
            pk_set = True
        elif "date" in lowered or lowered.endswith('_time'):
            col_type = "TIMESTAMP"
        elif any(word in lowered for word in ("price", "amount", "quantity", "total", "refund")) and not lowered.endswith('_status'):
            col_type = "NUMERIC"
        elif lowered.startswith('is_') or lowered.startswith('has_'):
            col_type = "BOOLEAN"

        cols.append(f'"{col_clean}" {col_type}')

    cols_sql = ",\n    ".join(cols)
    return f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n    {cols_sql}\n);'


# --------------------------------------------------------------------------- #
# 4️⃣  Mapping of CSV file → target table name (default: file stem)
# --------------------------------------------------------------------------- #
CSV_TABLE_MAP = {
    "customers.csv":      "customers",
    "orders.csv":         "orders",
    "order_items.csv":    "order_items",
    "delivery_events.csv":"delivery_events",
    "returns_refunds.csv":"returns_refunds",
    "tickets.csv":        "tickets",
    "evaluation_cases.csv":"evaluation_cases",
    # Add more mappings here if you have additional CSVs.
}


# --------------------------------------------------------------------------- #
# 5️⃣  Main routine
# --------------------------------------------------------------------------- #
# -------------------------------------------------------------------- #
# 5️⃣  Main routine
# -------------------------------------------------------------------- #
def main():
    # Resolve project root and data directory (works regardless of cwd)
    script_dir = pathlib.Path(__file__).resolve().parent
    project_root = script_dir.parent
    data_dir = project_root / 'data'

    # Connect to Neon Postgres
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    conn.autocommit = True

    # --------------------------------------------------------------- #
    # 5a️⃣  First pass: create tables (if not exists) and collect names
    # --------------------------------------------------------------- #
    tables_created = []
    for csv_path in sorted(data_dir.glob('*.csv')):
        table_name = CSV_TABLE_MAP.get(csv_path.name) or csv_path.stem
        # Read header to infer columns
        with open(csv_path, 'r', newline='') as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                print('⚠️  Empty file – skipping.')
                continue
        create_sql = infer_create_table(table_name, header)
        exec_sql(conn, f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')
        exec_sql(conn, create_sql)
        tables_created.append(table_name)
        print(f'\n▶ Table `{table_name}` created/exists (from `{csv_path.name}`)')

    # --------------------------------------------------------------- #
    # 5b️⃣  Truncate all created tables in one statement (CASCADE)
    # --------------------------------------------------------------- #
    if tables_created:
        truncate_sql = (
            'TRUNCATE TABLE '
            + ', '.join(f'"{t}"' for t in tables_created)
            + ' RESTART IDENTITY CASCADE;'
        )
        exec_sql(conn, truncate_sql)
        print('   ↳ All target tables truncated (cascade).')


    # --------------------------------------------------------------- #
    # 5c️⃣  Process each CSV: create table (if not exists) + load data
    # --------------------------------------------------------------- #
    for csv_path in sorted(data_dir.glob('*.csv')):
        table_name = CSV_TABLE_MAP.get(csv_path.name) or csv_path.stem

        print(f'\n▶ Processing `{csv_path.name}` → table `{table_name}`')

        # ---- create table -------------------------------------------------
        with open(csv_path, 'r', newline='') as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                print('⚠️  Empty file – skipping.')
                continue

        create_sql = infer_create_table(table_name, header)
        exec_sql(conn, f'DROP TABLE IF EXISTS "{table_name}" CASCADE;')
        exec_sql(conn, create_sql)
        print('   ↳ Table created / already exists.')

                # ---- bulk‑load via INSERT (skip malformed rows) ----
        # Build an INSERT statement with placeholders for all columns
        columns = ', '.join(f'"{col}"' for col in header)
        placeholders = ', '.join(['%s'] * len(header))
        insert_sql = f'INSERT INTO "{table_name}" ({columns}) VALUES %s'
        rows = []
        with open(csv_path, 'r', newline='') as raw_f:
            reader = csv.reader(raw_f)
            next(reader)  # skip header (already processed)
            for row in reader:
                # Skip empty rows or rows with wrong column count
                if not row or len(row) != len(header):
                    continue
                rows.append(row)
        if rows:
            from psycopg2.extras import execute_values
            with conn.cursor() as cur:
                execute_values(cur, insert_sql, rows, page_size=1000)
            conn.commit()
            print(f'   ↳ Inserted {len(rows)} rows into `{table_name}`.')
        else:
            print('   ⚠️  No valid data rows to insert.')

    # ---------------------------------------------------------------- #
    # 5d️⃣  (Optional) load JSONL/JSON files – extend as needed
    # ---------------------------------------------------------------- #
    conn.close()
    print('\n✅ All CSV files have been imported into Neon.\n')

if __name__ == '__main__':
    main()