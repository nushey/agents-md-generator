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

# Sync version from pyproject.toml into server.json
VERSION=$(grep '^version = ' "$SCRIPT_DIR/pyproject.toml" | head -1 | sed 's/version = "\(.*\)"/\1/')
echo "Version: $VERSION"
sed -i "s/\"version\": \".*\"/\"version\": \"$VERSION\"/g" "$SCRIPT_DIR/server.json"

# Clean old dist
echo "Removing old dist..."
rm -rf "$SCRIPT_DIR/dist"

# Build
echo "Building..."
uv build

# Publish to PyPI
echo "Publishing to PyPI..."
uv publish --token "$PYPI_TOKEN"

# Publish to MCP Registry
echo "Publishing to MCP Registry..."
if ! command -v mcp-publisher &>/dev/null; then
  echo "Error: mcp-publisher not found. Install it first."
  exit 1
fi
mcp-publisher publish

# Git: stage version files, commit, push dev, merge into main
echo "Committing version bump..."
git -C "$SCRIPT_DIR" add pyproject.toml server.json
git -C "$SCRIPT_DIR" commit -m "chore: bump to version $VERSION"

echo "Pushing to dev..."
git -C "$SCRIPT_DIR" push origin dev

echo "Merging dev into main..."
git -C "$SCRIPT_DIR" checkout main
git -C "$SCRIPT_DIR" merge dev --no-edit
git -C "$SCRIPT_DIR" push origin main
git -C "$SCRIPT_DIR" checkout dev

echo "Done."
