# GoatCounter log monitor

A small per-user Linux utility for importing access logs into an existing GoatCounter site. An interactive installer installs the official CLI, checks a hidden API token, configures named monitors, and helps set up cron. The monitor supports live watching and explicit one-time batches of rotated plain/gzip archives.

The installer, runtime, Python helpers, and tests are ordinary repository files. No script writes or embeds another script. Installation creates a launcher symlink pointing at the shipped monitor entry point.

## Install

Run as your hosting shell user, without `sudo`:

```bash
mkdir -p "$HOME/.local/share"
git clone https://github.com/RubenFixit/goatcounter-log-monitor.git \
  "$HOME/.local/share/goatcounter-log-monitor"
bash "$HOME/.local/share/goatcounter-log-monitor/install.sh"
```

Keep the clone in place: the installed launcher points to it. Default executables are `~/.local/bin/goatcounter` and `~/.local/bin/goatcounter-log-monitor`. No database, Go compiler, or GoatCounter server is needed.

Requirements: Linux x86_64 or ARM64; Bash 4+; Python 3.9+; Git; curl 7.55+; gzip; sha256sum; flock; and standard GNU/Linux file utilities. Ubuntu VPS hosting normally provides these. No third-party Python packages are required.

The wizard prompts for an executable directory, monitor name, GoatCounter HTTPS base URL, hidden API token, readable log-file path, and log format. It can configure multiple monitors for different logs or sites. The base URL must omit `/count`. Each monitor tails one file; configure HTTP and HTTPS separately if you need both.

Create the analytics site beforehand. Give the API token **Record pageviews** permission and access to that site; none of the statistics/export/site-management permissions are needed. The installer verifies authorization through `/api/v0/test` without recording a fake pageview. It does not test the log's syntax or create a site.

Use a separate analytics site for log imports if JavaScript tracking remains enabled. Mixing both methods over overlapping dates can inflate counts.

## Update: installer only

The monitor has **no `update` or `self-update` command**. All updates are managed by the installer:

```bash
# Check/update the installer and shared utility code, then the official CLI.
bash "$HOME/.local/share/goatcounter-log-monitor/install.sh" update

# Update installer/monitor/helper files without touching the GoatCounter CLI.
bash "$HOME/.local/share/goatcounter-log-monitor/install.sh" update --monitor-only
```

Rerunning `install.sh` without arguments performs the same checks, detects existing monitors, and offers to add another monitor after updating. It does not force you to recreate monitor configurations or re-enter their keys. The previous executable directory is remembered; keep it when updating an existing installation.

The installer checks the configured official origin's `main` branch, shows the available utility version and commit, and asks before applying it. It only fast-forwards a clean `main` checkout; local changes, unexpected remotes, detached/other branches, and divergent history are left untouched with an explanation. If the installer source changes, it restarts the updated `install.sh` once and continues with the original update options. All source files come from the same Git checkout. Updates follow `origin/main`, not release tags.

The official GoatCounter CLI is checked separately against upstream stable-release metadata. It is replaced only after approval when the version differs; an already-current or newer CLI is left alone. Downloads are SHA-256 verified using GitHub asset digests, with published v2.7.0 hashes as a fallback for older asset metadata. A new executable is staged and renamed into place instead of truncating a running binary. If a release check fails, the installer can keep an existing CLI.

Private settings, API keys, batch receipts, and cron jobs are preserved. Updating utility files does not interrupt active imports. A running watcher continues using its existing process until restarted; configuration changes likewise take effect on restart. Restart deliberately, because the watcher does not recover requests missed during a stop. `--skip-update-check` skips the utility Git check for an intentional offline/development run; it does not disable CLI checks unless combined with `update --monitor-only`.

## Migrate an earlier standalone/gist installation

Clone this repository and run `install.sh update` using the commands above. It discovers configurations already stored in `~/.config/goatcounter-log-monitor`, derives the existing executable directory, and offers to replace the old launcher with a symlink to this repository. API keys and receipts remain in their existing locations. Existing cron commands keep working when the launcher path is unchanged.

An old watcher already in progress is not killed or replaced. After the installer finishes, stop/restart that specific watcher when you are ready to use the updated runtime. Do not run duplicate monitors for the same log/site. The old gist is not an update source and need not exist for migration.

## First test and cron startup

For an initial trial, choose **manual** startup. **Run one batch before starting the watcher or enabling cron**, including today's current log:

```bash
~/.local/bin/goatcounter-log-monitor batch example-https --dry-run
~/.local/bin/goatcounter-log-monitor batch example-https
```

Check the CLI output and dashboard, then start your named monitor in the foreground:

```bash
~/.local/bin/goatcounter-log-monitor watch example-https
```

Open a page on the website whose log you selected. The watcher is normally quiet; allow around 30 seconds for batches to appear in the separate log analytics dashboard. From another SSH session:

```bash
~/.local/bin/goatcounter-log-monitor status
tail -n 50 ~/.local/state/goatcounter-log-monitor/example-https.log
```

Replace `example-https` with your monitor name. Ctrl+C stops a foreground watcher. A held lock proves a process is running, not that uploads are succeeding; check the dashboard and diagnostics too.

To stop a watcher from another session, including one started by cron:

```bash
~/.local/bin/goatcounter-log-monitor stop example-https
```

The command sends SIGTERM to the matching watcher and waits for its lock to be released. It also recognizes watchers started before this command was added. Running it again when stopped is harmless. It leaves active batches running. Cron remains enabled and can start the watcher again at its next scheduled check; run your batch after stopping, or disable that monitor's cron entry for a longer stop. Start it manually again with `watch example-https`, or let cron start it.

For DreamHost, choose **panel** startup. Add each printed command in the hosting panel under the shell user owning the logs. Select every five minutes and enable locking. If selecting individual minutes, use `0,5,10,15,20,25,30,35,40,45,50,55`. Do not append `&`. Panel mode prints instructions without changing crontab or starting watchers immediately.

Each watcher keeps running between checks. File locking prevents a duplicate invocation of the same monitor. After a watcher exits or the server reboots, a later cron check starts it again. The wizard saves the suggested entries here:

```bash
cat ~/.local/state/goatcounter-log-monitor/cron-suggestions.txt
```

For other hosts, **crontab** mode can install five-minute checks after confirmation. It preserves existing jobs, saves a backup, and rejects duplicate monitor markers. Do not mix direct crontab edits with DreamHost's panel service: panel updates can overwrite them. Removing a cron entry prevents future starts but does not terminate an existing importer.

## Batch upload: rotated logs and current log

Stop that monitor's watcher before running a batch. Preview first:

```bash
~/.local/bin/goatcounter-log-monitor batch example-https --dry-run

# Optional bounds: include dated archives on/after the first date,
# and strictly before the second date. These dates are examples.
~/.local/bin/goatcounter-log-monitor batch example-https \
  --from 2026-10-19 --before 2026-10-26 --dry-run

# Same range, with an interactive IMPORT confirmation before any upload.
~/.local/bin/goatcounter-log-monitor batch example-https \
  --from 2026-10-19 --before 2026-10-26
```

The CLI already reads individual gzip files but accepts only one filename per invocation. The batch helper handles selection, private snapshots, decompression, receipts, and one CLI invocation per unique file. It reuses the saved site, token, log format, datetime format, and debug setting.

For `access.log`, discovery includes `access.log.2026-10-24`, `access.log.2026-10-19.gz`, `access.log.1`, `access.log.2.gz`, and the active `access.log`. It skips symlinks such as DreamHost's `access.log.0` and unrelated files/directories. Date-named archives are chronological; numbered archives use modification day and descending rotation number. The current log is imported last. Date bounds select archive filenames and use today's server date for the current log; they do not filter timestamps inside individual records. Undated numbered archives are skipped when date bounds are supplied. Default selection has no date bounds.

Batch includes a snapshot of the configured current log by default. It copies at most the file size observed when that file is opened, so ongoing writes cannot make the upload run indefinitely. Log bytes, including any incomplete final line, are passed unchanged to GoatCounter. There is no automatic handoff: requests written between the snapshot and watcher startup can be missed.

All selected archives are snapshotted and gzip integrity is checked before uploading. Corrupt or changing archives stop the batch before uploads begin. Allow disk space roughly equal to the selected uncompressed archives. The monitor lock blocks cron starts of that same monitor during a batch; another running watcher makes the batch refuse to start. A destination/filter-scope lock prevents concurrent batches sharing receipts.

Batch passes each selected file to the GoatCounter CLI, decompressing `.gz` files into temporary plain files first. It does not preflight, parse, or rewrite log entries. Neither watch nor batch excludes GETs, HEADs, redirects, static files, or non-200 responses. To disable GoatCounter v2.7.0's default static/redirect exclusions, both pass `-exclude=path:re:a^`, an expression that can never match; this release rejects the documented empty exclusion. The server can still classify bots or reject invalid records. CLI output and errors appear directly in the terminal for batch and in the private monitor log for watch. Debug logging is off by default.

SHA-256 receipts under `~/.local/state/goatcounter-log-monitor/batches/` skip completed identical payloads, including plain/gzip copies. Changed dated archives are rejected rather than replayed. Keep the receipts: deleting them, changing destination or CLI arguments, or moving to an unrelated state directory can defeat repeat-import protection. These are **file-level receipts, not event-level deduplication**; distinct files can still contain overlapping requests. Existing receipts are retained. Version 0.2.4 changes the CLI arguments and therefore uses a new receipt scope; previous imports are not automatically skipped under the new settings.

Receipts belong only to batch; watch uses GoatCounter's `-follow` mode and neither reads nor writes them. Receipts skip unchanged files but do not track individual entries shared with watcher traffic, JavaScript submissions, or direct CLI imports. GoatCounter handles session counting on the server.

Receipts are marked `in-progress` before submission, then `complete` when the CLI exits zero. Output alone does not change that result. A completed receipt records the CLI exit status; it does not verify that pageviews appeared in the dashboard. A nonzero CLI exit stops the batch and is returned to the caller; an interruption or failed import prevents automatic retries. Review GoatCounter's output before deciding what to resubmit. There is no rollback or exactly-once guarantee. Deleting an uncertain receipt and rerunning may duplicate accepted hits.

`--dry-run` sends no pageviews and writes no receipts, although it uses locks and temporary snapshots. `--yes` skips only interactive confirmation, not locks or uncertain-receipt checks. This utility does not automatically bridge the end of batch history into live collection or recover gaps.

## Log format and CLI diagnostics

The installer accepts a native log-format name or `custom`. For DreamHost combined logs with trailing spaces, choose `custom` and accept the format and datetime defaults. Existing monitors can use the same values in their private configuration:

```bash
LOG_FORMAT='log:$remote_addr $ignore [$datetime] "$method $path $http" $status $size "$referrer" "$user_agent"$ignore'
LOG_DATETIME='02/Jan/2006:15:04:05 -0700'
LOG_DEBUG=
```

The settings are passed unchanged to the CLI. `LOG_DATETIME` defaults to empty for native predefined formats. `LOG_DEBUG` defaults to empty; explicitly set `LOG_DEBUG=import-api` when troubleshooting. Normal CLI errors remain visible with debugging off, and changing debug settings does not change batch receipt identity. Silent mode is disabled in both watch and batch. Stop and restart an existing watcher to apply new settings. Earlier installers saved `LOG_DEBUG=import-api` explicitly; clear that setting in existing configurations to turn debugging off. Updates preserve saved settings and do not change running processes.

## Troubleshoot a batch with no dashboard data

Imported records keep their original timestamps: check the archive's date range, not only today's dashboard. A clean CLI exit or a receipt marked `complete` does not prove that GoatCounter displayed visits; records might have failed parsing, been rejected, or been classified as bots by the server. Do not delete receipts and replay a batch just because the dashboard is empty.

Inspect an archive that was already uploaded without resubmitting it:

```bash
~/.local/bin/goatcounter-log-monitor inspect example-https \
  --file "$HOME/logs/example.com/https/access.log.2026-10-25"
```

Omit `--file` to inspect a bounded snapshot of the configured active log, or select a `.gz` archive. Inspection does not acquire the watcher lock or change batch receipts. It substitutes a synthetic key and local API, then reports candidate counts for format-only, hypothetical GET-only and HTTP-200-only filters, and the configured import settings. Those comparison filters are used only by this optional inspection command. It also reports the candidate date span and a heuristic count of common bot User-Agent signatures. It does not print request URLs, IPs, or raw User-Agent values. CLI diagnostics, if present, are retained only in private state files; those files may contain log details and should not be posted unredacted.

If the configured candidate count is zero or parsed records are invalid, investigate the format before another upload. If valid candidates are present, check dates and bot hints and investigate server-side processing. Bot hints are not GoatCounter's own classification; inspection cannot query the real dashboard and needs no extra API permission. The strict `combined` format supports Apache entries with `HTTP/2.0`, IPv4, and IPv6, but trailing spaces can prevent parsing. Use the custom format above for DreamHost logs with trailing spaces.

## Files and privacy

```text
install.sh                    Interactive installation and update entry point
bin/goatcounter-log-monitor    Runtime commands: watch, stop, batch, inspect, status, version
lib/common.sh                 Shared shell helpers
lib/installer.sh              Configuration, CLI installation, cron setup
lib/update.sh                 Safe source updates and launcher installation
lib/monitor.sh                Runtime command dispatch and status
libexec/batch.py               Archive selection, snapshots, receipts
libexec/stop.py                Stop a matching watcher using its existing lock
libexec/installer_helpers.py   Release metadata, URLs, version comparison, quoting
libexec/inspect_log.py         Read-only parser/filter diagnostic command
libexec/inspection.py          Isolated loopback API for local inspection
tests/                        Linux integration tests and ordinary fixture files
```

Configurations live in `~/.config/goatcounter-log-monitor/<name>.conf`, mode 600 inside a mode-700 directory. They contain API keys; never publish them or place them inside the website directory. Tokens are hidden during entry and are not passed in command-line arguments. The importer receives its key through its environment, accessible to the same Unix user and server administrators.

Diagnostics live in `~/.local/state/goatcounter-log-monitor/<name>.log`. Logs over 1 MiB rotate at startup to `.log.1`; this is not a continuous size cap. Import diagnostics can contain original log-entry data, so they are private too. Sources contain no site credentials or monitor-specific settings.

## Measurement limits

- The watcher collects new lines only. Downtime, API failures, crashes, and rotation edge cases can lose data. Historical import is explicit. Verify live collection after the first nightly rotation on your hosting server.
- All parsed entries are submitted without local exclusions. This includes HEAD requests, redirects, static files, error responses, and your own requests. GoatCounter's server-side processing and bot classification still apply.
- Parsed records can send IP addresses and User-Agent values to GoatCounter for location, bot detection, and session processing. A CDN must preserve actual visitor addresses in origin logs for useful results.
- Prefetching can fetch pages never viewed; browser/CDN caches can avoid origin requests. Log counts and JavaScript counts measure different things.
- Log-derived data lacks screen sizes and page titles. Query strings and canonical paths are not normalized by this utility.

## Tests

```bash
find lib -name '*.sh' -exec bash -n {} \;
bash -n install.sh
bash -n bin/goatcounter-log-monitor
python3 -m unittest discover -s tests -v
```

Tests use synthetic keys, mock downloads, temporary files and real local Git repositories. They cover installer migration, secret/path handling, CLI verification, monitor locking, archive batches/receipts, and safe installer updates without changing the user's real crontab or uploading to a real analytics site. Set `GC_REAL_CLI=/full/path/to/goatcounter` to enable actual CLI ingestion tests against a local mock API. `bash tests/test-real-install.sh` separately checks a real official download and retains a temporary `/tmp` installation for inspection.

ARM64 download selection is supported but has not been exercised on ARM hardware. Target-host nightly rotation still needs operational verification.

## References and license

- [GoatCounter releases](https://github.com/arp242/goatcounter/releases)
- [Log ingestion](https://www.goatcounter.com/help/logfile)
- [CLI import flags](https://github.com/arp242/goatcounter/blob/v2.7.0/cmd/goatcounter/import.go)
- [API permissions](https://github.com/arp242/goatcounter/blob/v2.7.0/api_token.go)
- [DreamHost cron panel](https://help.dreamhost.com/hc/en-us/articles/215088668-Create-a-cron-job)
- [DreamHost custom cron interaction](https://help.dreamhost.com/hc/en-us/articles/215767047-Creating-a-custom-Cron-Job)

This utility is MIT licensed. The downloaded GoatCounter CLI is a separate upstream project with its own license.
