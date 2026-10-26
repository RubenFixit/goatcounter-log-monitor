#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stop this user's watcher identified by its open monitor lock and arguments."""
import errno
import fcntl
import os
from pathlib import Path
import signal
import sys
import time

lock_path, monitor, binary, log_file, site = sys.argv[1:]


def unlocked(lock):
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


with open(lock_path, 'a') as lock:
    if unlocked(lock):
        print(f'{monitor}: not running.')
        raise SystemExit(0)
    identity = os.fstat(lock.fileno())
    found = False
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        pidfd = None
        try:
            if process.stat().st_uid != os.getuid():
                continue
            # Pin the process while checking it when the kernel supports pidfds.
            if hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'):
                try:
                    pidfd = os.pidfd_open(int(process.name))
                except OSError as error:
                    if error.errno not in (errno.ENOSYS, errno.EINVAL):
                        raise
            held = (process/'fd'/'9').stat()
            if (held.st_dev, held.st_ino) != (identity.st_dev, identity.st_ino):
                continue
            arguments = (process/'cmdline').read_bytes().split(b'\0')
            required = [binary, 'import', '-follow', log_file, '-site='+site]
            if not all(os.fsencode(arg) in arguments for arg in required):
                continue
            if pidfd is not None:
                signal.pidfd_send_signal(pidfd, signal.SIGTERM)
            else:
                os.kill(int(process.name), signal.SIGTERM)
            found = True
            break
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        finally:
            if pidfd is not None:
                os.close(pidfd)
    if not found:
        raise SystemExit(f'{monitor}: lock is held, but no matching watcher was found. An active batch is left running.')
    deadline = time.monotonic()+10
    while not unlocked(lock):
        if time.monotonic() >= deadline:
            raise SystemExit(f'{monitor}: sent SIGTERM, but the lock is still held. Check status before starting a batch.')
        time.sleep(.1)
    print(f'{monitor}: stopped. Cron may start it again; run your batch now or disable its cron entry for a longer stop.')
