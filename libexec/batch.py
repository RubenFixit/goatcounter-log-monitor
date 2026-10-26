#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import argparse
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

state, monitor, active, site, binary = sys.argv[1:6]
separator = sys.argv.index('--', 6)
cli_args = sys.argv[6:separator]
parser = argparse.ArgumentParser(description='Pass rotated logs, and optionally the current log, to the GoatCounter CLI.')
parser.add_argument('--dry-run', action='store_true', help='Preview selections without uploading or writing receipts.')
parser.add_argument('--yes', action='store_true', help='Confirm upload without prompting (does not bypass receipts).')
parser.add_argument('--include-current', action='store_true', help='Also import a bounded snapshot of the configured current access log, after archives. Date bounds apply only to archives.')
parser.add_argument('--from', dest='start', type=dt.date.fromisoformat, metavar='YYYY-MM-DD', help='Include dated archives on/after this date.')
parser.add_argument('--before', type=dt.date.fromisoformat, metavar='YYYY-MM-DD', help='Include dated archives strictly before this date.')
args = parser.parse_args(sys.argv[separator+1:])
if args.start and args.before and args.start >= args.before:
    parser.error('--from must precede --before')

state = Path(state)
active = Path(active)
if not active.is_absolute() or not active.parent.is_dir():
    raise SystemExit('The configured log directory is unavailable.')
# The ledger is shared across monitors targeting the same site and CLI arguments.
# Different binary paths do not create a fresh duplicate-import scope.
scope = hashlib.sha256(json.dumps([site, cli_args], separators=(',', ':')).encode()).hexdigest()
receipt_dir = state / 'batches' / scope
receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
scope_lock = open(receipt_dir / 'lock', 'a')
try:
    fcntl.flock(scope_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('Another batch for this site and CLI configuration is running.')
ledger_file = receipt_dir / 'receipts.json'
ledger = json.loads(ledger_file.read_text()) if ledger_file.exists() else {}

def save_ledger():
    fd, name = tempfile.mkstemp(prefix='.receipts-', dir=receipt_dir)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(ledger, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, ledger_file)
    finally:
        if os.path.exists(name):
            os.unlink(name)

pattern = re.compile(re.escape(active.name) + r'\.(?:(?P<date>\d{4}-\d{2}-\d{2})|(?P<number>\d+))(?P<gzip>\.gz)?$')
candidates = []
for p in active.parent.iterdir():
    match = pattern.fullmatch(p.name)
    # Skip aliases such as DreamHost's access.log.0 symlink entirely, as well
    # as error.log, unrelated reports/directories, and the active file itself.
    if not match or p.is_symlink() or not p.is_file():
        continue
    date_text = match.group('date')
    archive_date = dt.date.fromisoformat(date_text) if date_text else None
    if (args.start or args.before) and archive_date is None:
        print(f'Skipping undated numbered archive with date filters: {p.name}')
        continue
    if args.start and archive_date < args.start:
        continue
    if args.before and archive_date >= args.before:
        continue
    order = (archive_date.toordinal(), 0) if archive_date else (dt.datetime.fromtimestamp(p.stat().st_mtime).date().toordinal(), -int(match.group('number')))
    candidates.append((order, p))
if args.include_current:
    if not active.is_file() or active.is_symlink():
        raise SystemExit('The current access log must be an accessible regular file, not a symlink.')
    candidates.append(((dt.date.max.toordinal(), 0), active))
candidates.sort(key=lambda pair: (pair[0], pair[1].name))
if not candidates:
    print('No matching logs. Use --include-current to also import the current access log.')
    raise SystemExit(0)

print(f'Monitor: {monitor}\nDestination: {site}\nCurrent log {"included" if args.include_current else "excluded"}: {active.name}')
if args.include_current:
    print('The current log is snapshotted once. Reimporting it after it grows, or later importing its rotated copy, can duplicate earlier records. Date bounds apply only to archives.')
started = state / f'{monitor}.watch-started'
if started.exists():
    print('This monitor has run in live mode since at least ' + started.read_text().strip())
print('Receipts cannot recognize earlier JavaScript submissions, live-watcher traffic, or imports made outside this batch command.')
print('Receipts are scoped to the destination and CLI arguments; changing those settings does not skip earlier imports.')
print('Use --before to keep a backfill separate from dates already collected. Date bounds select archive filenames, not individual log timestamps.')

with tempfile.TemporaryDirectory(prefix='.batch-', dir=state) as temp:
    pending = []
    seen = set()
    # Snapshot every selected file BEFORE uploading anything.
    # Gzip is decoded here so plain/gzip copies receive the same content hash.
    for _, source in candidates:
        snapshot = Path(temp) / f'{len(pending)}.log'
        is_current = source == active
        digest = hashlib.sha256()
        opener = gzip.open if source.name.endswith('.gz') else open
        try:
            with opener(source, 'rb') as src, open(snapshot, 'wb') as dst:
                before = os.fstat(src.fileno())
                remaining = before.st_size if is_current else None
                while True:
                    if remaining == 0:
                        break
                    chunk = src.read(min(1024 * 1024, remaining) if remaining is not None else 1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    dst.write(chunk)
                    if remaining is not None:
                        remaining -= len(chunk)
        except (OSError, EOFError) as e:
            raise SystemExit(f'Cannot snapshot {source.name}: {e}. Nothing from this batch was uploaded.')
        after = source.stat()
        changed = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if is_current:
            changed = (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or after.st_size < before.st_size or remaining != 0
        if changed:
            raise SystemExit(f'{source.name} changed while being read; no uploads performed. Retry after rotation finishes.')
        identity = digest.hexdigest()
        if snapshot.stat().st_size == 0:
            print(f'Skipping empty archive: {source.name}')
            continue
        if identity in seen:
            print(f'Skipping duplicate plain/gzip/content copy: {source.name}')
            continue
        seen.add(identity)
        # Dated archives should be immutable. A changed payload under the same
        # dated name may contain already-uploaded lines plus new lines.
        logical_source = str(source)[:-3] if source.name.endswith('.gz') else str(source)
        if not is_current and pattern.fullmatch(source.name).group('date'):
            for prior_hash, prior in ledger.items():
                prior_source = prior.get('logical_source', prior.get('source', ''))
                if prior_source.endswith('.gz'):
                    prior_source = prior_source[:-3]
                if prior_source == logical_source and prior_hash != identity:
                    raise SystemExit(f'Dated archive {source.name} changed since a previous import attempt; refusing to replay potentially overlapping data. Review {ledger_file}.')
        previous = ledger.get(identity)
        if previous and previous['status'] == 'complete':
            print(f'Already imported: {source.name}')
            continue
        if previous:
            raise SystemExit(f'Previous import of {source.name} is {previous["status"]}; refusing automatic retry because some hits may already exist. Review {ledger_file}.')
        print(f'Will import: {source.name} ({snapshot.stat().st_size} uncompressed bytes)')
        pending.append((source, snapshot, identity))
    if not pending:
        print('Nothing new to upload.')
        raise SystemExit(0)
    if args.dry_run:
        print(f'Dry run: {len(pending)} unique files; no uploads and no receipts written.')
        raise SystemExit(0)
    if not args.yes:
        # Use the terminal for explicit upload confirmation, including when
        # stdin belongs to a caller or a pipeline.
        try:
            with open('/dev/tty', 'r') as reader, open('/dev/tty', 'w') as writer:
                writer.write(f'Type IMPORT to upload {len(pending)} files to {site}: ')
                writer.flush()
                confirmation = reader.readline().strip()
        except OSError:
            raise SystemExit('Interactive confirmation requires a terminal; use --dry-run or explicitly pass --yes.')
        if confirmation != 'IMPORT':
            print('Cancelled; nothing uploaded.')
            raise SystemExit(0)
    for source, snapshot, identity in pending:
        record = {'status': 'in-progress', 'source': str(source), 'site': site,
                  'sha256': identity, 'started_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        record['logical_source'] = str(source)[:-3] if source.name.endswith('.gz') else str(source)
        ledger[identity] = record
        save_ledger()
        print(f'Importing {source.name}...', flush=True)
        # Let GoatCounter report parsing and submission results directly.
        try:
            code = subprocess.run([binary, *cli_args, str(snapshot)]).returncode
        except OSError as e:
            print(f'Cannot run GoatCounter: {e}', file=sys.stderr)
            code = 1
        if code != 0:
            record.update(status='uncertain', exit_code=code)
            save_ledger()
            print(f'GoatCounter exited {code} for {source.name}. Some hits may have been uploaded. Stopped; review the CLI output before retrying.', file=sys.stderr)
            raise SystemExit(code if code > 0 else 1)
        record.update(status='complete', exit_code=0,
                      completed_at=dt.datetime.now(dt.timezone.utc).isoformat())
        save_ledger()
        print(f'GoatCounter CLI exited 0: {source.name}. Check its output for rejected records.', flush=True)
    print(f'Batch CLI runs finished: {len(pending)} files; dashboard receipt was not verified. Keep receipts at {ledger_file} to prevent repeat submissions.')
