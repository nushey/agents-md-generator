#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

# Load .env
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: .env not found at $ENV_FILE"
  echo "Copy .env.example and fill in PYPI_TOKEN."
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

if [[ -z "${PYPI_TOKEN:-}" ]]; then
  echo "Error: PYPI_TOKEN is not set in .env"
  exit 1
fi

# Clean old dist
echo "Removing old dist..."
rm -rf "$SCRIPT_DIR/dist"

# Build
echo "Building..."
uv build

# Publish
echo "Publishing to PyPI..."
uv publish --token "$PYPI_TOKEN"

echo "Done."
