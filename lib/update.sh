# SPDX-License-Identifier: MIT
PROJECT_UPSTREAM='https://github.com/RubenFixit/goatcounter-log-monitor.git'

update_project() {
  local actual branch current available old_version new_version top
  need git
  if ! top=$(git -C "$PROJECT_ROOT" rev-parse --show-toplevel 2>/dev/null) || [[ "$top" != "$PROJECT_ROOT" ]]; then
    printf 'Utility update check unavailable: use a Git clone of %s.\n' "$PROJECT_UPSTREAM"
    return
  fi
  actual=$(git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null) || die 'This checkout has no origin remote.'
  case "$actual" in
    "$PROJECT_UPSTREAM"|'git@github.com:RubenFixit/goatcounter-log-monitor.git') ;;
    *) die 'Origin is not the expected utility repository; refusing an automatic code update.';;
  esac
  branch=$(git -C "$PROJECT_ROOT" symbolic-ref --quiet --short HEAD) || die 'Detached checkout; switch to main before updating.'
  [[ "$branch" == main ]] || die 'Automatic updates require the main branch.'
  [[ -z "$(git -C "$PROJECT_ROOT" status --porcelain)" ]] || die 'Local source changes exist. Commit or move them before updating; nothing was overwritten.'
  exec 8>"$STATE_DIR/utility-update.lock"
  flock -n 8 || die 'Another utility update is running.'
  printf 'Checking utility updates from origin/main...\n'
  git -C "$PROJECT_ROOT" fetch --quiet origin main || die 'Update check failed; no local code was changed.'
  current=$(git -C "$PROJECT_ROOT" rev-parse HEAD)
  available=$(git -C "$PROJECT_ROOT" rev-parse origin/main)
  if [[ "$current" == "$available" ]]; then
    printf 'Installer and monitor source are up to date (%s).\n' "$(cat "$PROJECT_ROOT/VERSION")"
    exec 8>&-
    return
  fi
  git -C "$PROJECT_ROOT" merge-base --is-ancestor HEAD origin/main || die 'Local and upstream history diverged; no reset or merge was attempted.'
  old_version=$(cat "$PROJECT_ROOT/VERSION")
  new_version=$(git -C "$PROJECT_ROOT" show origin/main:VERSION) || die 'Upstream VERSION file is missing.'
  [[ "$new_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die 'Unexpected upstream VERSION value.'
  printf 'Available utility update: %s (%s) -> %s (%s)\n' "$old_version" "${current:0:8}" "$new_version" "${available:0:8}"
  if ! yes 'Update the installer and all shared monitor files?' y; then
    exec 8>&-
    return
  fi
  git -C "$PROJECT_ROOT" merge --ff-only --quiet origin/main || die 'Fast-forward update failed.'
  exec 8>&-
  printf 'Source updated. Restarting the updated installer; private monitor data is unchanged.\n'
  exec /bin/bash "$PROJECT_ROOT/install.sh" --skip-update-check "$@"
}

install_runner() {
  local bin_dir=$1 temporary target="$PROJECT_ROOT/bin/goatcounter-log-monitor"
  RUNNER="$bin_dir/goatcounter-log-monitor"
  [[ -f "$target" ]] || die 'The repository runtime entry point is missing.'
  chmod 700 "$target"
  if [[ -L "$RUNNER" ]] && [[ "$(readlink -f -- "$RUNNER")" == "$target" ]]; then
    printf 'Monitor launcher already points to this checkout.\n'
  else
    [[ ! -d "$RUNNER" ]] || die "A directory occupies $RUNNER"
    if [[ -e "$RUNNER" || -L "$RUNNER" ]]; then
      yes "Replace the existing launcher at $RUNNER with the repository version?" y || die 'Existing launcher left unchanged.'
    fi
    temporary=$(mktemp -d "$bin_dir/.monitor-link.XXXXXXXX")
    ln -s -- "$target" "$temporary/launcher"
    mv -Tf -- "$temporary/launcher" "$RUNNER"
    rmdir -- "$temporary"
  fi
  # Store only a path, never credentials. Existing monitor configs and receipts
  # remain in their original per-user directories during gist migration.
  printf '%s\n' "$bin_dir" > "$STATE_DIR/install-bin"
  chmod 600 "$STATE_DIR/install-bin"
}
