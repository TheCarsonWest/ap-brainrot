import os
import sys
import math
import numpy as np
try:
    import cupy as cp
    CUPY_AVAILABLE = True
except ImportError:
    cp = np
    CUPY_AVAILABLE = False
from PIL import Image
from scipy.io import wavfile
import concurrent.futures

def get_pause_segments(wav_path, pause_thresh=0.05, min_pause_len=0.2):
    sr, data = wavfile.read(wav_path)
    if data.ndim > 1:
        data = data.mean(axis=1)  # mono
    # Move data to GPU if possible
    data_cp = cp.asarray(data)
    data_cp = data_cp / cp.max(cp.abs(data_cp))
    frame_size = int(0.02 * sr)
    hop = frame_size
    energies = cp.array([
        cp.sqrt(cp.mean(data_cp[i:i+frame_size]**2))
        for i in range(0, len(data)-frame_size, hop)
    ])
    pauses = energies < pause_thresh
    pauses = cp.asnumpy(pauses)  # back to numpy for Python logic
    pause_segments = []
    start = 0
    in_pause = False
    for i, p in enumerate(pauses):
        t = i * hop / sr
        if p and not in_pause:
            in_pause = True
            pause_start = t
            if pause_start > start:
                pause_segments.append((start, pause_start))
        elif not p and in_pause:
            in_pause = False
            start = t
    if start < len(data)/sr:
        pause_segments.append((start, len(data)/sr))
    return pause_segments

def get_avg_volumes(wav_path, segments):
    sr, data = wavfile.read(wav_path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    data_cp = cp.asarray(data)
    data_cp = data_cp / cp.max(cp.abs(data_cp))
    volumes = []
    for start, end in segments:
        s = int(start * sr)
        e = int(end * sr)
        if e > s:
            vol = cp.sqrt(cp.mean(data_cp[s:e]**2))
            vol = float(vol.get()) if CUPY_AVAILABLE else float(vol)
        else:
            vol = 0
        volumes.append(vol)
    return volumes

def generate_frame(args):
    i, t, segment_idx, volumes, max_vol, img, W, H, scale_coeff, segments, frame_times, output_dir, scale_base = args
    # Find which segment this frame is in
    while segment_idx < len(segments) and t > segments[segment_idx][1]:
        segment_idx += 1
    # Always assign vol based on the current segment
    if segment_idx < len(volumes):
        vol = volumes[segment_idx]
    else:
        vol = volumes[-1]
    norm_vol = vol / max_vol

    # Bounce only when normalized volume is above threshold
    bounce_amplitude = 25
    bounce_freq = 5
    bounce_threshold = 0.1
    if vol > bounce_threshold:
        bounce = -abs(vol) * bounce_amplitude * abs(math.sin(t * bounce_freq))
    else:
        bounce = 0

    scale = scale_base + scale_coeff * norm_vol
    """
      The image is 500 pixels tall, 
      The volume rnages usually from 0 to 0.25, 
      and the subtitles are at around y=600, 
      so we need to keep the image under that
    """

    x = int(W/2 - (img.width * scale) / 2+math.sin(t) * 10)
    y = int(H - (img.height * scale) + bounce+math.cos(t)+20)+50

    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    img_resized = img.resize((int(img.width * scale), int(img.height * scale)), resample=Image.BICUBIC)
    frame.paste(img_resized, (x, y), img_resized)

    # --- Render volume value in top left corner ---
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(frame)
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except Exception:
        font = ImageFont.load_default()
    draw.text((10, 10), f"vol: {vol:.4f}", fill=(255,255,255,255), font=font)
    # --- end volume render ---

    frame.save(os.path.join(output_dir, f"frame_{i:04d}.png"))

image_path = sys.argv[1]  # ./assets/character/image.png
output_dir = sys.argv[2]  # ./output/some_script/frames
wav_path = sys.argv[3]    # ./output/some_script/audio.wav

# Get duration from wav file
sr, data = wavfile.read(wav_path)
duration = len(data) / sr

fps = 30
scale_base = 0.75 
 # Base scale of the image
scale_coeff = 0.25 # How much the image scales with volume

os.makedirs(output_dir, exist_ok=True)

# Load original image
img = Image.open(image_path).convert("RGBA")
# Scale image to 500 pixels tall
target_height = 500
aspect_ratio = img.width / img.height
target_width = int(target_height * aspect_ratio)
img = img.resize((target_width, target_height), resample=Image.BICUBIC)

W, H = 720, 1080  # match video size

num_frames = int(duration * fps)

# Get pause segments and average volumes
segments = get_pause_segments(wav_path)
volumes = get_avg_volumes(wav_path, segments)
if not volumes:
    volumes = [1.0]
max_vol = max(volumes) if max(volumes) > 0 else 1.0

# Map each frame to a segment
frame_times = np.linspace(0, duration, num_frames)
segment_idx = 0

# Prepare arguments for each frame
args_list = []
segment_idx = 0
for i, t in enumerate(frame_times):
    args_list.append((i, t, segment_idx, volumes, max_vol, img, W, H, scale_coeff, segments, frame_times, output_dir,scale_base))

# Use ThreadPoolExecutor for multithreading (limit to 5 workers)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
    list(executor.map(generate_frame, args_list))