#!/bin/bash
# deploy.sh — Sync new projections and deploy everything
#
# Usage: ./deploy.sh
#   Run this after adding new CSV files to "projections by slate - dk/"

set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
CSV_SRC="$ROOT/projections by slate - dk"
CSV_DEST="$ROOT/backend/projections"
SAL_SRC="$ROOT/dk salaries "
SAL_SRC_ALT="$ROOT/dk salaries"
SAL_DEST="$ROOT/backend/dk-salaries"
FRONTEND="$ROOT/frontend"
BACKEND="$ROOT/backend"

echo "=== 1. Syncing projection CSVs ==="
mkdir -p "$CSV_DEST"
cp "$CSV_SRC"/*.csv "$CSV_DEST/" 2>/dev/null || true
NEW=$(diff <(cd "$CSV_DEST" && ls *.csv 2>/dev/null | sort) <(cd "$CSV_SRC" && ls *.csv 2>/dev/null | sort) | grep "^>" | wc -l | tr -d ' ')
echo "  Source:  $(ls "$CSV_SRC"/*.csv 2>/dev/null | wc -l | tr -d ' ') files"
echo "  Synced:  $(ls "$CSV_DEST"/*.csv 2>/dev/null | wc -l | tr -d ' ') files in backend"

echo ""
echo "=== 1b. Syncing DK salary CSVs ==="
mkdir -p "$SAL_DEST"
cp "$SAL_SRC"/*.csv "$SAL_DEST/" 2>/dev/null || cp "$SAL_SRC_ALT"/*.csv "$SAL_DEST/" 2>/dev/null || true
echo "  Synced:  $(ls "$SAL_DEST"/*.csv 2>/dev/null | wc -l | tr -d ' ') salary files in backend"

STAGING_DIST="$ROOT/staging-frontend-dist"

PROD_DIST="$ROOT/production-frontend-dist"

echo ""
echo "=== 2. Building frontend (production) ==="
cd "$FRONTEND"
npm run build --silent
echo "  Built frontend/dist/"

echo ""
echo "=== 2b. Exporting production dist ==="
mkdir -p "$PROD_DIST"
rsync -a --delete "$FRONTEND/dist/" "$PROD_DIST/"
echo "  Exported to production-frontend-dist/"

echo ""
echo "=== 2c. Building frontend (staging) ==="
cd "$FRONTEND"
VITE_USE_STAGING=true npm run build --silent
echo "  Built staging frontend/dist/"

echo ""
echo "=== 2d. Exporting staging dist ==="
mkdir -p "$STAGING_DIST"
rsync -a --delete "$FRONTEND/dist/" "$STAGING_DIST/"
echo "  Exported to staging-frontend-dist/"

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
echo "  Backend:   https://baseball-dfs-sims.fly.dev"
echo "  Production: Drag production-frontend-dist/ to sims-life.netlify.app"
echo "  Staging:    Drag staging-frontend-dist/ to your staging Netlify site"
