# SPDX-License-Identifier: MIT
load_monitor() {
  local id=$1 config
  valid_name "$id" || die 'Specify a valid monitor name.'
  config="$CONFIG_DIR/$id.conf"
  [[ -f "$config" && ! -L "$config" && -O "$config" ]] || die "Missing or unsafe monitor configuration: $id"
  source "$config"
  [[ -x "$BINARY" ]] || die 'Configured CLI is unavailable.'
  export GOATCOUNTER_API_KEY
  IMPORT_ARGS=(import -silent -format="$LOG_FORMAT"
    -exclude=static -exclude=redirect -exclude='!method:GET' -exclude='!status:200'
    -exclude='path:re:\.(woff2?|ttf|otf|eot|map)(\?.*)?$' -site="$GOATCOUNTER_SITE")
}

watch_monitor() {
  local id=${1:-} log_file log_size
  load_monitor "$id"
  need flock
  mkdir -p "$STATE_DIR"
  exec 9>"$STATE_DIR/$id.lock"
  flock -n 9 || exit 0
  log_file="$STATE_DIR/$id.log"
  # Rotate diagnostics on startup if the previous run exceeded 1 MiB.
  if [[ -f "$log_file" ]]; then
    log_size=$(wc -c < "$log_file")
    (( log_size < 1048576 )) || mv -f -- "$log_file" "$log_file.1"
  fi
  exec >>"$log_file" 2>&1
  printf '\n[%s] Starting monitor %s\n' "$(date -Is)" "$id"
  [[ -r "$LOG_FILE" && -f "$LOG_FILE" ]] || die 'Configured access log is unavailable.'
  [[ -e "$STATE_DIR/$id.watch-started" ]] || date -u +%Y-%m-%dT%H:%M:%SZ > "$STATE_DIR/$id.watch-started"
  exec "$BINARY" "${IMPORT_ARGS[@]}" -follow "$LOG_FILE"
}

stop_monitor() {
  local id=${1:-}
  load_monitor "$id"
  need python3
  mkdir -p "$STATE_DIR"
  python3 "$PROJECT_ROOT/libexec/stop.py" "$STATE_DIR/$id.lock" "$id" "$BINARY" "$LOG_FILE" "$GOATCOUNTER_SITE"
}

batch_monitor() {
  local id=${1:-}
  shift || true
  load_monitor "$id"
  need python3
  need flock
  mkdir -p "$STATE_DIR"
  exec 9>"$STATE_DIR/$id.lock"
  flock -n 9 || die "This monitor is running. Run goatcounter-log-monitor stop $id before a batch; cron starts are blocked while the batch holds this lock."
  # Python handles archive discovery, private snapshots, and atomic receipts.
  # The existing CLI still parses each log and submits the actual pageviews.
  python3 "$PROJECT_ROOT/libexec/batch.py" "$STATE_DIR" "$id" "$LOG_FILE" "$GOATCOUNTER_SITE" "$BINARY" "${IMPORT_ARGS[@]}" -- "$@"
}
inspect_monitor() {
  local id=${1:-}
  shift || true
  load_monitor "$id"
  need python3
  mkdir -p "$STATE_DIR"
  GOATCOUNTER_API_KEY=goatcounter-offline-inspection python3 "$PROJECT_ROOT/libexec/inspect_log.py" \
    "$STATE_DIR" "$id" "$LOG_FILE" "$LOG_FORMAT" "$BINARY" "${IMPORT_ARGS[@]}" -- "$@"
}

show_status() {
  local config id
  need flock
  mkdir -p "$STATE_DIR"
  shopt -s nullglob
  for config in "$CONFIG_DIR"/*.conf; do
    id=${config##*/}; id=${id%.conf}
    valid_name "$id" || continue
    if flock -n "$STATE_DIR/$id.lock" true; then printf '%s: not running\n' "$id";
    else printf '%s: running (lock held)\n' "$id"; fi
  done
}
