# One-command reproduction: venv + pinned deps -> regenerate the SYNTHETIC test data (checked against the recorded hash)
# -> backend tests -> frontend tests, typecheck, build. Writes the real output to docs/repro_log.txt.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts/reproduce.ps1 [-SkipInstall]
# -SkipInstall reuses backend\.venv and frontend\node_modules (no network).
param([switch]$SkipInstall)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $root "docs\repro_log.txt"
"PigmentCal-UQ reproduction log  $(Get-Date -Format s)  (synthetic data = software test only; no research claims)" | Out-File $log -Encoding utf8
function Step($name, [scriptblock]$cmd) {
  "`n=== $name ===" | Out-File $log -Append -Encoding utf8
  & $cmd 2>&1 | Out-File $log -Append -Encoding utf8
  "exit code: $LASTEXITCODE" | Out-File $log -Append -Encoding utf8
  Write-Host "$name -> exit $LASTEXITCODE"
}
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not $SkipInstall) {
  if (-not (Test-Path $py)) { Step "create venv" { python -m venv (Join-Path $root "backend\.venv") } }
  Step "pip install (pinned)" { & $py -m pip install -r (Join-Path $root "backend\requirements.lock") }
  Step "npm ci" { Push-Location (Join-Path $root "frontend"); npm ci; Pop-Location }
}
Step "regenerate synthetic data into a temp folder and compare with the recorded hash" {
  $tmp = Join-Path $env:TEMP "pigmentcal_synth_check"; New-Item -ItemType Directory -Force $tmp | Out-Null
  & $py -I -c "import importlib.util,sys,json,pathlib; p=pathlib.Path(r'$root')/'data'/'synthetic'; s=importlib.util.spec_from_file_location('g',p/'generate_synthetic_pipeline_data.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); got=m.write(pathlib.Path(r'$tmp')); want=json.loads((p/'synthetic_pipeline_test_dataset.meta.json').read_text(encoding='utf-8')); print('regenerated sha256', got['csv_sha256']); print('recorded    sha256', want['csv_sha256']); print('IDENTICAL' if got['csv_sha256']==want['csv_sha256'] else 'DIFFERENT (library versions differ?)')"
}
Step "backend tests" { Push-Location (Join-Path $root "backend"); & $py -m pytest -q -p no:cacheprovider; Pop-Location }
Step "frontend tests" { Push-Location (Join-Path $root "frontend"); npm test; Pop-Location }
Step "frontend typecheck" { Push-Location (Join-Path $root "frontend"); npx tsc --noEmit; Pop-Location }
Step "frontend production build" { Push-Location (Join-Path $root "frontend"); npm run build; Pop-Location }
Write-Host "Log written to $log"
