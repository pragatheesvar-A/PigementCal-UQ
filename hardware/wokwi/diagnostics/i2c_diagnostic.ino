// TEMPORARY diagnostic for the Wokwi MAX30102 chip. Does NOT use the MAX3010x library. Paste into Wokwi's sketch.ino to test,
// then restore ../sketch.ino for the JSON stream. Output is human-readable text, not the Live Monitor protocol.
// Deterministic synthetic waveform for simulator/integration testing only.
// The RED/IR values come from the SIMULATED chip and are not physiological measurements.
#include <Wire.h>

static const uint8_t ADDR = 0x57;

static bool readReg(uint8_t reg, uint8_t &v) {
  Wire.beginTransmission(ADDR); Wire.write(reg);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom((int)ADDR, 1) != 1) return false;
  v = Wire.read(); return true;
}
static bool writeReg(uint8_t reg, uint8_t v) {
  Wire.beginTransmission(ADDR); Wire.write(reg); Wire.write(v);
  return Wire.endTransmission() == 0;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  Wire.setClock(400000);
  delay(200);
  Serial.println("=== MAX30102 I2C TEST ===");

  int found = 0;
  Serial.println("Scanning I2C bus...");
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { Serial.printf("I2C device found at 0x%02X\n", a); found++; }
  }
  if (!found) Serial.println("NO I2C DEVICE FOUND");

  uint8_t id = 0;
  bool ok = readReg(0xFF, id);
  Serial.printf("PART ID (reg 0xFF) = 0x%02X\n", ok ? id : 0);
  bool pass = ok && id == 0x15;
  Serial.println(pass ? "MAX30102 I2C TEST: PASS" : "MAX30102 I2C TEST: FAIL");
  if (!pass) return;

  // Direct FIFO access: reset, red+IR mode, 100 Hz, clear FIFO, then read samples.
  writeReg(0x09, 0x40); delay(10);
  writeReg(0x08, 0x00);        // no averaging
  writeReg(0x0A, 0x07);        // 100 Hz, 18-bit (value is only used by the simulation for the rate)
  writeReg(0x09, 0x03);        // red + IR
  writeReg(0x04, 0); writeReg(0x05, 0); writeReg(0x06, 0);
  delay(300);

  for (int k = 0; k < 8; k++) {
    uint8_t wr = 0, rd = 0; readReg(0x04, wr); readReg(0x06, rd);
    if (wr == rd) { Serial.println("FIFO empty"); delay(50); continue; }
    Wire.beginTransmission(ADDR); Wire.write(0x07); Wire.endTransmission();
    if (Wire.requestFrom((int)ADDR, 6) != 6) { Serial.println("FIFO read failed"); continue; }
    uint32_t red = 0, ir = 0;
    for (int i = 0; i < 3; i++) red = (red << 8) | Wire.read();
    for (int i = 0; i < 3; i++) ir  = (ir  << 8) | Wire.read();
    Serial.printf("RED=%lu IR=%lu\n", (unsigned long)(red & 0x3FFFF), (unsigned long)(ir & 0x3FFFF));
    delay(70);
  }
  Serial.println("RAW FIFO TEST DONE");
}

void loop() {}
