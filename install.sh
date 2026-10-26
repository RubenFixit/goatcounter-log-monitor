#!/bin/bash
# SPDX-License-Identifier: MIT
set +x
set +v
set -euo pipefail
umask 077
PROJECT_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
source "$PROJECT_ROOT/lib/common.sh"
source "$PROJECT_ROOT/lib/monitor.sh"
source "$PROJECT_ROOT/lib/update.sh"
source "$PROJECT_ROOT/lib/installer.sh"
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
