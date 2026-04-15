#!/bin/bash
# deploy.sh — Sync new projections and deploy everything
#
# Usage: ./deploy.sh
#   Run this after adding new CSV files to "projections by slate - dk/"

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
CSV_SRC="$ROOT/projections by slate - dk"
CSV_DEST="$ROOT/backend/projections"
FRONTEND="$ROOT/frontend"
BACKEND="$ROOT/backend"
DIST_ZIP="$HOME/Desktop/frontend-dist.zip"

echo "=== 1. Syncing projection CSVs ==="
mkdir -p "$CSV_DEST"
cp "$CSV_SRC"/*.csv "$CSV_DEST/" 2>/dev/null || true
NEW=$(diff <(cd "$CSV_DEST" && ls *.csv 2>/dev/null | sort) <(cd "$CSV_SRC" && ls *.csv 2>/dev/null | sort) | grep "^>" | wc -l | tr -d ' ')
echo "  Source:  $(ls "$CSV_SRC"/*.csv 2>/dev/null | wc -l | tr -d ' ') files"
echo "  Synced:  $(ls "$CSV_DEST"/*.csv 2>/dev/null | wc -l | tr -d ' ') files in backend"

echo ""
echo "=== 2. Building frontend ==="
cd "$FRONTEND"
npm run build --silent
echo "  Built frontend/dist/"

echo ""
echo "=== 3. Creating Netlify zip ==="
rm -f "$DIST_ZIP"
cd "$FRONTEND/dist"
zip -rq "$DIST_ZIP" .
echo "  Created ~/Desktop/frontend-dist.zip"

echo ""
echo "=== 4. Committing changes ==="
cd "$ROOT"
git add backend/projections/ frontend/src/ backend/
git diff --cached --quiet && echo "  No changes to commit" || {
    git commit -m "Update projections and deploy $(date +%Y-%m-%d)"
    echo "  Committed"
}

echo ""
echo "=== 5. Pushing to GitHub ==="
git push origin main
echo "  Pushed"

echo ""
echo "=== 6. Deploying backend to Fly.io ==="
cd "$BACKEND"
fly deploy
echo "  Deployed"

echo ""
echo "=== Done ==="
echo "  Backend:  https://baseball-dfs-sims.fly.dev"
echo "  Netlify:  Upload ~/Desktop/frontend-dist.zip to sims-life.netlify.app"
