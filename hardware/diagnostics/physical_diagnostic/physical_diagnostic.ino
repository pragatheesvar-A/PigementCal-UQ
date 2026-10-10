/*
 * PigmentCal-UQ — PHYSICAL ESP32 + MAX30102 first-bring-up diagnostic (human-readable text, NOT the Live Monitor protocol).
 *
 * Checks, in this order, and prints what it actually observes:
 *   1. I2C scan                      -> which addresses answer
 *   2. PART ID register 0xFF         -> a genuine MAX30102 / MAX30105 answers 0x15
 *   3. sensor initialisation         -> same settings as esp32_max30102.ino
 *   4. raw RED / IR FIFO values      -> printed ~5 times per second for ~15 s, then a min/max summary
 * No SpO2 algorithm, no JSON. Flash esp32_max30102.ino afterwards for the Live Monitor.
 *
 * Board: ESP32 Dev Module · Library: "SparkFun MAX3010x Pulse and Proximity Sensor Library" · Serial Monitor: 115200 baud.
 * Wiring (3V3 / GND / SDA = GPIO21 / SCL = GPIO22) is in hardware/PHYSICAL_TEST_CHECKLIST.md.
 * This sketch has NOT been run by its author: nothing printed here is known in advance. Not a medical device.
 */
#include <Wire.h>
#include "MAX30105.h"

static const uint8_t SDA_PIN = 21, SCL_PIN = 22, ADDR = 0x57;
MAX30105 sensor;

static bool readReg(uint8_t reg, uint8_t &v) {
  Wire.beginTransmission(ADDR); Wire.write(reg);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom((int)ADDR, 1) != 1) return false;
  v = Wire.read(); return true;
}

static void halt(const char *why) {
  for (;;) { Serial.printf("STOPPED: %s\n", why); delay(2000); }
}

void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("=== PHYSICAL MAX30102 DIAGNOSTIC ===");
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  Serial.printf("1) I2C scan (SDA=GPIO%d, SCL=GPIO%d)\n", SDA_PIN, SCL_PIN);
  int found = 0; bool at57 = false;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { Serial.printf("   I2C device found at 0x%02X\n", a); found++; if (a == ADDR) at57 = true; }
  }
  if (!found) halt("NO I2C DEVICE FOUND - check 3V3/GND/SDA/SCL wiring, the module's power pin and the cable");
  if (!at57) halt("devices answered, but none at 0x57 - the module is not at the expected MAX30102 address");

  Serial.println("2) PART ID register 0xFF");
  uint8_t id = 0;
  if (!readReg(0xFF, id)) halt("0x57 acknowledged but the PART ID read failed");
  Serial.printf("   PART ID = 0x%02X (a genuine MAX30102 / MAX30105 reports 0x15)\n", id);
  if (id != 0x15) halt("PART ID is not 0x15 - this is not the expected sensor, or the bus is unreliable");

  Serial.println("3) sensor initialisation");
  if (!sensor.begin(Wire, I2C_SPEED_FAST)) halt("MAX3010x library could not initialise the sensor");
  sensor.setup(0x3F, 4, 2, 400, 411, 16384);     // same settings as esp32_max30102.ino: red+IR, 400 sps averaged by 4 -> 100 Hz
  Serial.println("   initialised. Place a fingertip gently on the sensor, then lift it off after a few seconds.");

  Serial.println("4) raw FIFO values (counts, 18-bit max 262143)");
  uint32_t redMin = 0xFFFFFFFF, redMax = 0, irMin = 0xFFFFFFFF, irMax = 0, n = 0, lastPrint = 0;
  uint32_t start = millis();
  while (millis() - start < 15000) {
    sensor.check();
    while (sensor.available()) {
      uint32_t red = sensor.getFIFORed(), ir = sensor.getFIFOIR();
      sensor.nextSample();
      n++;
      if (red < redMin) redMin = red; if (red > redMax) redMax = red;
      if (ir < irMin) irMin = ir;     if (ir > irMax) irMax = ir;
      if (millis() - lastPrint >= 200) { lastPrint = millis(); Serial.printf("   RED=%lu IR=%lu\n", (unsigned long)red, (unsigned long)ir); }
    }
  }
  Serial.printf("SUMMARY: %lu samples in 15 s (about %lu per second)\n", (unsigned long)n, (unsigned long)(n / 15));
  if (n == 0) { Serial.println("RESULT: FAIL - no samples were read from the FIFO"); return; }
  Serial.printf("   RED min=%lu max=%lu | IR min=%lu max=%lu\n", (unsigned long)redMin, (unsigned long)redMax, (unsigned long)irMin, (unsigned long)irMax);
  bool nonzero = redMax > 0 && irMax > 0, changing = (redMax > redMin) && (irMax > irMin);
  Serial.printf("   non-zero: %s | changing: %s\n", nonzero ? "yes" : "NO", changing ? "yes" : "NO");
  Serial.println(nonzero && changing ? "RESULT: sensor path works (I2C, PART ID, FIFO). This is not a measurement validation."
                                     : "RESULT: FAIL - values are zero or constant; check the finger/LED light path, power and wiring");
}

void loop() {}
