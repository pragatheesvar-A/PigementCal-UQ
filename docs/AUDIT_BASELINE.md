# Audit baseline (recorded BEFORE any change in this audit)

Date: 2026-10-08 · Python 3.13.15 · Node v24.14.1 · Windows 11 · the project folder is not a git repository (so no commits were made).

| Command | Result (real output) |
|---|---|
| `cd backend && python -m pytest -q` | `457 passed in 61.07s (0:01:01)` |
| `cd frontend && npm test` | `Test Files 6 passed (6)` · `Tests 106 passed (106)` |
| `cd frontend && npx tsc --noEmit` | no output, exit 0 |
| `cd frontend && npm run build` | `✓ built in 672ms` |

## Not covered by a dedicated test
- Backend: every module under `backend/app` is named in at least one test file (this says nothing about branch coverage).
- Frontend pages/components with no direct unit test (they are only exercised by browser scripts that are not part of the suite): `Boundary`, `ConformalPanel`, `Limitations`, `Safety`, `Shell`, `ResultPanel`, `liveApi`, `perfusionApi`, `pigmentApi`, `signalApi`, and the pages `DataCollection`, `LiveMonitor`, `Models`, `Overview`, `Perfusion`, `Pigmentation`, `ReliabilityCheck`, `Results`, `SignalQuality`, `Summary`, `Xai`.
- Hardware: `hardware/esp32_max30102/esp32_max30102.ino`, `hardware/diagnostics/physical_diagnostic`, `hardware/wokwi/*` have no automated tests (they compile with arduino-cli; that is a build check only). `hardware/check_session_csv.py` is tested indirectly in the browser flow only.

## Baseline truths (unchanged by this audit)
REAL RESEARCH DATA = 0 · REAL VALIDATION = NOT AVAILABLE · PHYSICAL ESP32 = NOT TESTED · PHYSICAL MAX30102 = NOT TESTED · WOKWI RUNTIME = NOT EXECUTED · WEB SERIAL = NOT TESTED · PHONE CAMERA PPG = NOT TESTED · OPENOXIMETRY = BLOCKED.
