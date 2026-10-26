# SPDX-License-Identifier: MIT
normalize_site() {
  python3 "$PROJECT_ROOT/libexec/installer_helpers.py" normalize-site "$1"
}

validate_key() {
  local site=$1 key=$2 code
  # A header file keeps the token out of curl's process arguments and output.
  [[ -n "$key" && "$key" != *$'\r'* && "$key" != *$'\n'* ]] || return 1
  printf 'Authorization: Bearer %s\n' "$key" > "$TMP_DIR/auth-header"
  if ! code=$(curl --silent --show-error --proto '=https' --connect-timeout 10 --max-time 30 \
      --header "@$TMP_DIR/auth-header" --header 'Content-Type: application/json' \
      --data '{"perm":2}' --output /dev/null --write-out '%{http_code}' \
      "$site/api/v0/test"); then
    : > "$TMP_DIR/auth-header"
    printf 'Could not connect to the site API.\n' >&2
    return 1
  fi
  : > "$TMP_DIR/auth-header"
  [[ "$code" == 200 ]] || { printf 'API check returned HTTP %s. Check the URL, token, site access, and Record pageviews permission.\n' "$code" >&2; return 1; }
}

install_cli() {
  local bin_dir=$1 arch tag url digest installed version_state current_version=''
  case "$(uname -m)" in x86_64|amd64) arch=amd64;; aarch64|arm64) arch=arm64;; *) die 'Supported architectures: x86_64 and ARM64.';; esac
  CLI="$bin_dir/goatcounter"
  if [[ -e "$CLI" ]]; then
    [[ -f "$CLI" && -x "$CLI" && ! -L "$CLI" ]] || die "Not a regular executable: $CLI"
    current_version=$("$CLI" version) || die 'The installed CLI did not report its version.'
    printf 'Installed CLI: %s\n' "$current_version"
  fi
  printf 'Fetching official release metadata...\n'
  if ! curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --connect-timeout 10 --max-time 60 \
    https://api.github.com/repos/arp242/goatcounter/releases/latest > "$TMP_DIR/release.json"; then
    if [[ -n "$current_version" ]] && yes 'Release check failed. Keep the existing CLI?' y; then return; fi
    die 'Could not check official CLI releases.'
  fi
  python3 "$PROJECT_ROOT/libexec/installer_helpers.py" release "$TMP_DIR/release.json" "$arch" > "$TMP_DIR/asset.txt"
  mapfile -t installed < "$TMP_DIR/asset.txt"
  tag=${installed[0]} url=${installed[1]} digest=${installed[2]}
  if [[ -n "$current_version" ]]; then
    version_state=$(python3 "$PROJECT_ROOT/libexec/installer_helpers.py" cli-version-state "$tag" "$current_version")
    if [[ "$version_state" == same ]]; then
      printf 'GoatCounter CLI is up to date (%s).\n' "$tag"
      return
    fi
    if [[ "$version_state" == newer ]]; then
      printf 'Installed CLI is newer than the latest stable release; leaving it unchanged.\n'
      return
    fi
    printf 'Latest stable CLI: %s\n' "$tag"
    yes 'Install this CLI release over the existing version?' y || return 0
  fi
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
    --connect-timeout 10 --max-time 180 "$url" -o "$TMP_DIR/goatcounter.gz"
  printf '%s  %s\n' "$digest" "$TMP_DIR/goatcounter.gz" | sha256sum --check --status \
    || die 'CLI checksum mismatch; nothing was installed.'
  gzip -dc "$TMP_DIR/goatcounter.gz" > "$TMP_DIR/goatcounter"
  chmod 700 "$TMP_DIR/goatcounter"
  "$TMP_DIR/goatcounter" version
  # Stage on the destination filesystem and rename over an old binary. Running
  # importers can finish using the old inode; no executable is truncated.
  local staged
  staged=$(mktemp "$bin_dir/.goatcounter.XXXXXX")
  install -m 700 "$TMP_DIR/goatcounter" "$staged"
  mv -f -- "$staged" "$CLI"
  printf 'Installed GoatCounter %s at %s\n' "$tag" "$CLI"
}
cron_command() {
  # POSIX shell quoting; cron treats percent specially even inside quotes.
  python3 "$PROJECT_ROOT/libexec/installer_helpers.py" cron-command "$RUNNER" "$1"
}

configure_monitor() {
  local id site token log_path format datetime='' staged reuse
  while :; do
    id=$(prompt 'Monitor name (lowercase letters, digits, hyphen, underscore)') || exit 1
    valid_name "$id" || { printf 'Use 1–48 characters; start with a letter or digit.\n' >&2; continue; }
    [[ ! -e "$CONFIG_DIR/$id.conf" ]] || { printf 'That monitor already exists; choose a new name.\n' >&2; continue; }
    break
  done
  while :; do
    site=$(prompt 'GoatCounter site base URL (not /count)' "${LAST_SITE:-}") || exit 1
    if site=$(normalize_site "$site"); then break; fi
  done
  printf 'API token: enable only Record pageviews, and allow this analytics site.\n'
  while :; do
    token=''
    if [[ "$site" == "${LAST_SITE:-}" && -n "${LAST_TOKEN:-}" ]] && yes 'Reuse the previous token for this site?' y; then
      token=$LAST_TOKEN
    else
      printf 'API token (hidden): ' >&2
      IFS= read -rs token || die 'Input ended.'
      printf '\n' >&2
    fi
    if validate_key "$site" "$token"; then break; fi
    yes 'Try the token again?' y || die 'No monitor was saved.'
  done
  printf 'Token and Record pageviews permission verified; no pageview was sent.\n'
  while :; do
    log_path=$(prompt 'Full access.log path (~ is supported)' "${LAST_LOG:-}") || exit 1
    log_path=$(expand_path "$log_path")
    safe_path "$log_path" && [[ -f "$log_path" && -r "$log_path" ]] && break
    printf 'Choose an existing readable log file using an absolute path (no %% or line breaks).\n' >&2
  done
  while :; do
    printf 'For DreamHost combined logs with trailing spaces, choose custom.\n' >&2
    format=$(prompt 'Log format: combined, combined-vhost, common, common-vhost, caddy, bunny, custom' combined) || exit 1
    case "$format" in
      custom)
        format=$(prompt 'Custom log: format' 'log:$remote_addr $ignore [$datetime] "$method $path $http" $status $size "$referrer" "$user_agent"$ignore') || exit 1
        [[ "$format" == log:* ]] || { printf 'Custom formats must start with log:.\n' >&2; continue; }
        datetime=$(prompt 'Datetime format' '02/Jan/2006:15:04:05 -0700') || exit 1
        break;;
      combined|combined-vhost|common|common-vhost|caddy|bunny) break;;
    esac
  done
  printf '\nMonitor: %s\nSite: %s\nLog: %s\nFormat: %s\n' "$id" "$site" "$log_path" "$format"
  yes 'Save this monitor?' y || return 0
  staged=$(mktemp "$CONFIG_DIR/.$id.XXXXXX")
  {
    printf '# Generated private configuration. Never publish this file.\n'
    printf 'BINARY=%q\n' "$CLI"
    printf 'GOATCOUNTER_SITE=%q\n' "$site"
    printf 'GOATCOUNTER_API_KEY=%q\n' "$token"
    printf 'LOG_FILE=%q\n' "$log_path"
    printf 'LOG_FORMAT=%q\n' "$format"
    printf 'LOG_DATETIME=%q\n' "$datetime"
    printf 'LOG_DEBUG=import-api\n'
  } > "$staged"
  chmod 600 "$staged"
  mv -- "$staged" "$CONFIG_DIR/$id.conf"
  MONITORS+=("$id")
  LAST_SITE=$site LAST_TOKEN=$token LAST_LOG=$log_path
  printf 'Saved %s (token omitted from output).\n' "$id"
}

setup_cron() {
  local mode id command old_status
  while :; do
    mode=$(prompt 'Startup setup: panel (DreamHost), crontab, or manual' panel) || exit 1
    case "$mode" in panel|crontab|manual) break;; esac
  done
  printf '\nCron schedule: every five minutes. Each monitor keeps running between checks.\n'
  : > "$TMP_DIR/new-cron"
  for id in "${MONITORS[@]}"; do
    command=$(cron_command "$id")
    printf '\n%s:\n%s\n' "$id" "$command"
    printf '*/5 * * * * %s # goatcounter-log-monitor:%s\n' "$command" "$id" >> "$TMP_DIR/new-cron"
  done
  case "$mode" in
    panel)
      printf '\nIn your hosting panel, add one job per command above under this shell user.\n'
      printf 'Select every five minutes and enable locking. Do not append &.\n'
      printf 'Do not also install the same jobs via crontab; panel edits may replace them.\n';;
    crontab)
      need crontab
      printf '\nHosting panels may overwrite direct crontab edits. Existing jobs will be preserved.\n'
      yes 'Install these jobs in your user crontab now?' n || return 0
      old_status=0
      crontab -l > "$TMP_DIR/old-cron" 2> "$TMP_DIR/cron-error" || old_status=$?
      if (( old_status != 0 )); then
        grep -qi 'no crontab for' "$TMP_DIR/cron-error" || die 'Could not read crontab; no changes made.'
        : > "$TMP_DIR/old-cron"
      fi
      # Back up before adding entries. Never replace unrelated jobs or silently
      # append a second entry bearing the same monitor marker.
      cp -- "$TMP_DIR/old-cron" "$STATE_DIR/crontab-backup-$(date +%Y%m%dT%H%M%S)-$$.txt"
      for id in "${MONITORS[@]}"; do
        if grep -Fq "# goatcounter-log-monitor:$id" "$TMP_DIR/old-cron"; then
          die "An existing cron marker already names $id; review it before changing the crontab."
        fi
      done
      { cat "$TMP_DIR/old-cron"; printf '\n'; cat "$TMP_DIR/new-cron"; } > "$TMP_DIR/combined-cron"
      crontab "$TMP_DIR/combined-cron"
      printf 'User crontab updated. Watchers start at the next scheduled check.\n';;
    manual) printf '\nRun the commands above yourself; no startup jobs were changed.\n';;
  esac
  install -m 600 "$TMP_DIR/new-cron" "$STATE_DIR/cron-suggestions.txt"
}
main() {
  local bin_dir command update_only=0 monitor_only=0 skip_check=0 config id
  local -a existing=() restart_args=()
  while (( $# )); do
    case "$1" in
      update) update_only=1; restart_args+=(update);;
      --monitor-only) monitor_only=1; restart_args+=(--monitor-only);;
      --skip-update-check) skip_check=1;;
      --help|-h)
        printf 'Usage: bash install.sh [update [--monitor-only]] [--skip-update-check]\n'
        printf 'Updates are installer-only. Existing monitors, keys, cron jobs, and receipts are preserved.\n'
        return;;
      *) die "Unknown installer option: $1";;
    esac
    shift
  done
  (( !monitor_only || update_only )) || die '--monitor-only requires update.'
  [[ "$(uname -s)" == Linux ]] || die 'This wizard installs Linux binaries. Run it on your VPS.'
  (( BASH_VERSINFO[0] >= 4 )) || die 'Bash 4 or newer is required.'
  [[ "${EUID:-$(id -u)}" != 0 ]] || die 'Run as the hosting shell user, not root.'
  for command in curl python3 gzip sha256sum flock install mktemp; do need "$command"; done
  printf 'GoatCounter log monitor installer %s\n\n' "$(cat "$PROJECT_ROOT/VERSION")"
  printf 'This installs per-user files and monitors NEW access-log entries.\n'
  printf 'Installation imports no history; the optional batch command imports rotated archives.\n'
  printf 'Stopped watchers do not catch up after restart.\n'
  printf 'Use a separate GoatCounter analytics site if JavaScript tracking remains enabled.\n\n'
  [[ ! -L "$CONFIG_DIR" && ! -L "$STATE_DIR" ]] || die 'Configuration/state directories must not be symlinks.'
  mkdir -p "$CONFIG_DIR" "$STATE_DIR"
  chmod 700 "$CONFIG_DIR" "$STATE_DIR"
  shopt -s nullglob
  for config in "$CONFIG_DIR"/*.conf; do
    id=${config##*/}; id=${id%.conf}
    valid_name "$id" && existing+=("$id")
  done
  if (( ${#existing[@]} )); then
    printf 'Existing monitors (configuration and receipts will be preserved):\n'
    printf '  %s\n' "${existing[@]}"
  fi
  if (( !skip_check )); then update_project "${restart_args[@]}"; fi
  TMP_DIR=$(mktemp -d "$STATE_DIR/.install.XXXXXXXX")
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  while :; do
    bin_dir="$HOME/.local/bin"
    if [[ -f "$STATE_DIR/install-bin" && ! -L "$STATE_DIR/install-bin" ]]; then
      IFS= read -r bin_dir < "$STATE_DIR/install-bin"
    elif (( ${#existing[@]} )); then
      # Read the executable path from an existing private, trusted config in a
      # subshell; don't load or print its API token in the installer process.
      bin_dir=$(source "$CONFIG_DIR/${existing[0]}.conf"; dirname -- "$BINARY")
    fi
    bin_dir=$(prompt 'Executable directory' "$bin_dir") || exit 1
    bin_dir=$(expand_path "$bin_dir")
    safe_path "$bin_dir" && break
    printf 'Use an absolute path without %% or line breaks.\n' >&2
  done
  mkdir -p "$bin_dir"
  bin_dir=$(cd "$bin_dir" && pwd -P)
  safe_path "$bin_dir" || die 'Resolved executable path contains unsupported characters.'
  if (( monitor_only )); then
    CLI="$bin_dir/goatcounter"
    printf 'Skipping GoatCounter CLI updates (--monitor-only).\n'
  else
    install_cli "$bin_dir"
  fi
  RUNNER="$bin_dir/goatcounter-log-monitor"
  install_runner "$bin_dir"
  if (( update_only )); then
    printf '\nUpdate complete. Existing monitor settings, receipts, and cron jobs were not changed.\n'
    printf 'Running importers keep their loaded code/binary until restarted; they were not interrupted.\n'
    return
  fi
  if (( ${#existing[@]} )) && ! yes 'Add a new monitor?' n; then
    printf 'Installation checked/updated; existing monitors are unchanged.\n'
    return
  fi
  MONITORS=()
  while :; do
    configure_monitor
    yes 'Add another monitor (another log or site)?' n || break
  done
  (( ${#MONITORS[@]} > 0 )) || die 'No monitors saved; no cron jobs changed.'
  printf '\nRecommended first step: run one batch BEFORE starting a watcher or enabling cron.\n'
  for id in "${MONITORS[@]}"; do
    printf '  %q batch %q --include-current\n' "$RUNNER" "$id"
  done
  printf 'This imports existing rotated logs and a snapshot of today\047s access.log.\n'
  setup_cron
  unset LAST_TOKEN
  printf '\nDone. Check status with: %q status\n' "$RUNNER"
  printf 'Private diagnostic logs: %s/<monitor>.log\n' "$STATE_DIR"
  printf 'Recommended initial batch (before any watcher): %q batch %s --include-current\n' "$RUNNER" "${MONITORS[0]}"
  printf 'Verify collection after the first nightly log rotation. No gap recovery is provided.\n'
}
