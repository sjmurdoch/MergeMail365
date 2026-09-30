#!/usr/bin/env bash
# Update vendored third-party CSS/JS in src/mail_merge/web/static/.
#
# Usage: ./scripts/update-vendor.sh [--trix VERSION] [--pico VERSION] [--min-age-days N]
#
# Versions are pinned below (or via TRIX_VERSION / PICO_VERSION env vars or
# the flags above). As a supply-chain precaution, matching the exclude-newer
# setting in pyproject.toml, a version is refused if npm shows it was
# published less than MIN_AGE_DAYS (default 7) days ago.
#
# Review the diff before committing.

set -euo pipefail

TRIX_VERSION="${TRIX_VERSION:-2.1.19}"
PICO_VERSION="${PICO_VERSION:-2.1.1}"
MIN_AGE_DAYS="${MIN_AGE_DAYS:-7}"

while [ "$#" -gt 0 ]; do
    case "$1" in
        --trix) TRIX_VERSION="$2"; shift 2 ;;
        --pico) PICO_VERSION="$2"; shift 2 ;;
        --min-age-days) MIN_AGE_DAYS="$2"; shift 2 ;;
        -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done

STATIC="src/mail_merge/web/static"

# Fail unless npm package $1 at version $2 was published at least MIN_AGE_DAYS ago.
check_age() {
    local pkg="$1"
    local version="$2"
    curl -fsSL "https://registry.npmjs.org/$pkg" | python3 -c '
import datetime, json, sys
pkg, version, min_days = sys.argv[1], sys.argv[2], int(sys.argv[3])
published = json.load(sys.stdin)["time"].get(version)
if published is None:
    sys.exit(f"{pkg}@{version} not found on npm")
age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(published.replace("Z", "+00:00"))
if age < datetime.timedelta(days=min_days):
    sys.exit(f"{pkg}@{version} was published {age.days} day(s) ago; minimum is {min_days}")
print(f"  {pkg}@{version} published {published[:10]} ({age.days} days ago)")
' "$pkg" "$version" "$MIN_AGE_DAYS"
}

echo "Updating Pico CSS..."
check_age "@picocss/pico" "$PICO_VERSION"
curl -fsSL "https://unpkg.com/@picocss/pico@${PICO_VERSION}/css/pico.conditional.min.css" -o "$STATIC/pico.min.css"
pico_ver=$(sed -n 's/.*Pico CSS[^v]*v\([0-9.]*\).*/\1/p' "$STATIC/pico.min.css" | head -1)
echo "  → Pico CSS v${pico_ver:-unknown}"

echo "Updating Trix..."
check_age "trix" "$TRIX_VERSION"
curl -fsSL "https://unpkg.com/trix@${TRIX_VERSION}/dist/trix.umd.min.js" -o "$STATIC/trix.js"
curl -fsSL "https://unpkg.com/trix@${TRIX_VERSION}/dist/trix.css" -o "$STATIC/trix.css"
trix_ver=$(head -5 "$STATIC/trix.js" | sed -n 's/.*Trix \([0-9.]*\).*/\1/p')
echo "  → Trix v${trix_ver:-unknown}"

echo ""
echo "Done. Review changes with: git diff $STATIC"
