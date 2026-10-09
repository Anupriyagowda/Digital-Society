#!/usr/bin/env python3
"""
Simple SQLite CLI helper for the project — no external binaries required.
Usage:
  python sqlite_cli.py                -> interactive prompt
  python sqlite_cli.py -e "SELECT ..."  -> execute single query
  python sqlite_cli.py -f script.sql    -> execute SQL file
Default DB: digital_society.db
"""
import sqlite3
import argparse
import os
import sys

DB = os.path.join(os.path.dirname(__file__), 'digital_society.db')

parser = argparse.ArgumentParser(description='Simple SQLite CLI for project DB')
parser.add_argument('-d', '--db', default=DB, help='Path to sqlite db')
parser.add_argument('-e', '--execute', help='Execute SQL and exit')
parser.add_argument('-f', '--file', help='Execute SQL file and exit')
args = parser.parse_args()

if not os.path.exists(args.db):
    print('DB file not found:', args.db)
    sys.exit(1)

conn = sqlite3.connect(args.db)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

def run_sql(sql):
    try:
        cur.execute(sql)
        if cur.description:
            cols = [c[0] for c in cur.description]
            rows = cur.fetchall()
            # Print table-like output
            print('| ' + ' | '.join(cols) + ' |')
            print('|-' + '-|-'.join('-' * len(c) for c in cols) + '-|')
            for r in rows:
                print('| ' + ' | '.join(str(r[c]) for c in cols) + ' |')
        else:
            conn.commit()
            print('OK:', cur.rowcount)
    except Exception as e:
        print('ERROR:', e)

if args.execute:
    run_sql(args.execute)
    conn.close()
    sys.exit(0)

if args.file:
    with open(args.file, 'r', encoding='utf-8') as f:
        run_sql(f.read())
    conn.close()
    sys.exit(0)

print('Connected to', args.db)
print('Type SQL and end with ; to execute. Ctrl-D (or Ctrl-Z on Windows) to quit.')
buffer = ''
try:
    while True:
        try:
            line = input('sqlite> ')
        except EOFError:
            print('\nBye')
            break
        buffer += line + '\n'
        if ';' in line:
            run_sql(buffer)
            buffer = ''
finally:
    conn.close()
