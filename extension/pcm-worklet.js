class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 16000;
    this.ratio = sampleRate / this.targetRate;
    this.pos = 0;
    this.out = [];
    this.chunk = 4096;
  }

  process(inputs) {
    const channels = inputs[0];
    if (!channels || !channels.length || !channels[0]) {
      return true;
    }
    const left = channels[0];
    const right = channels[1];
    const n = left.length;
    let pos = this.pos;
    while (pos < n) {
      const i0 = Math.floor(pos);
      const i1 = Math.min(i0 + 1, n - 1);
      const frac = pos - i0;
      let s = left[i0] + (left[i1] - left[i0]) * frac;
      if (right) {
        const r = right[i0] + (right[i1] - right[i0]) * frac;
        s = (s + r) * 0.5;
      }
      this.out.push(s);
      pos += this.ratio;
    }
    this.pos = pos - n;

    while (this.out.length >= this.chunk) {
      const slice = this.out.splice(0, this.chunk);
      const i16 = new Int16Array(slice.length);
      for (let i = 0; i < slice.length; i++) {
        const v = Math.max(-1, Math.min(1, slice[i]));
        i16[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
      }
      this.port.postMessage(i16.buffer, [i16.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor);
