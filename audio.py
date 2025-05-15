import sys
import os
import numpy as np
import noisereduce as nr
from pedalboard import Pedalboard, Gain, NoiseGate, Compressor, LowShelfFilter
from pedalboard.io import AudioFile

def main():
    if len(sys.argv) < 2:
        print("Usage: python audio.py <input_wav_path>")
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.isfile(input_path):
        print(f"File not found: {input_path}")
        sys.exit(1)

    # Load audio file
    with AudioFile(input_path, 'r') as f:
        audio = f.read(f.frames)
        samplerate = f.samplerate
        num_channels = f.num_channels
    print(f"Loaded audio: shape={audio.shape}, dtype={audio.dtype}, samplerate={samplerate}, channels={num_channels}")

    # Noise reduction
    if num_channels > 1:
        reduced_noise = np.zeros_like(audio)
        for ch in range(num_channels):
            reduced_noise[:, ch] = nr.reduce_noise(
                y=audio[:, ch], sr=samplerate, stationary=True, prop_decrease=0.75
            )
    else:
        reduced_noise = nr.reduce_noise(
            y=audio, sr=samplerate, stationary=True, prop_decrease=0.75
        )
        # Ensure shape is (frames, 1) for mono
        reduced_noise = reduced_noise.reshape(-1, 1)
    print(f"After noise reduction: shape={reduced_noise.shape}, dtype={reduced_noise.dtype}")

    # Enhancing through pedalboard
    board = Pedalboard([
        NoiseGate(threshold_db=-30, ratio=1.5, release_ms=250),
        Compressor(threshold_db=-16, ratio=4),
        LowShelfFilter(cutoff_frequency_hz=400, gain_db=10, q=1),
        Gain(gain_db=2)
    ])
    effected = board(reduced_noise, samplerate)
    print(f"After pedalboard: shape={effected.shape}, dtype={effected.dtype}")

    # Prepare output path
    base, ext = os.path.splitext(input_path)
    output_path = f"{base}_cleaned.wav"

    # Ensure output is float32 and in range [-1, 1]
    effected = np.clip(effected, -1.0, 1.0).astype(np.float32)
    # If mono, ensure shape is (frames, 1)
    if effected.ndim == 1:
        effected = effected.reshape(-1, 1)

    # Save cleaned audio
    with AudioFile(output_path, 'w', samplerate, effected.shape[1]) as f:
        f.write(effected)
    print(f"Saved audio: shape={effected.shape}, dtype={effected.dtype}")

    print(f"Cleaned audio saved to: {output_path}")

if __name__ == "__main__":
    main()
