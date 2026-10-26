# Changelog

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
