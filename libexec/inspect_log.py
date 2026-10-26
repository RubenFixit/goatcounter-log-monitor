#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only log diagnostics, with no real API token or submissions."""
import argparse
import gzip
import os
from pathlib import Path
import shutil
import sys
import tempfile

from inspection import inspect_log

state, monitor, configured_file, format_name, binary = sys.argv[1:6]
separator = sys.argv.index('--', 6)
configured_args = sys.argv[6:separator]
parser = argparse.ArgumentParser(description='Inspect log parsing locally without sending records to GoatCounter.')
parser.add_argument('--file', help='A plain or gzip log to inspect, instead of the active configured log.')
args = parser.parse_args(sys.argv[separator+1:])
source = Path(os.path.expanduser(args.file or configured_file))
if not source.is_file():
    raise SystemExit('The chosen log is not an accessible regular file.')
state = Path(state)
state.mkdir(parents=True, exist_ok=True, mode=0o700)
print(f'Monitor: {monitor}\nFile: {source}\nConfigured format: {format_name}', flush=True)
print('Read-only inspection: CLI records go to a temporary local API and are discarded; the real token/site and batch receipts are not used.', flush=True)
with tempfile.TemporaryDirectory(prefix='.inspect-', dir=state) as temp:
    snapshot = Path(temp)/'snapshot.log'
    if source.name.endswith('.gz'):
        with gzip.open(source, 'rb') as src, open(snapshot, 'wb') as dst:
            shutil.copyfileobj(src, dst)
    else:
        with open(source, 'rb') as src, open(snapshot, 'wb') as dst:
            remaining = os.fstat(src.fileno()).st_size
            while remaining:
                chunk = src.read(min(1024*1024, remaining))
                if not chunk:
                    break
                dst.write(chunk)
                remaining -= len(chunk)
    content = snapshot.read_bytes()
    if content and not content.endswith(b'\n'):
        content = content[:content.rfind(b'\n')+1]
        snapshot.write_bytes(content)
        print('Ignored an incomplete final line.')
    print(f'Snapshot: {len(content)} bytes; {content.count(bytes([10]))} complete lines', flush=True)
    format_args = [arg for arg in configured_args if arg.startswith(('-format=', '-datetime='))]
    stages = [
        # Use a never-matching pattern: some releases reject an empty exclude.
        ('Format only (no exclusions)', ['import', '-silent', *format_args, '-exclude=path:re:a^']),
        ('GET requests only', ['import', '-silent', *format_args, '-exclude=!method:GET']),
        ('HTTP 200 only', ['import', '-silent', *format_args, '-exclude=!status:200']),
        ('Configured import settings', configured_args),
    ]
    summaries = []
    for index, (label, options) in enumerate(stages):
        diagnostic = Path(temp)/f'{index}.log'
        result = inspect_log(binary, options, snapshot, diagnostic)
        summaries.append(result)
        print(f'{label}: {result["rows"]} candidate records; CLI exit {result["exit_code"]}; diagnostics {result["diagnostic_bytes"]} bytes', flush=True)
        if result['invalid_candidates']:
            print(f'  Empty/invalid parsed records: {result["invalid_candidates"]}; check format or truncated log entries.', flush=True)
        if result['exit_code'] != 0 or result['diagnostic_bytes']:
            destination = state/f'{monitor}.inspection-{index}.log'
            shutil.copyfile(diagnostic, destination)
            print(f'Private CLI diagnostics: {destination}', flush=True)
    filtered = summaries[-1]
    print(f'Eligible record dates: {filtered["first_record_at"] or "none"} to {filtered["last_record_at"] or "none"}')
    print(f'Common bot User-Agent hints among eligible records: {filtered["bot_user_agent_hints"]}/{filtered["rows"]} (heuristic, not GoatCounter\'s server-side classification).')
    if filtered['rows'] == 0:
        print('No records would reach GoatCounter with the current format/filters. No upload was performed.')
    else:
        print('The CLI can submit candidates. Dashboard visibility still depends on server-side filtering and persistence, which this local check cannot verify.')
