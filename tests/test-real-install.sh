#!/bin/bash
# Exercise the real upstream download without configuring sites or uploading hits.
set -euo pipefail
source "$(dirname "$0")/../install.sh"
test_root=$(mktemp -d /tmp/goatcounter-real-install.XXXXXXXX)
# Deliberately retain the small test installation for inspection after the run.
CONFIG_DIR="$test_root/config"
STATE_DIR="$test_root/state"
set +e
printf '%s\n' "$test_root/bin" | bash -c 'source "$1"; CONFIG_DIR="$2"; STATE_DIR="$3"; main --skip-update-check' \
  _ "$(dirname "$0")/../install.sh" "$CONFIG_DIR" "$STATE_DIR"
result=$?
set -e
[[ "$result" == 1 ]] || die 'Expected the wizard to stop at EOF before configuring a monitor.'
[[ -x "$test_root/bin/goatcounter" ]] || die 'CLI was not installed.'
"$test_root/bin/goatcounter" version
[[ ! -e "$test_root/config/monitor.conf" ]] || die 'Unexpected monitor configuration.'
printf 'Real verified CLI download passed; no API token, cron changes, or pageviews. Test files: %s\n' "$test_root"
if [[ -n "${GC_REAL_INSTALL_RESULT:-}" ]]; then
  printf '%s\n' "$test_root/bin/goatcounter" > "$GC_REAL_INSTALL_RESULT"
fi
