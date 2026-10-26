# Changelog

## 0.2.4

- Remove all hardcoded record filtering from watch and batch, and disable the CLI's implicit static/redirect exclusions with a never-matching expression.
- Support native custom `LOG_FORMAT` and `LOG_DATETIME` settings, including the verified DreamHost format accepting trailing characters. The installer offers these through its custom-format prompts.
- Remove silent mode from watch, enable configurable `import-api` debugging by default, and describe batch results as CLI exit status rather than verified uploads.
- Add `batch --include-current` for a bounded snapshot of the current access log, imported after archives. Recommend a single initial batch before enabling a watcher or cron; document repeat-import overlap and the startup gap.
- Preserve existing receipts, but changed CLI arguments use a new receipt scope. Previous imports may overlap a new batch and are not automatically skipped.

## 0.2.3

- Add `stop NAME` to terminate the matching watcher and wait for its monitor lock to be released. This also works with watchers started before this update; active batches are left running.
- Point batch lock errors to the stop command. Stopping does not change cron jobs; a later cron invocation can restart the watcher.

## 0.2.2

- Simplify batch imports: pass each archive to the GoatCounter CLI without local parser preflight or candidate validation.
- Show GoatCounter's normal output and errors directly, and use its exit status to determine completion. Preserve existing archive selection, gzip handling, locks, and repeat-import receipts.
- Keep `inspect` as an optional diagnostic command; batch imports no longer invoke it automatically.

## 0.2.1

- Add `inspect NAME [--file PATH]`: exercise the CLI parser against a temporary loopback API with a synthetic key, report format/filter counts and bot User-Agent hints, and discard records without contacting the real site or changing receipts.
- Preflight new batch archives locally and reject zero-record or invalid parses before writing success receipts or uploading any archive in that batch.
- Record eligible-row counts and distinguish a quiet CLI submission from verified dashboard data. Existing receipts remain unchanged and do not prove rows were submitted or counted.
- Verify combined Apache HTTP/2 logs with anonymized IPv4/IPv6, redirects, successful GETs, HEAD checks, assets, bot signatures, and rate-limited responses using the real CLI.

## 0.2.0

- Move the standalone gist utility into a repository with separate installer, monitor, shell libraries, Python helpers, and test fixtures.
- Replace installed generated/copied monolithic scripts with a symlink to the repository's runtime entry point.
- Add installer-only `update` and `update --monitor-only` modes; the monitor exposes no update command.
- Detect existing monitor configurations and preserve API keys, cron jobs, diagnostics, and batch receipts during migration and updates.
- Check source updates against the official origin, allow only a clean fast-forward on `main`, and restart the updated installer before continuing.
- Detect the latest official GoatCounter CLI version, avoid redundant downloads or downgrades, and retain checksum verification and atomic executable replacement.
- Preserve live-watching and rotated/gzip archive batch behavior with repeat-import receipts and conservative partial-failure handling.

## Earlier standalone gist

The first version provided a single-file interactive installer, live watcher, batch importer, and cron setup. Its saved monitor configurations and state remain compatible with 0.2.0. The deleted gist is not needed for migration.
