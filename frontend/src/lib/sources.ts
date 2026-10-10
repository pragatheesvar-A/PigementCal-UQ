/** Live sample sources: USB serial (ESP32 + MAX30102), phone/webcam camera PPG, and replay of a recorded file. */

import { LineSplitter, dueCount, meanChannel, parsePacket, type PacketError, type Recording, type Sample } from "./acquisition";

export interface Callbacks {
  onSamples: (s: Sample[]) => void;
  onError: (e: Error) => void;
  onClosed?: () => void;
}

// ---------------------------------------------------------------- serial (Web Serial API: Chrome / Edge)
export interface SerialPortLike {
  open(o: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
  readable: ReadableStream<Uint8Array> | null;
}

export class SerialSource {
  private running = false;
  private reader: ReadableStreamDefaultReader<Uint8Array> | null = null;
  lines = 0;
  rejected = 0;
  /** Why lines were rejected, by reason. */
  errors: Partial<Record<PacketError, number>> = {};
  lastError = "";
  /** performance.now() of the last accepted sample (null until one arrives); used to detect a stalled sensor. */
  lastDataAt: number | null = null;
  recent: string[] = [];

  constructor(private port: SerialPortLike, private baud: number, private cb: Callbacks) {}

  async start() {
    await this.port.open({ baudRate: this.baud });
    this.running = true;
    void this.loop();
  }

  private async loop() {
    const dec = new TextDecoder();
    const split = new LineSplitter();
    try {
      while (this.running && this.port.readable) {
        this.reader = this.port.readable.getReader();
        try {
          for (;;) {
            const { value, done } = await this.reader.read();
            if (done) { this.running = false; break; }     // the stream ended (device unplugged / port closed): stop, do not spin
            const batch: Sample[] = [];
            for (const line of split.push(dec.decode(value, { stream: true }))) {
              const pk = parsePacket(line);
              if (pk.kind === "sample") { batch.push(pk.sample); this.lines++; }
              else if (pk.kind === "error") { this.rejected++; this.errors[pk.code] = (this.errors[pk.code] ?? 0) + 1; this.lastError = pk.message; }
              if (line.trim() !== "") { this.recent.push(line.trim().slice(0, 80)); if (this.recent.length > 5) this.recent.shift(); }
            }
            if (batch.length) { this.lastDataAt = performance.now(); this.cb.onSamples(batch); }
          }
        } finally { this.reader.releaseLock(); this.reader = null; }
        if (!this.running) break;
      }
    } catch (e) {
      if (this.running) this.cb.onError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      this.running = false;
      this.cb.onClosed?.();
    }
  }

  async stop() {
    this.running = false;
    try { await this.reader?.cancel(); } catch { /* already closed */ }
    try { await this.port.close(); } catch { /* already closed */ }
  }
}

// ---------------------------------------------------------------- camera PPG
export interface Frame { r: number; g: number; b: number }

export class CameraSource {
  private stream: MediaStream | null = null;
  private timer: number | null = null;
  torch = false;

  constructor(private video: HTMLVideoElement, private cb: Callbacks & { onFrame?: (f: Frame) => void }) {}

  async start() {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser cannot access a camera (it needs HTTPS or localhost).");
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 320 }, height: { ideal: 240 }, frameRate: { ideal: 30 } }, audio: false,
    });
    const track = this.stream.getVideoTracks()[0];
    try {   // use the flash as the light source where the device supports it
      const caps = track.getCapabilities?.() as { torch?: boolean } | undefined;
      if (caps?.torch) { await track.applyConstraints({ advanced: [{ torch: true } as MediaTrackConstraintSet] }); this.torch = true; }
    } catch { /* torch unavailable */ }
    this.video.srcObject = this.stream;
    this.video.muted = true;
    await this.video.play();
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 32;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    if (!ctx) throw new Error("Canvas is not available.");
    this.timer = window.setInterval(() => {
      if (this.video.readyState < 2) return;
      ctx.drawImage(this.video, 0, 0, 32, 32);
      const d = ctx.getImageData(0, 0, 32, 32).data;
      const f = { r: meanChannel(d, 32, 32, 0), g: meanChannel(d, 32, 32, 1), b: meanChannel(d, 32, 32, 2) };
      this.cb.onFrame?.(f);
      this.cb.onSamples([{ t: performance.now() / 1000, ir: f.r }]);     // one channel: mean red of the centre region
    }, 1000 / 30);
  }

  stop() {
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
    this.cb.onClosed?.();
  }
}

// ---------------------------------------------------------------- replay of a recording in real time
export class ReplaySource {
  private idx = 0;
  private startedAt = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  playing = false;

  constructor(private rec: Pick<Recording, "ir" | "red" | "accel">, private fs: number, private cb: Callbacks & { onEnd?: () => void }) {}

  get progress() { return this.idx / this.rec.ir.length; }
  get position() { return this.idx / this.fs; }

  play() {
    if (this.playing) return;
    this.playing = true;
    this.startedAt = performance.now() - (this.idx / this.fs) * 1000;     // resume where we paused
    this.timer = setInterval(() => this.tick(), 40);
  }

  pause() {
    this.playing = false;
    if (this.timer !== null) clearInterval(this.timer);
    this.timer = null;
  }

  restart() { this.pause(); this.idx = 0; this.play(); }

  private tick() {
    const n = dueCount(performance.now() - this.startedAt, this.fs, this.rec.ir.length);
    if (n > this.idx) {
      const batch: Sample[] = [];
      for (let i = this.idx; i < n; i++) {
        const s: Sample = { t: i / this.fs, ir: this.rec.ir[i] };
        if (this.rec.red) s.red = this.rec.red[i];
        if (this.rec.accel) s.accel = this.rec.accel[i];
        batch.push(s);
      }
      this.idx = n;
      this.cb.onSamples(batch);
    }
    if (this.idx >= this.rec.ir.length) { this.pause(); this.cb.onEnd?.(); }
  }

  stop() { this.pause(); this.idx = 0; this.cb.onClosed?.(); }
}
