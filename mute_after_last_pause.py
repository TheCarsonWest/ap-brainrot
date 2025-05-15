import subprocess
import re
import sys
import os

def get_last_silence_end(ffmpeg_log):
    silence_ends = [float(m.group(1)) for m in re.finditer(r'silence_end: ([\d\.]+)', ffmpeg_log)]
    return silence_ends[-1] if silence_ends else None

def mute_after_last_pause(input_file):
    cmd = [
        "ffmpeg", "-i", input_file,
        "-af", "silencedetect=noise=-30dB:d=0.25",
        "-f", "null", "-"
    ]
    proc = subprocess.run(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    ffmpeg_log = proc.stderr

    last_silence_end = get_last_silence_end(ffmpeg_log)
    if last_silence_end is None:
        print(f"No silence detected in {input_file}. Skipping.")
        return

    base, ext = os.path.splitext(input_file)
    output_file = f"{base}_s{ext}"

    mute_cmd = [
        "ffmpeg", "-i", input_file,
        "-af", f"volume=enable='gte(t,{last_silence_end})':volume=0",
        "-c:a", "libmp3lame", "-y", output_file
    ]
    subprocess.run(mute_cmd)
    print(f"Muted audio after {last_silence_end} seconds. Output: {output_file}")

def process_all_mp3s(root_dir):
    for dirpath, _, filenames in os.walk(root_dir):
        for filename in filenames:
            if filename.lower().endswith('.mp3'):
                input_file = os.path.join(dirpath, filename)
                mute_after_last_pause(input_file)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python mute_after_last_pause.py <input_dir>")
    else:
        process_all_mp3s(sys.argv[1])
