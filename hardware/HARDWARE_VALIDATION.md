# Hardware validation log: ESP32 + MAX30102

Not a medical device. Nothing here is a claim of medical or clinical accuracy.
Only items marked PASS or FAIL were actually performed; everything else says NOT TESTED.

## Status (updated only from real tests)
| Item | Status | Evidence |
|---|---|---|
| Firmware compile | NOT RUN | The ESP32 toolchain download (about 395 MB) was too slow and was stopped at 8%; the sketch has never been compiled |
| ESP32 connection (USB serial port appears) | NOT TESTED | No ESP32 was connected to the machine used for development: no serial port was present (checked 2026-10-07) |
| MAX30102 detection (I²C) | NOT TESTED | needs the physical sensor |
| Stable serial stream, IR and RED changing | NOT TESTED | needs the physical sensor |
| Web Serial (Connect / Connected / Disconnect) with the real board | NOT TESTED | Only a fake serial port was used in the automated tests |
| Live PPG waveform from the real sensor | NOT TESTED | |
| Session recording and CSV from the real sensor | NOT TESTED | The CSV writer is unit-tested with synthetic samples only |

## Compile test
Not run. An isolated arduino-cli was set up, but the ESP32 core download did not finish, so there is no PASS or FAIL for the compile. Compile it yourself in the Arduino IDE (board *ESP32 Dev Module*, library *SparkFun MAX3010x*), or with `arduino-cli compile --fqbn esp32:esp32:esp32 hardware/esp32_max30102`, and record the result here.

## How to run the physical validation yourself (about 15 minutes)
1. **Wire** the MAX30102 to the ESP32 (3.3 V, GND, SDA, SCL; exact pins depend on your board, see `README.md`).
2. **Flash** `esp32_max30102/esp32_max30102.ino` (board *ESP32 Dev Module*, 115200 baud).
3. **ESP32 + MAX30102 detected:** open the Arduino Serial Monitor at 115200. Expect `# PIGMENTCAL,v2-json,...` and then JSON lines.
   `# ERROR: MAX30102 not found` means a wiring or power problem. Close the Serial Monitor afterwards.
4. **IR/RED change:** put a fingertip on the sensor, then remove it. IR should rise from a low value to roughly 50 000–250 000 and RED should move with it.
5. **Web Serial:** in Chrome/Edge open Live Monitor, choose *ESP32 + MAX30102*, **Connect sensor**. Expect CONNECTED, a live waveform and a growing sample count. Unplug the USB cable: expect RECONNECT REQUIRED.
6. **Record:** enter an anonymous Participant ID (`P001`) and Session ID (`P001_S01`), Start session, record 30–60 s, Stop, **Save session CSV**.
7. **Quality check the CSV:** `python hardware/check_session_csv.py P001_P001_S01.csv --fs 100`. It reports missing samples, repeated or backwards timestamps, flatline, saturation, non-numeric values and empty accelerometer columns. It does not check accuracy.
8. Record the outcome in the table above (PASS / FAIL, date, board, sensor module, browser).
