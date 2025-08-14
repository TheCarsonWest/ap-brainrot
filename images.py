import sys
import re
import json
from typing import List, Tuple
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from scipy.io import wavfile
import concurrent.futures
from difflib import SequenceMatcher
from google_images_search import GoogleImagesSearch
import matplotlib.pyplot as plt
from matplotlib import rc
import os
from wand.image import Image as WandImage
from google import genai
from google.genai import types
import os
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import urllib.parse
import hashlib

# Configure Google Gemini API
client = genai.Client(api_key=open('api.txt', 'r').read())

def ai_text(p, think=-1):
    """Generate text using Gemini API with retry logic."""
    try:
        if think > 1:
            return client.models.generate_content(
                model="gemini-2.5-flash",
                contents=p,
                config=types.GenerateContentConfig(
                    thinking_config=types.ThinkingConfig(thinking_budget=think)
                    # Turn off thinking:
                    # thinking_config=types.ThinkingConfig(thinking_budget=0)
                    # Turn on dynamic thinking:
                    # thinking_config=types.ThinkingConfig(thinking_budget=-1)
                ),
            ).text
        else:
            return client.models.generate_content(contents=p,model="gemini-2.5-flash").text
    except Exception as e:
        print(f'Error in ai_text: {e}')
        time.sleep(5)
        return ai_text(p, think)

def shorten_filename(filename):
    """Shorten a filename using a hash to avoid errors."""
    max_length = 255  # Typical max filename length for most filesystems
    if len(filename) > max_length:
        # Use a hash of the filename to shorten it
        hash_part = hashlib.md5(filename.encode()).hexdigest()
        # Keep the extension and shorten the rest
        name, ext = os.path.splitext(filename)
        filename = f"{name[:max_length - len(hash_part) - len(ext) - 1]}_{hash_part}{ext}"
    return filename

def render_latex_to_png(equation, output_file="equation.png", fontsize=12, dpi=300):
    """
    Render a LaTeX equation to a PNG image.
    
    Parameters:
    - equation (str): LaTeX equation string (e.g., r'\frac{1}{2} + \sqrt{x^2}').
    - output_file (str): Path to save the PNG file (default: 'equation.png').
    - fontsize (int): Font size for the equation (default: 12).
    - dpi (int): Resolution of the output image (default: 300).
    """
    # Shorten the output filename if necessary
    output_file = shorten_filename(output_file)

    # Use matplotlib's built-in mathtext (no external LaTeX required)
    rc('text', usetex=False)
    rc('font', family='serif')

    # Strip leading/trailing $ and $$ from equation string
    eq = equation.strip()
    eq = re.sub(r'^(\${1,2})', '', eq)
    eq = re.sub(r'(\${1,2})$', '', eq)

    # Create a figure with no axes
    fig, ax = plt.subplots(figsize=(4, 1))
    ax.axis('off')  # Hide axes

    # Add a white rectangle as background for the equation
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    # Render the LaTeX equation with a white box
    text_obj = ax.text(0.5, 0.5, f"${eq}$", fontsize=fontsize, ha='center', va='center', zorder=2)
    # Draw a white rectangle behind the text
    fig.canvas.draw()
    bbox = text_obj.get_window_extent(renderer=fig.canvas.get_renderer())
    inv = ax.transData.inverted()
    bbox_data = bbox.transformed(inv)
    rect = plt.Rectangle((bbox_data.x0, bbox_data.y0), bbox_data.width, bbox_data.height,
                        color='white', zorder=1)
    ax.add_patch(rect)
    # Redraw text on top
    ax.draw_artist(text_obj)

    # Save the figure as a PNG with high DPI
    plt.savefig(output_file, format='png', dpi=dpi, bbox_inches='tight', transparent=False)
    plt.close(fig)

    print(f"Equation rendered and saved as {output_file}")

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
    return open('./prompts/timing_gen_prompt.txt', 'r', encoding='utf-8').read().format(
        script=script
    )

""" 
 "diagram",
 - For "diagram": a brief description of the diagram needed (e.g., "strong acid weak base titration curve"). Use this option sparingly, only when a diagram is necessary and an image search is insufficient. 
 """

def similarity(a: str, b: str) -> float:
    """Calculate similarity between two strings using SequenceMatcher."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def get_trigger_intervals(srt_text: str, timings: str, default_image_duration: float = 3, similarity_threshold: float = 0.5) -> List[Tuple[float, float, str]]:
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

def download_largest_google_image(prompt, local_path):
    temp_dir = "./imag_temp"
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    # Initialize Chrome WebDriver with headless options
    options = Options()
    options.add_argument("--headless=new")  # Use newer headless mode
    options.add_argument("--no-sandbox")  # Improve compatibility in some environments
    options.add_argument("--disable-dev-shm-usage")  # Avoid shared memory issues
    options.add_argument("--disable-gpu")  # Disable GPU for headless stability
    options.add_argument("--window-size=1920,1080")  # Set a window size for rendering

    # Initialize ChromeDriver
    driver = webdriver.Chrome(options=options)
    try:
        # Construct and visit Google Images search URL
        encoded_query = urllib.parse.quote(prompt)
        driver.get(f"https://www.google.com/search?tbm=isch&q={encoded_query}")

        # Scroll to load more images
        time.sleep(0.5)

        # Parse page source
        soup = BeautifulSoup(driver.page_source, "html.parser")
        
        # Collect image URLs
        images = soup.find_all("img")
        img_urls = []
        for img in images:
            img_url = img.get("src") or img.get("data-src")
            if img_url and img_url.startswith("http"):
                img_urls.append(img_url)
            if len(img_urls) >= 25:
                break

        if not img_urls:
            raise RuntimeError(f"No valid images found for prompt: {prompt}")

        # Download images and find the largest
        largest_size = 0
        largest_path = None
        largest_ext = "jpg"
        extension_map = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/gif": "gif"
        }

        for i, img_url in enumerate(img_urls):
            try:
                response = requests.get(img_url, stream=True, timeout=10)
                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "").lower()
                    if "image" in content_type:
                        file_extension = extension_map.get(content_type, "jpg")
                        file_path = os.path.join(temp_dir, f"image_{i}.{file_extension}")
                        with open(file_path, "wb") as f:
                            for chunk in response.iter_content(1024):
                                f.write(chunk)
                        file_size = os.path.getsize(file_path)
                        if file_size > largest_size:
                            largest_size = file_size
                            largest_path = file_path
                            largest_ext = file_extension
            except Exception:
                continue

        if not largest_path:
            raise RuntimeError(f"No valid images found for prompt: {prompt}")

        # Save the largest image to the specified local_path
        final_dir = os.path.dirname(local_path)
        if final_dir and not os.path.exists(final_dir):
            os.makedirs(final_dir)
        
        with open(largest_path, "rb") as src, open(local_path, "wb") as dst:
            dst.write(src.read())

        # Clean up temp files
        for fname in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, fname))
            except Exception:
                pass
        os.rmdir(temp_dir)

        return os.path.normpath(local_path)

    finally:
        driver.quit()



def image_search_and_cache(prompt_dict: dict, cache_dir: str) -> str:
    # type = "image", search for images on google
    # type = "equation", use a LaTeX renderer to create an image
    # type = "diagram", use a diagram generator to create an image
    # Common: ensure cache dir exists and compute local_path
    os.makedirs(cache_dir, exist_ok=True)
    if prompt_dict.get("type") == "image":
        prompt = prompt_dict.get("details", "")
        fname = re.sub(r"[^a-zA-Z0-9_-]", "_", prompt) + ".jpg"
    elif prompt_dict.get("type") == "equation":
        equation = prompt_dict.get("details", "")
        fname = re.sub(r"[^a-zA-Z0-9_-]", "_", equation) + ".png"
    elif prompt_dict.get("type") == "diagram":
        diagram_prompt = prompt_dict.get("details", "")
        fname = re.sub(r"[^a-zA-Z0-9_-]", "_", diagram_prompt) + ".png"
    elif prompt_dict.get("type") == "text":
        text_content = prompt_dict.get("details", "")
        fname = re.sub(r"[^a-zA-Z0-9_-]", "_", text_content[:32]) + ".png"
    else:
        raise ValueError(f"Unknown type: {prompt_dict.get('type')}")
    local_path = os.path.normpath(os.path.join(cache_dir, fname))
    if os.path.isfile(local_path):
        return local_path

    if prompt_dict.get("type") == "text":
        try:
            return generate_text_image(prompt_dict.get("details", ""), local_path)
        except Exception as e:
            print(f"Failed to render text image: {e}")
            return None

    if prompt_dict.get("type") == "image":
        # Use the new download_largest_google_image function instead of GoogleImagesSearch API
        return download_largest_google_image(prompt, local_path)
    
    
    elif prompt_dict.get("type") == "equation":
        # Use a LaTeX renderer to create an image 
        try:
            print(f"Rendering LaTeX equation to PNG: {prompt_dict.get('details', '')} -> {local_path}")
            render_latex_to_png(prompt_dict.get('details', ""), output_file=local_path)
            if not os.path.isfile(local_path):
                print(f"Equation PNG was not saved at {local_path}")
                return None
            return os.path.normpath(local_path)
        except Exception as e:
            print(f"Failed to render LaTeX equation: {e}")
            return None
    
    elif prompt_dict.get("type") == "diagram":
        # Use a diagram generator to create an image (this is a placeholder, implement actual generation)
        print("Generating diagram for prompt:", prompt_dict.get("details", ""))
        prompt = f"""
    Generate a comprehensive SVG diagram of {prompt_dict.get("details","")}. Respond only with code in an svg code block, do not use comments within your code in order to save space. Include ample padding so that no text overlaps with anything. If the diagram include a graph, include all of the important points. Use the foreignObject tag when creating text boxes so that you can use text wrapping, and to make sure no text overlaps with any object on the screen, and by making sure that the bounds(x,y,y+length,x+width) of the divs inside foreign Objects do not overlaps. In general, try not to make too many text boxes within close proximity of each other.
    """
        response = ai_text(prompt, think=4000)
        if not response or "<svg" not in response:
            print("Failed to generate SVG diagram.")
            return None
        # Extract SVG code from code block if present
        svg_code_match = re.search(r"<svg[\s\S]*?</svg>", response)
        if svg_code_match:
            svg_code = svg_code_match.group(0)
        else:
            svg_code = response  # fallback, may be just SVG code

        svg_path = os.path.normpath(local_path.replace(".png", ".svg"))
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg_code)

        # Convert SVG to JPG using wand
        try:
            with open(svg_path, "rb") as svg_file:
                svg_data = svg_file.read()
            jpg_path = os.path.normpath(local_path.replace(".png", ".jpg"))
            with WandImage(blob=svg_data, format="svg") as img:
                img.format = "jpg"
                img.background_color = "white"  # set background to white for JPG
                img.alpha_channel = 'remove'    # remove alpha for JPG
                img.save(filename=jpg_path)
                return jpg_path
        except Exception as e:
            print(f"Failed to convert SVG to JPG with wand: {e}")
            return None

def superimpose_frame(args):
    """Superimpose an image onto a frame if within the trigger interval."""
    i, t, frame_path, trigger_images, W, H, output_dir, frame_count = args
    try:
        frame = Image.open(os.path.normpath(frame_path)).convert("RGBA")
    except Exception as e:
        print(f"Error opening frame {frame_path}: {e}")
        return

    for start_ts, end_ts, img_path in trigger_images:
        if img_path is None:
            continue  # Skip if image path is None (failed generation)
        if start_ts <= t <= end_ts:
            try:
                top_img = Image.open(os.path.normpath(img_path)).convert("RGBA")
            except Exception as e:
                print(f"Error processing image {img_path}: {e}")
                continue  # Skip this image if it can't be opened
            try:
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
                continue  # Skip this image if any error occurs

    output_path = os.path.normpath(os.path.join(output_dir, f"frame_{i:04d}.png"))
    frame.save(output_path)

def generate_text_image(text_content, local_path, W=720, H=200, PAD=20):
    """Generate an image of text with autofit, white text, black outline, and drop shadow."""
    # Try to load DejaVu Sans font
    font_path = None
    try:
        import matplotlib
        font_path = matplotlib.font_manager.findfont("DejaVu Sans")
    except Exception:
        font_path = None

    # Improved word wrapping and autofit font size
    def wrap_text(text, font, max_width, draw):
        words = text.split()
        lines = []
        line = ''
        for word in words:
            test_line = line + (' ' if line else '') + word
            w = draw.textlength(test_line, font=font)
            if w > max_width and line:
                lines.append(line)
                line = word
            else:
                line = test_line
        if line:
            lines.append(line)
        return lines

    max_font_size = 100
    min_font_size = 20
    best_font_size = min_font_size
    for font_size in range(max_font_size, min_font_size-1, -2):
        try:
            font = ImageFont.truetype(font_path or "DejaVuSans.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        img_temp = Image.new('RGBA', (W, H), (0,0,0,0))
        draw_temp = ImageDraw.Draw(img_temp)
        lines = wrap_text(text_content, font, W-2*PAD, draw_temp)
        total_height = sum([draw_temp.textbbox((0,0), line, font=font)[3] - draw_temp.textbbox((0,0), line, font=font)[1] for line in lines]) + (len(lines)-1)*8
        if total_height <= H - 2*PAD:
            best_font_size = font_size
            break
    try:
        font = ImageFont.truetype(font_path or "DejaVuSans.ttf", best_font_size)
    except Exception:
        font = ImageFont.load_default()
    img = Image.new('RGBA', (W, H), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    lines = wrap_text(text_content, font, W-2*PAD, draw)
    total_height = sum([draw.textbbox((0,0), line, font=font)[3] - draw.textbbox((0,0), line, font=font)[1] for line in lines]) + (len(lines)-1)*8
    y = (H - total_height)//2
    for line in lines:
        bbox = draw.textbbox((0,0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (W - text_w)//2
        # Draw drop shadow
        shadow_offset = 3
        draw.text((x+shadow_offset, y+shadow_offset), line, font=font, fill=(0,0,0,180))
        # Draw black outline
        for ox in [-2,0,2]:
            for oy in [-2,0,2]:
                if ox == 0 and oy == 0:
                    continue
                draw.text((x+ox, y+oy), line, font=font, fill='black')
        # Draw main white text
        draw.text((x, y), line, font=font, fill='white')
        y += bbox[3] - bbox[1] + 8
    img.save(local_path, format='PNG')
    return os.path.normpath(local_path)

if __name__ == "__main__":
    """    if len(sys.argv) != 6:
        print(f"Usage: {sys.argv[0]} <subtitles.srt> <wav_path> <input_frames_dir> <cache_dir> <output_dir>")
        sys.exit(1)"""

    srt_path = sys.argv[1]
    wav_path = sys.argv[2]
    input_frames_dir = sys.argv[3]
    cache_dir = sys.argv[4]
    output_dir = sys.argv[5]
    vid_name = sys.argv[6]
    with open(srt_path, "r", encoding="utf-8") as f:
        srt_text = f.read()

    script = srt_to_raw_script(srt_text)
    prompt = create_prompt(script)
    # Retry AI call until valid JSON is returned
    while True:
        timings = ai_text(prompt,500).replace("`json", '').replace("`", "")
        try:
            json.loads(timings)
            break
        except json.JSONDecodeError as e:
            print(f"Malformed JSON from AI, retrying: {e}")
            time.sleep(2)
    print(f"Generated timings: {timings}")
    # Save timings JSON to cache directory
    os.makedirs(cache_dir, exist_ok=True)
    timings_path = os.path.join(cache_dir, "timings.json")
    try:
        with open(timings_path, "w", encoding="utf-8") as f:
            f.write(timings)
        print(f"Timings JSON saved to {timings_path}")
    except Exception as e:
        print(f"Failed to save timings JSON: {e}")

    trigger_intervals = get_trigger_intervals(srt_text, timings)
    try:
        prompt_dict = json.loads(timings)
        total_visuals = len(prompt_dict)
    except Exception:
        total_visuals = 0
    triggered = len(trigger_intervals)
    percent = (triggered / total_visuals * 100) if total_visuals else 0
    print(f"Found {triggered} out of {total_visuals} trigger intervals ({percent:.1f}%)")

    trigger_images = []
    for start, end, prompt in trigger_intervals:
        try:
            img_path = image_search_and_cache(prompt, cache_dir)
            trigger_images.append((start, end, img_path))
        except Exception as e:
            print(f"Failed to fetch image for prompt '{prompt}': {e}")

    # Generate an initial image with the video name
    initial_image_path = os.path.join(cache_dir, f"{vid_name}_initial.png")
    try:
        generate_text_image(vid_name, initial_image_path)
        sr, data = wavfile.read(wav_path)
        duration = len(data) / sr
        trigger_images.insert(0, (0, trigger_intervals[0][0] if trigger_intervals else duration, initial_image_path))
    except Exception as e:
        print(f"Failed to generate initial image for video name: {e}")

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