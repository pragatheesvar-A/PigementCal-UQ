/*
 * PigmentCal-UQ — Wokwi simulation sketch: ESP32 + simulated MAX30102 -> JSON lines for the Live Monitor.
 *
 * Output (115200 baud) is ONLY the Live Monitor protocol, one JSON object per line:
 *     {"timestamp":123456,"red":12345,"ir":23456}
 * Nothing else is printed while streaming. If the sensor is not found, a single '#' comment line (ignored by the app)
 * is printed repeatedly instead; no JSON is produced in that state.
 *
 * Deterministic synthetic waveform for simulator/integration testing only.
 * The RED/IR counts come from the SIMULATED chip (max-30102.chip.c): a synthetic test waveform, not a physiological
 * measurement. This verifies the software / I2C / serial path only; it is NOT physical-hardware or clinical validation.
 */
#include <Wire.h>
#include "MAX30105.h"          // SparkFun library; also drives the MAX30102

#define SERIAL_BAUD     115200
#define SAMPLE_RATE_HZ  100    // output rate after averaging

MAX30105 sensor;
static uint32_t sampleIndex = 0;

void setup() {
  Serial.begin(SERIAL_BAUD);
  Wire.begin(21, 22);          // SDA = GPIO21, SCL = GPIO22
  Wire.setClock(400000);
  delay(200);

  if (!sensor.begin(Wire, I2C_SPEED_FAST)) {
    while (true) {
      Serial.println("# ERROR: MAX30102 not found - check SDA=GPIO21 / SCL=GPIO22 and the chip definition");
      delay(1000);
    }
  }
  // brightness, average 4, red+IR, 400 sps internally -> 100 Hz output, 411 us pulse width (18-bit), 16384 range
  sensor.setup(0x3F, 4, 2, 400, 411, 16384);
}

void loop() {
  sensor.check();
  while (sensor.available()) {
    uint32_t red = sensor.getFIFORed();
    uint32_t ir  = sensor.getFIFOIR();
    sensor.nextSample();
    uint32_t ms = (uint32_t)(((uint64_t)sampleIndex * 1000ULL) / SAMPLE_RATE_HZ);   // sample-counter time, as in the real firmware
    sampleIndex++;
    Serial.printf("{\"timestamp\":%lu,\"red\":%lu,\"ir\":%lu}\n", (unsigned long)ms, (unsigned long)red, (unsigned long)ir);
  }
}
