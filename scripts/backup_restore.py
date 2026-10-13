"""Back up SoloVibe schemas and rehearse restore into an empty scratch database.

Requires matching PostgreSQL client binaries (pg_dump and pg_restore). Passwords
are passed through process environment, never command-line arguments or output.
"""
import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import config  # noqa: F401
from services.application import database_dsn

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ('solovibe_v1', 'solovibe_graph')


def client_env(dsn):
    options = conninfo_to_dict(dsn)
    env = os.environ.copy()
    names = {'host': 'PGHOST', 'port': 'PGPORT', 'user': 'PGUSER',
             'dbname': 'PGDATABASE', 'password': 'PGPASSWORD', 'sslmode': 'PGSSLMODE'}
    for name in (*names.values(), 'PGSERVICE', 'PGSERVICEFILE', 'PGOPTIONS'):
        env.pop(name, None)
    if not options.get('host') or not options.get('dbname'):
        raise RuntimeError('Database connection requires explicit host and database name')
    for source, target in names.items():
        if options.get(source):
            env[target] = str(options[source])
    return env


def tool(name):
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f'{name} is unavailable; install PostgreSQL client tools before this gate')
    return found


def run_tool(args, env):
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError(f'{Path(args[0]).name} failed (exit {result.returncode}); inspect the client and target privately')
    return result.stdout


def backup(output):
    source = database_dsn()
    target = output or (ROOT / '.runtime' / 'backups' /
        f'solovibe-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.dump')
    target = Path(target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RuntimeError('Backup target already exists; choose a new filename')
    try:
        run_tool([tool('pg_dump'), '--format=custom', '--no-owner', '--no-acl',
                  *(f'--schema={schema}' for schema in SCHEMAS), '--file', str(target)],
                 client_env(source))
        listing = run_tool([tool('pg_restore'), '--list', str(target)], os.environ.copy())
        if not all(schema in listing for schema in SCHEMAS):
            raise RuntimeError('Backup archive does not include both SoloVibe schemas')
        os.chmod(target, 0o600)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    print(f'backup_verified={target} bytes={target.stat().st_size}')


def restore_drill(archive):
    source = conninfo_to_dict(database_dsn())
    target_dsn = os.getenv('SOLOVIBE_RESTORE_DSN', '').strip()
    if not target_dsn:
        raise RuntimeError('Set SOLOVIBE_RESTORE_DSN to a separate empty scratch database')
    target = conninfo_to_dict(target_dsn)
    if not target.get('host') or not target.get('dbname'):
        raise RuntimeError('Scratch database requires explicit host and database name')
    identity = lambda item: (item.get('host'), item.get('port', '5432'), item.get('dbname'))
    if identity(source) == identity(target):
        raise RuntimeError('Restore target matches the live database')
    archive = Path(archive).resolve()
    if not archive.is_file():
        raise RuntimeError('Backup archive does not exist')
    with psycopg.connect(target_dsn, connect_timeout=8) as conn:
        present = conn.execute('''SELECT count(*) FROM information_schema.tables
            WHERE table_schema IN ('solovibe_v1', 'solovibe_graph')''').fetchone()[0]
        if present:
            raise RuntimeError('Scratch database already contains SoloVibe tables')
    run_tool([tool('pg_restore'), '--exit-on-error', '--single-transaction',
              '--no-owner', '--no-acl', '--dbname', target.get('dbname', ''),
              str(archive)], client_env(target_dsn))
    with psycopg.connect(target_dsn, connect_timeout=8) as conn:
        rows = conn.execute('''SELECT to_regclass('solovibe_v1.conversations'),
            to_regclass('solovibe_v1.runs'), to_regclass('solovibe_graph.checkpoints')''').fetchone()
        if not all(rows):
            raise RuntimeError('Restore completed without required business and checkpoint tables')
    print('restore_drill_verified=true; scratch database retained for inspection')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('backup').add_argument('--output', type=Path)
    commands.add_parser('restore-drill').add_argument('--archive', required=True, type=Path)
    args = parser.parse_args()
    try:
        backup(args.output) if args.command == 'backup' else restore_drill(args.archive)
    except Exception as exc:
        print(f'backup_or_restore_failed={type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
