#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${SEED_VC_ROOT:-$ROOT/third_party/seed-vc}"
mkdir -p "$(dirname "$DEST")"
if [[ -d "$DEST/.git" ]]; then
  echo "Seed-VC already cloned at $DEST"
else
  git clone --depth 1 https://github.com/Plachtaa/seed-vc.git "$DEST"
fi
echo "Set SEED_VC_ROOT=$DEST if you cloned elsewhere."
echo "Install Seed-VC deps from $DEST/requirements.txt (CUDA torch from pytorch.org)."
