#!/usr/bin/env bash
# Update vendored third-party CSS/JS in src/mail_merge/web/static/.
#
# Usage: ./scripts/update-vendor.sh
#
# Fetches the latest releases from CDN and overwrites the local copies.
# Review the diff before committing.

set -euo pipefail

STATIC="src/mail_merge/web/static"

echo "Updating Pico CSS..."
curl -fsSL "https://unpkg.com/@picocss/pico/css/pico.conditional.min.css" -o "$STATIC/pico.min.css"
pico_ver=$(sed -n 's/.*Pico CSS[^v]*v\([0-9.]*\).*/\1/p' "$STATIC/pico.min.css" | head -1)
echo "  → Pico CSS v${pico_ver:-unknown}"

echo "Updating Trix..."
curl -fsSL "https://unpkg.com/trix/dist/trix.umd.min.js" -o "$STATIC/trix.js"
curl -fsSL "https://unpkg.com/trix/dist/trix.css" -o "$STATIC/trix.css"
trix_ver=$(head -5 "$STATIC/trix.js" | sed -n 's/.*Trix \([0-9.]*\).*/\1/p')
echo "  → Trix v${trix_ver:-unknown}"

echo ""
echo "Done. Review changes with: git diff $STATIC"
