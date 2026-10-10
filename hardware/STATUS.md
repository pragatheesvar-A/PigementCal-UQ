# Hardware status (single source of truth)

Only a line backed by a real log in this repository may say PASS or FAIL. Everything else is NOT TESTED. No such log exists today.

| Item | Status | Evidence |
|---|---|---|
| Firmware compiles (arduino-cli, ESP32 core 3.3.12, SparkFun MAX3010x 1.1.2) | PASS (build only) | compile output reported in the session history: `esp32_max30102.ino` 296,920 bytes, `physical_diagnostic.ino` 297,732 bytes; no log file is stored in the repo |
| Flash to a physical ESP32 | NOT TESTED | no board has been connected |
| I²C scan finds 0x57 on a physical sensor | NOT TESTED | |
| PART ID 0xFF = 0x15 on a physical sensor | NOT TESTED | |
| Raw RED values (physical) | NOT TESTED | |
| Raw IR values (physical) | NOT TESTED | |
| 100 Hz stream (physical) | NOT TESTED | |
| Browser Web Serial connects to a physical board | NOT TESTED | the parser and recorder are unit-tested with a fake serial port only |
| Physical recording → CSV | NOT TESTED | |
| Phone / webcam camera PPG | NOT TESTED | |
| Wokwi simulation | NOT EXECUTED | files in `wokwi/` are statically prepared; see `wokwi/MANUAL_VERIFICATION.md` |
| Virtual MAX30102 (software) | TESTED as software integration only | `frontend/src/lib/virtualSensor.test.ts`, `backend/tests/test_virtual_integration.py`; not hardware validation, not real measurements |
| Virtual → real transfer | NOT EVALUATED | |

## Bring-up checklist for the day a board is available
1. Wiring (3.3 V logic): SDA → GPIO21, SCL → GPIO22, GND → GND, VIN/VCC per the breakout's documented supply (3V3 is the safe default; no 5 V unless the module says so).
2. Flash `diagnostics/physical_diagnostic/physical_diagnostic.ino`, Serial Monitor 115200, press EN.
3. Expect (NOT yet observed): `I2C device found at 0x57`, `PART ID = 0x15`, non-zero RED/IR that change when a finger is placed and lifted, ~100 samples per second, `RESULT: sensor path works`.
4. Flash `esp32_max30102/esp32_max30102.ino`, close the Serial Monitor, check JSON lines `{"timestamp":…,"red":…,"ir":…}`.
5. 100 Hz check: record 60 s, then `python hardware/check_session_csv.py <file>.csv --fs 100` (reports measured rate, gaps, repeated/backwards timestamps, flatline, saturation).
6. Web Serial: Chrome/Edge → Live Monitor → ESP32 + MAX30102 → Connect sensor; unplug USB and expect RECONNECT REQUIRED.
7. Record the real outputs here and in `HARDWARE_VALIDATION.md` (date, board, module, browser) before changing any status above.

A smoke test with your own finger is not research data and not a validation of accuracy.
