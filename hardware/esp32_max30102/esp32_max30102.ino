/*
 * PigmentCal-UQ — ESP32 + MAX30102 streaming firmware
 *
 * Streams raw red and infrared PPG counts (and, optionally, an MPU-6050 accelerometer) over USB serial so the
 * browser (Live Monitor page, Web Serial) can compute signal quality, perfusion index, motion and a reliability
 * state in real time.
 *
 * This sketch does NOT compute SpO2 and is NOT a medical device. It only streams raw samples.
 *
 * Serial protocol (115200 baud by default), ONE JSON OBJECT PER LINE:
 *     # comment / status lines start with '#' (ignored by the app)
 *     {"timestamp":123456,"red":12345,"ir":23456}
 *     {"timestamp":123456,"red":12345,"ir":23456,"accelerometer_x":0.01,"accelerometer_y":0.02,"accelerometer_z":0.98}
 * timestamp (milliseconds) is a SAMPLE-COUNTER time (n * 1000 / SAMPLE_RATE_HZ), so timestamps are perfectly regular even though
 * the FIFO is read in bursts. It assumes the sensor really runs at SAMPLE_RATE_HZ.
 *
 * Wiring (ESP32 DevKit, I2C on the default pins):
 *     MAX30102  VIN -> 3V3   GND -> GND   SDA -> GPIO21   SCL -> GPIO22
 *     MPU-6050  VCC -> 3V3   GND -> GND   SDA -> GPIO21   SCL -> GPIO22   (optional, address 0x68)
 *
 * Libraries (Arduino Library Manager): "SparkFun MAX3010x Pulse and Proximity Sensor Library".
 * Board: "ESP32 Dev Module".
 *
 * NOTE: written without access to the hardware — it has not been compiled or run by the author of this repository.
 * Please test it on your board and report problems.
 */

#include <Wire.h>
#include "MAX30105.h"          // SparkFun library; also drives the MAX30102

// ---------------------------------------------------------------- configuration
#define SERIAL_BAUD        115200
#define SAMPLE_RATE_HZ     100     // output rate after averaging (must match the sensor setup below)
#define USE_MPU6050        1       // set to 0 if no accelerometer is connected
#define MPU_ADDR           0x68
#define FINGER_THRESHOLD   30000   // IR counts below this are reported as "no finger"

// MAX30102 setup: 400 samples/s internally, averaged by 4 -> 100 Hz
static const byte LED_BRIGHTNESS = 0x3F;   // 0..255; raise if IR is low, lower if it saturates (262143 = 18-bit max)
static const byte SAMPLE_AVERAGE = 4;
static const byte LED_MODE       = 2;      // 2 = red + IR
static const int  SENSOR_RATE    = 400;
static const int  PULSE_WIDTH    = 411;    // 18-bit resolution
static const int  ADC_RANGE      = 16384;

MAX30105 sensor;
static uint32_t sampleIndex = 0;
static uint32_t lastStatusMs = 0;

#if USE_MPU6050
// Raw MPU-6050 accelerometer read (±2 g range -> 16384 LSB per g)
static bool mpuInit() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);            // PWR_MGMT_1
  Wire.write(0x00);            // wake up
  return Wire.endTransmission() == 0;
}
static bool mpuRead(float &ax, float &ay, float &az) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);            // ACCEL_XOUT_H
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((int)MPU_ADDR, 6) != 6) return false;
  int16_t x = (Wire.read() << 8) | Wire.read();
  int16_t y = (Wire.read() << 8) | Wire.read();
  int16_t z = (Wire.read() << 8) | Wire.read();
  ax = x / 16384.0f; ay = y / 16384.0f; az = z / 16384.0f;
  return true;
}
static bool mpuOk = false;
#endif

void setup() {
  Serial.begin(SERIAL_BAUD);
  Wire.begin();                // SDA=21, SCL=22
  Wire.setClock(400000);
  delay(200);

  if (!sensor.begin(Wire, I2C_SPEED_FAST)) {
    while (true) {
      Serial.println("# ERROR: MAX30102 not found - check wiring and power");
      delay(1000);
    }
  }
  sensor.setup(LED_BRIGHTNESS, SAMPLE_AVERAGE, LED_MODE, SENSOR_RATE, PULSE_WIDTH, ADC_RANGE);

#if USE_MPU6050
  mpuOk = mpuInit();
  Serial.println(mpuOk ? "# MPU6050 ok" : "# WARNING: MPU6050 not found - streaming without accelerometer");
#endif
  Serial.printf("# PIGMENTCAL,v2-json,fs=%d,fields=timestamp,red,ir%s\n", SAMPLE_RATE_HZ,
#if USE_MPU6050
                mpuOk ? ",accelerometer_x,accelerometer_y,accelerometer_z" : ""
#else
                ""
#endif
  );
}

void loop() {
  sensor.check();                              // pull new samples from the sensor FIFO
  while (sensor.available()) {
    uint32_t red = sensor.getFIFORed();
    uint32_t ir  = sensor.getFIFOIR();
    sensor.nextSample();

    uint32_t ms = (uint32_t)(((uint64_t)sampleIndex * 1000ULL) / SAMPLE_RATE_HZ);
    sampleIndex++;

#if USE_MPU6050
    float ax, ay, az;
    if (mpuOk && mpuRead(ax, ay, az)) {
      Serial.printf("{\"timestamp\":%lu,\"red\":%lu,\"ir\":%lu,\"accelerometer_x\":%.3f,\"accelerometer_y\":%.3f,\"accelerometer_z\":%.3f}\n",
                    (unsigned long)ms, (unsigned long)red, (unsigned long)ir, ax, ay, az);
      continue;
    }
#endif
    Serial.printf("{\"timestamp\":%lu,\"red\":%lu,\"ir\":%lu}\n", (unsigned long)ms, (unsigned long)red, (unsigned long)ir);

    if (ir < FINGER_THRESHOLD && millis() - lastStatusMs > 1000) {
      lastStatusMs = millis();
      Serial.println("# no finger detected");
    }
  }
}
