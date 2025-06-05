import os
import sys
import math
import re
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
from typing import List, Dict, Tuple
from google_images_search import GoogleImagesSearch

###############################
# --- Subtitle & Script Alignment ---
###############################

def timestamp_to_seconds(ts: str) -> float:
    h, m, s_ms = ts.split(':')
    s, ms = s_ms.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
def parse_srt_words(srt_text: str) -> tuple[List[str], List[float]]:
    entries = re.findall(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> .*?\n(.*?)\n', srt_text, re.DOTALL)
    words: List[str] = []
    timestamps: List[float] = []
    for _, timecode, content in entries:
        ts = timestamp_to_seconds(timecode)
        for w in re.findall(r"\w[\w']*", re.sub(r'[^\w\s\']', '', content)):
            words.append(w.lower())
            timestamps.append(ts)
    return words, timestamps

def tokenize_script(script: str) -> tuple[List[str], Dict[int, str], Dict[int, int]]:
    tokens: List[str] = []
    trigger_words: Dict[int, str] = {}
    token_to_line: Dict[int, int] = {}
    lines = script.strip().splitlines()
    pending_trigger: str | None = None

    for line_idx, line in enumerate(lines):
        line = line.strip()
        if line.startswith("{{") and line.endswith("}}"):
            pending_trigger = re.sub(r'[{}]', '', line).strip()
            continue
        if line:
            for w in re.findall(r"\w[\w']*", re.sub(r'[^\w\s\']', '', line)):
                w_lc = w.lower()
                idx = len(tokens)
                tokens.append(w_lc)
                token_to_line[idx] = line_idx
                if pending_trigger is not None:
                    trigger_words[idx] = pending_trigger
                    pending_trigger = None
    return tokens, trigger_words, token_to_line

def align_tokens_to_transcript(
    script_tokens: List[str],
    transcript_tokens: List[str],
    transcript_times: List[float]
) -> Dict[int, float]:
    mapping: Dict[int, float] = {}
    prev_time: float = 0.0
    j = 0

    for i, token in enumerate(script_tokens):
        matched = False
        for k in range(j, len(transcript_tokens)):
            if token == transcript_tokens[k]:
                prev_time = transcript_times[k]
                mapping[i] = prev_time
                j = k + 1
                matched = True
                break
        if not matched:
            # Advance timestamp slightly to avoid stalling
            mapping[i] = prev_time + 0.2  # Larger increment for smoother progression
            j = min(j + 1, len(transcript_tokens) - 1)
    return mapping

def get_trigger_intervals(
    script: str,
    srt_text: str,
    default_image_duration: float = 10.0
) -> List[tuple[float, float, str]]:
    script_tokens, trigger_word_locations, token_to_line = tokenize_script(script)
    transcript_tokens, transcript_times = parse_srt_words(srt_text)
    token_timestamp_map = align_tokens_to_transcript(script_tokens, transcript_tokens, transcript_times)
    
    line_to_tokens: Dict[int, List[int]] = {}
    for tidx, lidx in token_to_line.items():
        line_to_tokens.setdefault(lidx, []).append(tidx)

    intervals: List[tuple[float, float, str]] = []
    sorted_triggers = sorted(trigger_word_locations.items(), key=lambda x: x[0])
    
    for i, (tok_idx, prompt) in enumerate(sorted_triggers):
        line_idx = token_to_line[tok_idx]
        start_line = line_idx  # Line with the first token after {{prompt}}

        # Use first token of start_line for start_ts
        if start_line in line_to_tokens:
            start_ts = token_timestamp_map.get(min(line_to_tokens[start_line]), 0.0)
        else:
            continue

        # Set end_ts to start_ts of next prompt, or default duration
        if i < len(sorted_triggers) - 1:
            next_tok_idx = sorted_triggers[i + 1][0]
            next_line_idx = token_to_line[next_tok_idx]
            if next_line_idx in line_to_tokens:
                end_ts = token_timestamp_map.get(min(line_to_tokens[next_line_idx]), None)
            else:
                end_ts = None
        else:
            end_ts = None

        if end_ts is None or end_ts <= start_ts:
            end_ts = start_ts + default_image_duration

        intervals.append((start_ts, end_ts, prompt))

    # Extend last interval to audio duration if available
    if intervals and 'duration' in globals():
        intervals[-1] = (intervals[-1][0], max(intervals[-1][1], duration), intervals[-1][2])

    return intervals


###############################
# --- Image Search Utility ---
###############################

def image_search_and_cache(prompt: str, cache_dir: str) -> Image.Image:
    """
    Use Google-Images-Search to fetch one image for the prompt, save locally, and return as PIL Image.
    Assumes GCS_API_KEY and GCS_CX are set in the environment.
    """
    os.makedirs(cache_dir, exist_ok=True)
    fname = re.sub(r"[^a-zA-Z0-9_-]", "_", prompt) + ".jpg"
    local_path = os.path.join(cache_dir, fname)
    if os.path.isfile(local_path):
        return Image.open(local_path).convert("RGBA")

    gis = GoogleImagesSearch("AIzaSyBqOeFLTdxVZ61mZZ3jjQO1FBL7fXz9IQc", 'f26a3684236594ae5')
    search_params = {
        'q': prompt,
        'num': 1,
        'safe': 'medium',
        'fileType': 'jpg|png',
        'imgType': 'photo',
        'imgSize': 'medium',
    }
    gis.search(search_params=search_params)
    results = gis.results()
    if not results:
        raise RuntimeError(f"No valid images found for prompt: {prompt}")
    raw_data = results[0].get_raw_data()
    if not raw_data:
        raise RuntimeError(f"Downloaded image data is invalid for prompt: {prompt}")
    with open(local_path, "wb") as f:
        f.write(raw_data)
    return Image.open(local_path).convert("RGBA")

###############################
# --- Main Frame Generation ---
###############################

def get_pause_segments(wav_path: str, pause_thresh=0.05, min_pause_len=0.2) -> List[tuple[float, float]]:
    sr, data = wavfile.read(wav_path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    data_cp = cp.asarray(data)
    data_cp = data_cp / cp.max(cp.abs(data_cp))
    frame_size = int(0.02 * sr)
    hop = frame_size

    energies = cp.array([
        cp.sqrt(cp.mean(data_cp[i:i+frame_size]**2))
        for i in range(0, len(data) - frame_size, hop)
    ])
    pauses = energies < pause_thresh
    pauses = cp.asnumpy(pauses)

    pause_segments: List[tuple[float, float]] = []
    start = 0.0
    in_pause = False
    for i, p in enumerate(pauses):
        t = i * hop / sr
        if p and not in_pause:
            in_pause = True
            p_start = t
            if p_start > start:
                pause_segments.append((start, p_start))
        elif not p and in_pause:
            in_pause = False
            start = t

    if start < len(data) / sr:
        pause_segments.append((start, len(data) / sr))
    return pause_segments

def get_avg_volumes(wav_path: str, segments: List[tuple[float, float]]) -> List[float]:
    sr, data = wavfile.read(wav_path)
    if data.ndim > 1:
        data = data.mean(axis=1)
    data_cp = cp.asarray(data)
    data_cp = data_cp / cp.max(cp.abs(data_cp))

    volumes: List[float] = []
    for start, end in segments:
        s = int(start * sr)
        e = int(end * sr)
        if e > s:
            vol = cp.sqrt(cp.mean(data_cp[s:e]**2))
            vol = float(vol.get()) if CUPY_AVAILABLE else float(vol)
        else:
            vol = 0.0
        volumes.append(vol)
    return volumes

def generate_frame(args) -> int:
    """
    args is a tuple:
      (i, t, segment_idx, volumes, max_vol, bottom_img, trigger_images, W, H, scale_coeff, segments, frame_times, output_dir, scale_base)
    Returns updated segment_idx (not strictly required by multithreading but kept for consistency).
    """
    (i, t, segment_idx, volumes, max_vol, bottom_img, trigger_images, W, H, scale_coeff,
     segments, frame_times, output_dir, scale_base) = args

    # --- Find current volume segment ---
    while segment_idx < len(segments) and t > segments[segment_idx][1]:
        segment_idx += 1
    if segment_idx < len(volumes):
        vol = volumes[segment_idx]
    else:
        vol = volumes[-1] if volumes else 0.0
    norm_vol = vol / max_vol if max_vol > 0 else 0.0

    # --- Compute bounce for bottom character ---
    bounce_amplitude = 25
    bounce_freq = 5
    bounce_threshold = 0.1
    if vol > bounce_threshold:
        bounce = -abs(vol) * bounce_amplitude * abs(math.sin(t * bounce_freq))
    else:
        bounce = 0.0

    # --- Scale bottom image based on volume ---
    scale = scale_base + scale_coeff * norm_vol
    x_bot = int(W/2 - (bottom_img.width * scale) / 2 + math.sin(t) * 10)
    y_bot = int(H - (bottom_img.height * scale) + bounce + math.cos(t) + 20) + 50

    # --- Create frame and paste bottom image ---
    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bottom_resized = bottom_img.resize(
        (int(bottom_img.width * scale), int(bottom_img.height * scale)),
        resample=Image.BICUBIC
    )
    frame.paste(bottom_resized, (x_bot, y_bot), bottom_resized)

    # --- Overlay trigger image in top third if within any interval ---
    for (start_ts, end_ts, top_img) in trigger_images:
        if start_ts <= t <= end_ts:
            # Center horizontally; vertically within top H/3
            img_w, img_h = top_img.size
            # If width exceeds frame width, scale down
            if img_w > W:
                ratio = W / img_w
                new_w = W
                new_h = int(img_h * ratio)
                top_img = top_img.resize((new_w, new_h), resample=Image.BICUBIC)
                img_w, img_h = top_img.size
            x_top = int((W - img_w) / 2)
            y_top = int((H / 3 - img_h) / 2)
            frame.paste(top_img, (x_top, y_top), top_img)
            break  # only one trigger per frame

    frame.save(os.path.join(output_dir, f"frame_{i:04d}.png"))
    return segment_idx

if __name__ == "__main__":
    """
    Usage:
      python this_script.py \
        path/to/script.txt \
        path/to/subtitles.srt \
        path/to/character.png \
        path/to/audio.wav \
        path/to/output_frames \
        path/to/cache_dir
    """
    if len(sys.argv) != 7:
        print("Usage: python this_script.py <script.txt> <subtitles.srt> "
              "<character.png> <audio.wav> <output_dir> <cache_dir>")
        sys.exit(1)

    script_path = sys.argv[1]
    srt_path = sys.argv[2]
    bottom_img_path = sys.argv[3]
    wav_path = sys.argv[4]
    output_dir = sys.argv[5]
    cache_dir = sys.argv[6]

    # --- Read script & subtitles ---
    with open(script_path, "r", encoding="utf-8") as f:
        script_text = f.read()
    with open(srt_path, "r", encoding="utf-8") as f:
        srt_text = f.read()

    # --- Compute trigger intervals from script + SRT ---
    trigger_intervals = get_trigger_intervals(script_text, srt_text, default_image_duration=1.5)
    print(f"Found {len(trigger_intervals)} trigger intervals.")
    print("Trigger intervals:", trigger_intervals)
    # --- Preload & resize trigger images to fit top third ---
    trigger_images_resized: List[tuple[float, float, Image.Image]] = []
    for start, end, prompt in trigger_intervals:
        try:
            img = image_search_and_cache(prompt, cache_dir)
        except Exception:
            continue
        trigger_images_resized.append((start, end, img))

    # --- Load bottom character image ---
    bottom_img = Image.open(bottom_img_path).convert("RGBA")
    target_height = 500
    aspect_ratio = bottom_img.width / bottom_img.height
    target_width = int(target_height * aspect_ratio)
    bottom_img = bottom_img.resize((target_width, target_height), resample=Image.BICUBIC)

    # --- Audio processing ---
    sr, data = wavfile.read(wav_path)
    duration = len(data) / sr

    fps = 30
    scale_base = 0.75
    scale_coeff = 0.25
    W, H = 720, 1080

    os.makedirs(output_dir, exist_ok=True)

    # --- Compute pause segments & volumes ---
    segments = get_pause_segments(wav_path)
    volumes = get_avg_volumes(wav_path, segments)
    if not volumes:
        volumes = [1.0]
    max_vol = max(volumes) if max(volumes) > 0 else 1.0

    # --- Resize each trigger image to height ≤ H/3 ---
    resized_triggers: List[tuple[float, float, Image.Image]] = []
    max_top_height = H // 3
    for start, end, img in trigger_images_resized:
        w0, h0 = img.size
        if h0 > max_top_height:
            ratio = max_top_height / h0
            new_h = max_top_height
            new_w = int(w0 * ratio)
            img = img.resize((new_w, new_h), resample=Image.BICUBIC)
        resized_triggers.append((start, end, img))
    trigger_images = resized_triggers

    # --- Prepare frame times and args ---
    num_frames = int(duration * fps)
    frame_times = np.linspace(0, duration, num_frames)
    args_list = []
    segment_idx = 0
    for i, t in enumerate(frame_times):
        args_list.append((
            i, t, segment_idx, volumes, max_vol, bottom_img,
            trigger_images, W, H, scale_coeff,
            segments, frame_times, output_dir, scale_base
        ))

    # --- Generate frames in parallel ---
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(generate_frame, args_list))

    print("Frame generation complete.")
