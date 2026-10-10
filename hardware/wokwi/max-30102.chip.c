// Wokwi custom chip: MAX30102 register-level SIMULATION (I2C slave at 0x57).
//
// Deterministic synthetic waveform for simulator/integration testing only.
//
// Purpose: lets the ESP32 firmware (SparkFun MAX3010x library) be exercised in Wokwi: I2C scan, PART ID, FIFO read.
// It models only the registers the library uses. The RED/IR counts are a SYNTHETIC, DETERMINISTIC test waveform
// (a pulsatile baseline plus a little fixed pseudo-noise). They are NOT physiological measurements, carry no
// SpO2 / pigmentation information and must never be used as research data.
//
// SPDX-License-Identifier: MIT

#include "wokwi-api.h"
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define I2C_ADDRESS     0x57
#define FIFO_DEPTH      32

#define REG_INT_STATUS1 0x00
#define REG_FIFO_WR_PTR 0x04
#define REG_FIFO_OVF    0x05
#define REG_FIFO_RD_PTR 0x06
#define REG_FIFO_DATA   0x07
#define REG_FIFO_CONFIG 0x08
#define REG_MODE_CONFIG 0x09
#define REG_SPO2_CONFIG 0x0A
#define REG_REV_ID      0xFE
#define REG_PART_ID     0xFF

#define PART_ID_VALUE   0x15
#define REV_ID_VALUE    0x03
#define MODE_RESET_BIT  0x40
#define PPG_RDY_BIT     0x40
#define ROLLOVER_BIT    0x10

typedef struct {
  uint8_t  reg[256];
  uint8_t  fifo[FIFO_DEPTH][9];   // up to 3 channels x 3 bytes
  uint8_t  pointer;               // I2C register pointer
  bool     first_byte;            // the next written byte is the register pointer
  uint8_t  data_idx;              // byte index inside the FIFO sample being read
  uint32_t sample_no;
  uint32_t lcg;
  timer_t  timer;
} chip_state_t;

static void reset_registers(chip_state_t *c) {
  memset(c->reg, 0, sizeof(c->reg));
  c->reg[REG_REV_ID]  = REV_ID_VALUE;
  c->reg[REG_PART_ID] = PART_ID_VALUE;
  c->data_idx = 0;
}

static int active_channels(const chip_state_t *c) {
  switch (c->reg[REG_MODE_CONFIG] & 0x07) {
    case 0x02: return 1;   // red only
    case 0x03: return 2;   // red + IR
    case 0x07: return 3;   // multi-LED (the third channel is a constant here)
    default:   return 0;   // not sampling
  }
}

// Smooth periodic wave in [-1, 1] without libm: parabolic sine approximation.
static float psin(float q) {
  q -= (float)(int)q;
  float x = q * 2.0f - 1.0f;
  float ax = x < 0 ? -x : x;
  return 4.0f * x * (1.0f - ax);
}

static uint32_t next_noise(chip_state_t *c, uint32_t span) {      // deterministic pseudo-noise in [0, span)
  c->lcg = c->lcg * 1664525u + 1013904223u;
  return (c->lcg >> 16) % span;
}

static void push_sample(chip_state_t *c) {
  int n = active_channels(c);
  if (n == 0) return;
  uint8_t wr = c->reg[REG_FIFO_WR_PTR] & 0x1F, rd = c->reg[REG_FIFO_RD_PTR] & 0x1F;
  if (((wr + 1) & 0x1F) == rd) {                                   // FIFO full
    if (c->reg[REG_FIFO_CONFIG] & ROLLOVER_BIT) {
      c->reg[REG_FIFO_RD_PTR] = (rd + 1) & 0x1F;                   // overwrite the oldest sample
    } else {
      if (c->reg[REG_FIFO_OVF] < 0x1F) c->reg[REG_FIFO_OVF]++;
      return;                                                      // drop the new sample
    }
  }
  c->sample_no++;
  float phase = (float)(c->sample_no % 100u) / 100.0f;             // 1 pulse per 100 output samples (test waveform)
  float pulse = 0.7f * psin(phase) + 0.3f * psin(2.0f * phase + 0.25f);
  uint32_t vals[3];
  vals[0] = (uint32_t)(60000.0f + 1200.0f * pulse) + next_noise(c, 40);   // RED, 18-bit counts (synthetic)
  vals[1] = (uint32_t)(90000.0f + 3000.0f * pulse) + next_noise(c, 40);   // IR,  18-bit counts (synthetic)
  vals[2] = 20000u + next_noise(c, 40);
  for (int i = 0; i < n; i++) {
    c->fifo[wr][i * 3 + 0] = (vals[i] >> 16) & 0x03;
    c->fifo[wr][i * 3 + 1] = (vals[i] >> 8) & 0xFF;
    c->fifo[wr][i * 3 + 2] = vals[i] & 0xFF;
  }
  c->reg[REG_FIFO_WR_PTR] = (wr + 1) & 0x1F;
  c->reg[REG_INT_STATUS1] |= PPG_RDY_BIT;
}

// Output period from SPO2_CONFIG (sample rate) and FIFO_CONFIG (averaging).
static void restart_timer(chip_state_t *c) {
  static const uint32_t rates[8] = {50, 100, 200, 400, 800, 1000, 1600, 3200};
  uint32_t rate = rates[(c->reg[REG_SPO2_CONFIG] >> 2) & 0x07];
  uint32_t avg = 1u << ((c->reg[REG_FIFO_CONFIG] >> 5) & 0x07);
  if (avg > 32) avg = 32;
  uint32_t out_hz = rate / avg;
  if (out_hz == 0) out_hz = 1;
  timer_stop(c->timer);
  timer_start(c->timer, 1000000u / out_hz, true);
}

static void on_sample_timer(void *user_data) { push_sample((chip_state_t *)user_data); }

static bool on_connect(void *user_data, uint32_t address, bool read) {
  chip_state_t *c = (chip_state_t *)user_data;
  (void)address;
  if (!read) c->first_byte = true;      // a write transaction starts with the register pointer; a read keeps the pointer
  return true;
}

static uint8_t on_read(void *user_data) {
  chip_state_t *c = (chip_state_t *)user_data;
  uint8_t r = c->pointer;
  if (r == REG_FIFO_DATA) {             // the pointer stays on FIFO_DATA; bytes stream out sample by sample
    uint8_t wr = c->reg[REG_FIFO_WR_PTR] & 0x1F, rd = c->reg[REG_FIFO_RD_PTR] & 0x1F;
    int n = active_channels(c);
    if (rd == wr || n == 0) return 0;   // empty
    uint8_t b = c->fifo[rd][c->data_idx++];
    if (c->data_idx >= n * 3) { c->data_idx = 0; c->reg[REG_FIFO_RD_PTR] = (rd + 1) & 0x1F; }
    return b;
  }
  uint8_t v = c->reg[r];
  if (r == REG_INT_STATUS1) c->reg[REG_INT_STATUS1] = 0;     // read-to-clear
  c->pointer = (uint8_t)(c->pointer + 1);
  return v;
}

static bool on_write(void *user_data, uint8_t data) {
  chip_state_t *c = (chip_state_t *)user_data;
  if (c->first_byte) { c->pointer = data; c->first_byte = false; return true; }
  uint8_t r = c->pointer;
  if (r == REG_PART_ID || r == REG_REV_ID || r == REG_FIFO_DATA) return true;      // read-only
  if (r == REG_MODE_CONFIG) {
    if (data & MODE_RESET_BIT) { reset_registers(c); restart_timer(c); c->pointer = REG_MODE_CONFIG; return true; }   // reset bit self-clears
    c->reg[r] = data;
  } else if (r == REG_FIFO_WR_PTR || r == REG_FIFO_RD_PTR) {
    c->reg[r] = data & 0x1F;
    c->data_idx = 0;
  } else {
    c->reg[r] = data;
  }
  if (r == REG_SPO2_CONFIG || r == REG_FIFO_CONFIG) restart_timer(c);
  c->pointer = (uint8_t)(c->pointer + 1);
  return true;
}

static void on_disconnect(void *user_data) { (void)user_data; }

void chip_init(void) {
  chip_state_t *c = (chip_state_t *)calloc(1, sizeof(chip_state_t));
  c->lcg = 12345u;
  reset_registers(c);

  const timer_config_t tcfg = { .callback = on_sample_timer, .user_data = c };
  c->timer = timer_init(&tcfg);
  restart_timer(c);                                                // default rate until the firmware configures the sensor

  const i2c_config_t i2c = {
    .address = I2C_ADDRESS,
    .scl = pin_init("SCL", INPUT_PULLUP),
    .sda = pin_init("SDA", INPUT_PULLUP),
    .connect = on_connect, .read = on_read, .write = on_write, .disconnect = on_disconnect,
    .user_data = c,
  };
  i2c_init(&i2c);
}
