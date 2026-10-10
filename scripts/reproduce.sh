#!/usr/bin/env bash
# One-command reproduction (see reproduce.ps1). Usage: bash scripts/reproduce.sh [--skip-install]
# Writes the real command output to docs/repro_log.txt. Synthetic data = software test only; no research claims.
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
log="$root/docs/repro_log.txt"
if [ -x "$root/backend/.venv/Scripts/python.exe" ]; then py="$root/backend/.venv/Scripts/python.exe"; else py="$root/backend/.venv/bin/python"; fi
echo "PigmentCal-UQ reproduction log  $(date -Iseconds)  (synthetic data = software test only; no research claims)" > "$log"
step() { name="$1"; shift; printf '\n=== %s ===\n' "$name" >> "$log"; "$@" >> "$log" 2>&1; code=$?; echo "exit code: $code" >> "$log"; echo "$name -> exit $code"; }
if [ "${1:-}" != "--skip-install" ]; then
  [ -e "$py" ] || step "create venv" python3 -m venv "$root/backend/.venv"
  step "pip install (pinned)" "$py" -m pip install -r "$root/backend/requirements.lock"
  step "npm ci" bash -c "cd '$root/frontend' && npm ci"
fi
step "regenerate synthetic data and compare with the recorded hash" "$py" -I -c "
import importlib.util, json, pathlib, tempfile
p = pathlib.Path(r'$root') / 'data' / 'synthetic'
s = importlib.util.spec_from_file_location('g', p / 'generate_synthetic_pipeline_data.py'); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
got = m.write(pathlib.Path(tempfile.mkdtemp())); want = json.loads((p / 'synthetic_pipeline_test_dataset.meta.json').read_text(encoding='utf-8'))
print('regenerated sha256', got['csv_sha256']); print('recorded    sha256', want['csv_sha256'])
print('IDENTICAL' if got['csv_sha256'] == want['csv_sha256'] else 'DIFFERENT (library versions differ?)')"
step "backend tests" bash -c "cd '$root/backend' && '$py' -m pytest -q -p no:cacheprovider"
step "frontend tests" bash -c "cd '$root/frontend' && npm test"
step "frontend typecheck" bash -c "cd '$root/frontend' && npx tsc --noEmit"
step "frontend production build" bash -c "cd '$root/frontend' && npm run build"
echo "Log written to $log"
