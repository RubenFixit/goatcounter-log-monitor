# SPDX-License-Identifier: MIT
CONFIG_DIR="${HOME:?}/.config/goatcounter-log-monitor"
STATE_DIR="$HOME/.local/state/goatcounter-log-monitor"
TMP_DIR=''

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null || die "Required command missing: $1"; }
valid_name() { [[ "$1" =~ ^[a-z0-9][a-z0-9_-]{0,47}$ ]]; }
safe_path() { [[ "$1" == /* && "$1" != *$'\n'* && "$1" != *$'\r'* && "$1" != *%* ]]; }
expand_path() {
  case "$1" in '~') printf '%s' "$HOME";; '~/'*) printf '%s/%s' "$HOME" "${1:2}";; *) printf '%s' "$1";; esac
}
prompt() {
  local answer
  printf '%s' "$1" >&2
  [[ -z "${2:-}" ]] || printf ' [%s]' "$2" >&2
  printf ': ' >&2
  IFS= read -r answer || die 'Input ended; installation cancelled.'
  printf '%s' "${answer:-${2:-}}"
}
yes() {
  local answer
  answer=$(prompt "$1 (y/n)" "${2:-n}") || exit 1
  [[ "$answer" == [yY] || "$answer" == [yY][eE][sS] ]]
}
cleanup() {
  # Only remove the installer-created private temporary directory.
  case "$TMP_DIR" in "$STATE_DIR"/.install.*) /bin/rm -rf -- "$TMP_DIR";; esac
}
