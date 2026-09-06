#!/usr/bin/env sh
set -eu

FUSION_CLI_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
FUSION_CLI_PYTHON="$FUSION_CLI_DIR/.venv/bin/python"
if [ ! -x "$FUSION_CLI_PYTHON" ]; then
  printf '%s\n' "fusion_cli: CLI environment not found. Run: python3 -m venv \"$FUSION_CLI_DIR/.venv\" && \"$FUSION_CLI_PYTHON\" -m pip install -r \"$FUSION_CLI_DIR/requirements.txt\"" >&2
  exit 1
fi
exec "$FUSION_CLI_PYTHON" "$FUSION_CLI_DIR/fusion_cli.py" "$@"
