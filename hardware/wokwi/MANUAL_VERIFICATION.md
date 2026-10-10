# Wokwi manual verification (status: NOT RUN)

Nothing here has been executed yet: I2C detection, MAX30102 detection, RED/IR acquisition, the JSON stream, Web Serial / Live Monitor and
CSV recording are all **NOT VERIFIED**. The chip emits a *deterministic synthetic waveform for simulator/integration testing only*; it is not
physiological, participant, clinical or research data. Wokwi serial output is not a physical COM port, so browser Web Serial is **NOT TESTED**.

1. Open the existing Wokwi project.
2. Replace the project files with `diagram.json`, `max-30102.chip.json`, `max-30102.chip.c` and `libraries.txt` from this folder.
3. Copy `diagnostics/i2c_diagnostic.ino` into the active sketch as `sketch.ino`.
4. Start the simulation.
5. Open the Serial Monitor.
6. Record the exact output.
7. Expected:
   ```
   I2C device found at 0x57
   PART ID (reg 0xFF) = 0x15
   MAX30102 I2C TEST: PASS
   ```
8. Expected next: `RED=…` and `IR=…` lines that are non-zero and not all identical.
9. Stop the simulation.
10. Restore the final `sketch.ino` from this folder.
11. Run again.
12. Expected: the Serial Monitor shows only lines like `{"timestamp":0,"red":60123,"ir":90456}` (one JSON object per line, 115200 baud).

If the chip fails to build, copy the build error text; if a step differs from the expected output, copy the exact serial text.
