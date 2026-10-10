# Hardware: ESP32 + MAX30102 (+ optional MPU-6050)

A research data-acquisition rig for the **Live Monitor**. It streams raw red/infrared PPG counts (and an optional accelerometer)
over **USB serial**; the app computes signal quality, perfusion index, motion, pulse rate and a reliability state live (analysis about once per second),
and can record a session to CSV. No Wi-Fi is needed.

> **Not a medical device. Do not use for diagnosis.**
> The MAX30102 is a hobby-grade sensor; nothing here claims clinical accuracy. The rig does not produce SaO₂ ground truth.
> The SpO₂ shown in the app is an *uncalibrated ratio-of-ratios estimate* and is withheld whenever the signal is poor.
>
> **Hardware status: untested.** The firmware (`esp32_max30102/esp32_max30102.ino`) has **not** been compiled or flashed by the
> repository's author, and no real sensor has been connected to the app. The host side (packet parsing, buffering, session
> recording, CSV, disconnect handling) is covered by automated tests that use a fake serial port. Try the sketch on your board.

## Parts
| Part | Purpose |
|---|---|
| ESP32 DevKit (USB) | microcontroller, USB serial |
| MAX30102 breakout | red + infrared PPG |
| MPU-6050 breakout (optional) | accelerometer → real motion estimate |
| Colorimeter / spectrophotometer | objective skin colour (L\*, a\*, b\*) → ITA |
| Reference oximetry / blood gas | reference SaO₂ (never produced by this rig) |

## Hardware wiring and MAX30102 connection (I²C, default ESP32 pins)
| Sensor pin | ESP32 |
|---|---|
| VIN / VCC | 3V3 |
| GND | GND |
| SDA | GPIO 21 |
| SCL | GPIO 22 |

MAX30102 and MPU-6050 share the same two I²C lines (MPU-6050 address 0x68). Use 3.3 V, not 5 V. The MAX30102's INT pin is not used.

**The exact pins depend on your ESP32 board.** GPIO 21 / 22 are the default I²C pins of the common ESP32 DevKit (ESP32-WROOM-32) boards only.
Other boards (ESP32-S2, S3, C3, or boards with a different pin-out) use different default SDA/SCL pins, and breakout boards differ in labelling
(some MAX30102 modules label 3.3 V as `VIN` and need pull-ups that are already on the module). Check your board's pin-out, then either wire to its
default I²C pins or change the `Wire.begin()` call in the sketch to `Wire.begin(SDA_PIN, SCL_PIN)`. The sketch was compiled for *ESP32 Dev Module*
only; see `HARDWARE_VALIDATION.md` for what has and has not been verified.

## ESP32 setup and firmware upload
1. Arduino IDE → Boards Manager → install **esp32** (Espressif). Board: *ESP32 Dev Module*.
2. Library Manager → install **SparkFun MAX3010x Pulse and Proximity Sensor Library**.
3. Open `esp32_max30102/esp32_max30102.ino`. Set `USE_MPU6050` to `0` if you have no accelerometer. Select the COM port and **Upload**.
4. Open the Serial Monitor at **115200 baud**. You should see `# PIGMENTCAL,v2-json,...` then one JSON object per line.
   **Close the Serial Monitor** before connecting from the browser (only one program can hold the port).

## Serial protocol (115200 baud, 8N1, USB)
One JSON object per line, newline-terminated:
```
# comment or status line (ignored)
{"timestamp":123456,"red":12345,"ir":23456}
{"timestamp":123456,"red":12345,"ir":23456,"accelerometer_x":0.01,"accelerometer_y":0.02,"accelerometer_z":0.98}
```
| Field | Required | Meaning |
|---|---|---|
| `timestamp` | yes | milliseconds (the firmware uses a sample counter so spacing is regular) |
| `red`, `ir` | yes | raw ADC counts, ≥ 0 |
| `accelerometer_x/y/z` | no (all three or none) | acceleration in g |

Rejected lines are counted and the reason is shown, never silently dropped: *invalid JSON*, *missing timestamp / IR / RED*,
*corrupted* (non-numeric or negative values, partial accelerometer). The older `millis,red,ir[,ax,ay,az]` line format is still accepted.

## Browser requirements
Chrome or Edge on desktop, served over **HTTPS or `http://localhost`** (Web Serial). Firefox and Safari are not supported; the app
then shows **UNSUPPORTED BROWSER** and nothing crashes. Status labels: `CONNECTED`, `DISCONNECTED`, `RECONNECT REQUIRED`
(connection ended after being connected, e.g. USB unplugged), `UNSUPPORTED BROWSER`. If data stops while connected, the app says
*"The sensor stopped sending data"*.

## How to connect
1. Start the backend and frontend (see the top-level README).
2. Open **Live Monitor** → *ESP32 + MAX30102* → baud 115200 → **Connect sensor** → choose the ESP32's port (allow the permission prompt).
3. Rest a fingertip lightly on the sensor and keep still. The waveform, IR, Red, sample count, signal quality, PI and reliability appear live.

## How to record and save a CSV
1. Enter an **anonymous** Participant ID (e.g. `P001`) and Session ID (e.g. `P001_S01`). Names, e-mail addresses and phone numbers are refused.
2. **Start session** → the page shows *LIVE RECORDING*, samples, duration and the sensor name.
3. **Stop session** (also happens automatically if the sensor disconnects; recorded samples are kept).
4. **Save session CSV** → `P001_P001_S01.csv` is downloaded.
5. Measure ITA (colorimeter) and reference SaO₂ separately and upload everything in **Data Collection**. The recorded CSV uploads as-is.

## Expected CSV format
```
participant_id,session_id,timestamp,red,ir,accelerometer_x,accelerometer_y,accelerometer_z
P001,P001_S01,0.000,81234,101234,0.010,0.020,0.980
P001,P001_S01,0.010,81301,101290,0.011,0.019,0.981
```
`timestamp` = seconds since the first recorded sample. Accelerometer cells are empty when no accelerometer is present.
**SaO₂ and ITA are never written**; they must come from real reference measurements.

## Signal polarity
Reflective PPG sensors report *lower* counts at systole, so the app flips the signal about its mean (keeping the DC level, which
perfusion index needs). Configurable per source in `backend/app/config.py` (`LiveConfig.invert_default`).

## Tuning tips
* IR counts below ~30 000 usually mean no finger; above ~250 000 the 18-bit ADC is near saturation, so lower `LED_BRIGHTNESS`.
* Press lightly: a hard press squeezes out blood and lowers perfusion.
* Ambient light, nail polish and finger movement degrade the signal. The system reports that as signal quality and motion, and abstains rather than guessing.
