import os
import sys
import re
import json
from typing import List, Tuple
from PIL import Image
import numpy as np
from scipy.io import wavfile
import concurrent.futures
from difflib import SequenceMatcher
from time import sleep
import google.generativeai as genai
from google_images_search import GoogleImagesSearch


# Configure Google Gemini API
genai.configure(api_key=open('api.txt', 'r').read())
model = genai.GenerativeModel("gemini-2.5-flash")

def ai_text(p):
    """Generate text using Gemini API with retry logic."""
    try:
        return model.generate_content(p).text
    except Exception as e:
        print(f'Error in ai_text: {e}')
        sleep(5)
        return ai_text(p)

def timestamp_to_seconds(ts: str) -> float:
    """Convert SRT timestamp (HH:MM:SS,mmm) to seconds."""
    h, m, s_ms = ts.split(':')
    s, ms = s_ms.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

def parse_srt(srt_text: str) -> List[Tuple[float, float, str]]:
    """Parse SRT file into list of (start_time, end_time, text) tuples."""
    entries = re.findall(r'\d+\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)\n\n', srt_text, re.DOTALL)
    return [(timestamp_to_seconds(start), timestamp_to_seconds(end), text.strip()) for start, end, text in entries]

def group_srt_into_phrases(srt_entries: List[Tuple[float, float, str]], max_gap: float = 0.5) -> List[Tuple[float, float, str]]:
    """Group word-by-word SRT entries into phrases based on timing gaps."""
    if not srt_entries:
        return []
    
    phrases = []
    current_phrase = []
    current_start = srt_entries[0][0]
    current_end = srt_entries[0][1]
    current_text = srt_entries[0][2]
    
    for i, (start, end, text) in enumerate(srt_entries[1:], 1):
        if start - current_end <= max_gap:
            current_text += f" {text}"
            current_end = end
        else:
            phrases.append((current_start, current_end, current_text))
            current_start = start
            current_end = end
            current_text = text
    phrases.append((current_start, current_end, current_text))
    
    return phrases

def srt_to_raw_script(srt_text: str) -> str:
    """Extract every 4th line starting from line 3 (lines 3, 7, 11, ...) from SRT text."""
    lines = srt_text.strip().splitlines()
    raw_script_lines = [lines[i].strip() for i in range(2, len(lines), 4) if lines[i].strip()]
    return "\n".join(raw_script_lines)

def create_prompt(script: str) -> str:
    """Create prompt for AI to generate image search prompts."""
    return f"""
Here is the script of a video you are going to create:

{script}

Your job is to make prompts that should be searched to find an image that is corresponding with what is being said. Respond with a dictionary where the key is a string from the text and the value is an image search prompt to supplement what is being said. Copy over the string exactly. Do not respond with anything other than this dictionary. Make the code block language json. Do not add any other text or explanation. The values should be descriptive image search prompts that would yield relevant images for the text. You cannot simply describe a concept you want to show, you must describe the image you want to find, the prompt cannot be too specific or it will not work. The image should be relevant to the text and should not be a generic image. Do not show images relating to the anything personal to the person speaking. If there is no relevant image, do not include that string in the dictionary. 
"""

def similarity(a: str, b: str) -> float:
    """Calculate similarity between two strings using SequenceMatcher."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def get_trigger_intervals(srt_text: str, timings: str, default_image_duration: float = 1.5, similarity_threshold: float = 0.4) -> List[Tuple[float, float, str]]:
    """Map image prompts to subtitle timestamps using substring and fuzzy matching."""
    srt_entries = parse_srt(srt_text)
    grouped_entries = group_srt_into_phrases(srt_entries)
    
    try:
        prompt_dict = json.loads(timings)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in timings: {e}. Returning empty intervals.")
        return []

    intervals = []
    unmatched_phrases = []
    for start, end, text in grouped_entries:
        best_match = None
        best_score = 0.0
        best_prompt = None
        for script_text, img_prompt in prompt_dict.items():
            # Check for exact substring match first
            if script_text.lower() in text.lower():
                best_match = script_text
                best_score = 1.0
                best_prompt = img_prompt
                break
            # Fallback to fuzzy matching
            score = similarity(script_text, text)
            if score > best_score and score >= similarity_threshold:
                best_match = script_text
                best_score = score
                best_prompt = img_prompt
        if best_match:
            duration = end - start
            if duration < default_image_duration:
                end = start + default_image_duration
            intervals.append((start, end, best_prompt))
        else:
            unmatched_phrases.append((start, end, text))

    if unmatched_phrases:
        print("Unmatched phrases:")
        for start, end, text in unmatched_phrases:
            print(f"  {start:.2f} --> {end:.2f}: {text}")

    return sorted(intervals, key=lambda x: x[0])

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
    """Superimpose an image onto a frame if within the trigger interval."""
    i, t, frame_path, trigger_images, W, H, output_dir, frame_count = args
    try:
        frame = Image.open(frame_path).convert("RGBA")
    except Exception as e:
        print(f"Error opening frame {frame_path}: {e}")
        return

    for start_ts, end_ts, img_path in trigger_images:
        if start_ts <= t <= end_ts:
            try:
                top_img = Image.open(img_path).convert("RGBA")
                img_w, img_h = top_img.size
                max_top_height = H // 2
                if img_h > max_top_height:
                    ratio = max_top_height / img_h
                    new_w = int(img_w * ratio)
                    new_h = max_top_height
                    top_img = top_img.resize((new_w, new_h), resample=Image.Resampling.LANCZOS)
                    img_w, img_h = top_img.size
                if img_w > W:
                    ratio = W / img_w
                    new_h = int(img_h * ratio)
                    new_w = W
                    top_img = top_img.resize((new_w, new_h), resample=Image.Resampling.LANCZOS)
                    img_w, img_h = top_img.size
                x_top = (W - img_w) // 2
                y_top = (H // 2 - img_h) // 2
                frame.paste(top_img, (x_top, y_top), top_img)
                frame_count[0] += 1
                break
            except Exception as e:
                print(f"Error processing image {img_path}: {e}")
                continue

    output_path = os.path.join(output_dir, f"frame_{i:04d}.png")
    frame.save(output_path)

if __name__ == "__main__":
    if len(sys.argv) != 6:
        print(f"Usage: {sys.argv[0]} <subtitles.srt> <wav_path> <input_frames_dir> <cache_dir> <output_dir>")
        sys.exit(1)

    srt_path = sys.argv[1]
    wav_path = sys.argv[2]
    input_frames_dir = sys.argv[3]
    cache_dir = sys.argv[4]
    output_dir = sys.argv[5]

    with open(srt_path, "r", encoding="utf-8") as f:
        srt_text = f.read()

    script = srt_to_raw_script(srt_text)
    prompt = create_prompt(script)
    timings = ai_text(prompt).replace("`json", '').replace("`", "")
    print(f"Generated timings: {timings}")

    trigger_intervals = get_trigger_intervals(srt_text, timings)
    print(f"Found {len(trigger_intervals)} trigger intervals.")

    trigger_images = []
    for start, end, prompt in trigger_intervals:
        try:
            img_path = image_search_and_cache(prompt, cache_dir)
            trigger_images.append((start, end, img_path))
        except Exception as e:
            print(f"Failed to fetch image for prompt '{prompt}': {e}")

    sr, data = wavfile.read(wav_path)
    duration = len(data) / sr
    fps = 30
    W, H = 720, 1080
    os.makedirs(output_dir, exist_ok=True)

    num_frames = int(duration * fps)
    frame_times = np.linspace(0, duration, num_frames)
    frame_count = [0]
    args_list = [
        (i, t, os.path.join(input_frames_dir, f"frame_{i:04d}.png"), trigger_images, W, H, output_dir, frame_count)
        for i, t in enumerate(frame_times)
        if os.path.exists(os.path.join(input_frames_dir, f"frame_{i:04d}.png"))
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        executor.map(superimpose_frame, args_list)

    print(f"Image superimposition complete. Total frames with superimposed images: {frame_count[0]}")