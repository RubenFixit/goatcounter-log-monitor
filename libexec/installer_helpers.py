#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import sys

mode = sys.argv.pop(1)
if mode == 'normalize-site':
    import sys
    from urllib.parse import urlsplit, urlunsplit
    u = urlsplit(sys.argv[1])
    if (u.scheme != 'https' or not u.hostname or u.username or u.password
        or u.query or u.fragment or any(ord(c) <= 32 for c in sys.argv[1])
        or '..' in u.path.split('/') or u.path.rstrip('/').endswith('/count')):
        raise SystemExit('Use the HTTPS site base URL, without /count, credentials, query, or fragment.')
    print(urlunsplit((u.scheme, u.netloc, u.path.rstrip('/'), '', '')))
elif mode == 'release':
    import json, re, sys
    from urllib.parse import urlsplit
    release = json.load(open(sys.argv[1]))
    tag = release['tag_name']
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise SystemExit('Unexpected release version.')
    name = f'goatcounter-{tag}-linux-{sys.argv[2]}.gz'
    asset = next((a for a in release['assets'] if a['name'] == name), None)
    if not asset:
        raise SystemExit(f'No release asset named {name}.')
    url = asset['browser_download_url']
    expected = f'https://github.com/arp242/goatcounter/releases/download/{tag}/{name}'
    if url != expected:
        raise SystemExit('Unexpected release download URL.')
    digest = asset.get('digest') or ''
    # Older GitHub assets may not expose digest metadata. These are the published
    # checksums for the current stable release, not a reason to skip verification.
    known = {
        ('v2.7.0', 'amd64'): '98d221cb9c8ef2bf76d8daa9cca647839f8d8b0bb5bc7400ff9337c5da834511',
        ('v2.7.0', 'arm64'): 'ff5b2670b858bbe48802dfdc74130b6dcde2de9f5c1229b838eb9132769307dd',
    }
    digest = digest.removeprefix('sha256:') if digest.startswith('sha256:') else known.get((tag, sys.argv[2]), '')
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise SystemExit('No trusted SHA-256 available for this release; refusing an unverified install.')
    print(tag, url, digest, sep='\n')
elif mode == 'cron-command':
    import shlex, sys
    print('/bin/bash ' + shlex.quote(sys.argv[1]) + ' watch ' + shlex.quote(sys.argv[2]))
elif mode == 'cli-version-state':
    import re
    target = re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)', sys.argv[1])
    current = re.search(r'\bv(\d+)\.(\d+)\.(\d+)\b', sys.argv[2])
    if not target or not current:
        print('unknown')
    else:
        target = tuple(map(int, target.groups()))
        current = tuple(map(int, current.groups()))
        print('same' if current == target else 'newer' if current > target else 'older')
else:
    raise SystemExit('Unknown installer helper command')
