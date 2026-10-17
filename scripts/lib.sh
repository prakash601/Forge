#!/usr/bin/env bash
# Shared shell prelude for scripts/* (Issue #85). Sourced, never executed:
#
#   . "$(cd "$(dirname "$0")" && pwd)/lib.sh"
#   forge_cd_repo_root
#
# shellcheck shell=bash

forge_cd_repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
}

forge_export_uv_path() {
  export PATH="$HOME/.local/bin:$PATH"
}

forge_load_dotenv() {
  # Optional local overrides; mirrors the old per-script inline block.
  # shellcheck disable=SC1091
  if [ -f .env ]; then
    set -a
    . ./.env
    set +a
  fi
}
