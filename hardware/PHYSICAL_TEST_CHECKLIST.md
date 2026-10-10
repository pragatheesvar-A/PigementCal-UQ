# Physical ESP32 + MAX30102 test checklist

**Status of every line below: NOT TESTED — REQUIRES PHYSICAL HARDWARE.** Nothing here has been run by the author of this repository.
Mark a line PASS or FAIL only from what you actually observed, with the date, board, sensor module and browser.

A hardware smoke test (even with your own finger) is **not research data**: it is not a participant dataset, a validation, or a
clinical measurement. Keep these files out of Data Collection unless they are part of a properly approved study.

## Wiring (default ESP32 DevKit / ESP32-WROOM-32 pins)
| MAX30102 module | ESP32 | Note |
|---|---|---|
| SDA | GPIO21 | I²C address 0x57 |
| SCL | GPIO22 | |
| GND | GND | |
| VIN / VCC | **3V3** | Check your module's silkscreen / datasheet: many breakouts are 3.3 V parts; some include a regulator and accept a higher VIN. Module-dependent: if unsure, use 3V3 and do **not** connect 5 V. |
| INT | not connected | not used by the firmware |

Other ESP32 boards (S2, S3, C3, other pin-outs) have different default I²C pins: use that board's SDA/SCL or change `Wire.begin(SDA, SCL)`.

## Files
- First bring-up (text output, no JSON): `hardware/diagnostics/physical_diagnostic/physical_diagnostic.ino`
- Live Monitor firmware (JSON lines, 115200 baud): `hardware/esp32_max30102/esp32_max30102.ino` (set `USE_MPU6050` to 0 if there is no accelerometer)
- Sensor firmware output only: `{"timestamp":…,"red":…,"ir":…}` (plus optional accelerometer). Never SaO₂, SpO₂, ITA, PI or SQI.

## Part 1 — Arduino IDE + Serial Monitor (115200)
Flash `physical_diagnostic.ino`, open the Serial Monitor, then press the board's EN/reset button.

| | Check | Expected (NOT observed yet) | Result |
|---|---|---|---|
| A | ESP32 detected by the computer (a COM port appears) | port visible | NOT TESTED |
| B | Correct COM port selected | | NOT TESTED |
| C | Firmware uploaded | upload succeeds | NOT TESTED |
| D | Serial Monitor opens at 115200 | readable text | NOT TESTED |
| E | I²C device found at 0x57 | `I2C device found at 0x57` | NOT TESTED |
| F | PART ID | `PART ID = 0x15` | NOT TESTED |
| G | RED values present | `RED=…` non-zero | NOT TESTED |
| H | IR values present | `IR=…` non-zero | NOT TESTED |
| I | RED changes over time (finger on, then off) | min ≠ max | NOT TESTED |
| J | IR changes over time | min ≠ max | NOT TESTED |
| K | No repeated reset | the banner appears once | NOT TESTED |
| L | No FIFO error | samples counted, none missing | NOT TESTED |

## Part 2 — JSON stream, Web Serial, Live Monitor, CSV
Flash `esp32_max30102.ino`. **Close the Arduino Serial Monitor** (only one program may hold the port). Use Chrome or Edge on desktop.

| | Check | Expected (NOT observed yet) | Result |
|---|---|---|---|
| M | JSON lines appear in the Serial Monitor | one `{"timestamp":…,"red":…,"ir":…}` per line (and `# …` comment lines) | NOT TESTED |
| N | Browser Web Serial connects (Live Monitor → ESP32 + MAX30102 → Connect sensor, 115200) | CONNECTED | NOT TESTED |
| O | Live Monitor receives samples | sample count grows | NOT TESTED |
| P | Live PPG changes with the finger | waveform moves | NOT TESTED |
| Q | Recording starts (anonymous Participant ID e.g. `P001`, Session ID e.g. `P001_S01`) | state: recording | NOT TESTED |
| R | Recording stops | state: stopped | NOT TESTED |
| S | CSV downloads | `P001_P001_S01.csv` | NOT TESTED |
| T | CSV passes validation: `python hardware/check_session_csv.py P001_P001_S01.csv --fs 100` | exit code 0 | NOT TESTED |

## Things that commonly go wrong (hypotheses to check, not findings)
- Opening a serial port from the browser can reset many ESP32 boards (DTR/RTS toggling); the timestamp then restarts from 0 and the Live Monitor starts a clean window.
- "That port is already open": close the Arduino Serial Monitor or any other program using the COM port.
- `NO I2C DEVICE FOUND`: power pin, SDA/SCL swapped, a charge-only USB cable, or a module whose pull-ups are missing.
- IR near 0 with a finger on the sensor: LED power/brightness, finger pressure, or ambient light.
- Saturation (values at 262143): lower `LED_BRIGHTNESS` in the sketch.

## Evidence to send back
The exact text from Part 1 (items E–L), a few JSON lines from M, what the Live Monitor shows for N–R, and the output of the CSV check for T.
