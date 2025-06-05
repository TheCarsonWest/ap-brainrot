import os
import sys
import re
import json
import numpy as np
from PIL import Image
from typing import List, Dict, Tuple
from google_images_search import GoogleImagesSearch
import concurrent.futures
from scipy.io import wavfile

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
            mapping[i] = prev_time + 0.2
            j = min(j + 1, len(transcript_tokens) - 1)
    return mapping

def get_trigger_intervals(
    script: str,
    srt_text: str,
    default_image_duration: float = 1.5
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
        start_line = line_idx

        if start_line in line_to_tokens:
            start_ts = token_timestamp_map.get(min(line_to_tokens[start_line]), 0.0)
        else:
            continue

        if i < len(sorted_triggers) - 1:
            next_tok_idx = sorted_triggers[i + 1][0]
            next_line_idx = token_to_line[next_tok_idx]
            end_ts = token_timestamp_map.get(min(line_to_tokens.get(next_line_idx, [])), None)
        else:
            end_ts = None

        if end_ts is None or end_ts <= start_ts:
            end_ts = start_ts + default_image_duration

        intervals.append((start_ts, end_ts, prompt))

    return intervals

def image_search_and_cache(prompt: str, cache_dir: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    fname = re.sub(r"[^a-zA-Z0-9_-]", "_", prompt) + ".jpg"
    local_path = os.path.join(cache_dir, fname)
    if os.path.isfile(local_path):
        return local_path

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
    return local_path

def superimpose_frame(args):
    i, t, frame_path, trigger_images, W, H, output_dir = args
    frame = Image.open(frame_path).convert("RGBA")
    
    for start_ts, end_ts, img_path in trigger_images:
        if start_ts <= t <= end_ts:
            top_img = Image.open(img_path).convert("RGBA")
            img_w, img_h = top_img.size
            max_top_height = H // 2
            if img_h > max_top_height:
                ratio = max_top_height / img_h
                new_w = int(img_w * ratio)
                new_h = max_top_height
                top_img = top_img.resize((new_w, new_h), resample=Image.BICUBIC)
                img_w, img_h = top_img.size
            if img_w > W:
                ratio = W / img_w
                new_h = int(img_h * ratio)
                new_w = W
                top_img = top_img.resize((new_w, new_h), resample=Image.BICUBIC)
                img_w, img_h = top_img.size
            x_top = int((W - img_w) / 2)
            y_top = int((H / 3 - img_h) / 2)
            frame.paste(top_img, (x_top, y_top), top_img)
            break
    
    frame.save(os.path.join(output_dir, f"frame_{i:04d}.png"))

if __name__ == "__main__":
    if len(sys.argv)-1 != 6:
        print(len(sys.argv))
        print("Usage: python image_search_superimpose.py <script.txt> <subtitles.srt> <wav_path> <input_frames_dir> <cache_dir> <output_dir>")
        sys.exit(1)
    print(sys.argv)
    script_path = sys.argv[1]
    srt_path = sys.argv[2]
    wav_path = sys.argv[3]
    input_frames_dir = sys.argv[4]
    cache_dir = sys.argv[5]
    output_dir = sys.argv[6]

    with open(script_path, "r", encoding="utf-8") as f:
        script_text = f.read()
    with open(srt_path, "r", encoding="utf-8") as f:
        srt_text = f.read()

    sr, data = wavfile.read(wav_path)
    duration = len(data) / sr
    fps = 30
    W, H = 720, 1080

    trigger_intervals = get_trigger_intervals(script_text, srt_text)
    print(f"Found {len(trigger_intervals)} trigger intervals.")

    trigger_images = []
    for start, end, prompt in trigger_intervals:
        try:
            img_path = image_search_and_cache(prompt, cache_dir)
            trigger_images.append((start, end, img_path))
        except Exception as e:
            print(f"Failed to fetch image for prompt '{prompt}': {e}")

    os.makedirs(output_dir, exist_ok=True)

    num_frames = int(duration * fps)
    frame_times = np.linspace(0, duration, num_frames)
    args_list = [(i, t, os.path.join(input_frames_dir, f"frame_{i:04d}.png"), trigger_images, W, H, output_dir)
                 for i, t in enumerate(frame_times) if os.path.exists(os.path.join(input_frames_dir, f"frame_{i:04d}.png"))]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(superimpose_frame, args_list))

    print("Image superimposition complete.")