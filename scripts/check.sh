#!/usr/bin/env sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

if [ -n "${PYTHON:-}" ]; then
  exec "$PYTHON" "$repo_root/scripts/check_project.py"
fi

for candidate in \
  "$repo_root/.venv/Scripts/python.exe" \
  "$repo_root/venv/Scripts/python.exe" \
  "$repo_root/.venv/bin/python" \
  "$repo_root/venv/bin/python" \
  python \
  python3
do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" --version >/dev/null 2>&1; then
    exec "$candidate" "$repo_root/scripts/check_project.py"
  fi
done

if command -v py >/dev/null 2>&1 && py -3 --version >/dev/null 2>&1; then
  exec py -3 "$repo_root/scripts/check_project.py"
fi

echo "Python was not found. Install Python, activate a venv, or set PYTHON before pushing." >&2
exit 1
