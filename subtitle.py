import re
from datetime import timedelta
import argparse

# Configurable variables for formatting
FONT_NAME = "DejaVu Sans"  # The font name to use for the subtitles.
FONT_SIZE = 72  # The font size for the subtitles.
PRIMARY_COLOR = "&H00FFFFFF"  # The primary color of the text in ASS format (BGR hexadecimal).
SECONDARY_COLOR = "&H000000FF"  # The secondary color (used for karaoke effects, not used here).
OUTLINE_COLOR = "&H00000000"  # The color of the outline around the text.
BACK_COLOR = "&H64000000"  # The background color (used for karaoke effects, not used here).
BOLD = 0  # Set to 1 for bold text, 0 for normal text.
ITALIC = 0  # Set to 1 for italic text, 0 for normal text.
UNDERLINE = 0  # Set to 1 to underline the text, 0 for no underline.
STRIKEOUT = 0  # Set to 1 to strike through the text, 0 for no strikeout.
SCALE_X = 100  # Horizontal scaling of the text (percentage).
SCALE_Y = 100  # Vertical scaling of the text (percentage).
SPACING = 0  # Additional spacing between characters (in pixels).
ANGLE = 0  # Rotation angle of the text (in degrees).
BORDER_STYLE = 1  # Border style: 1 for outline + shadow, 3 for opaque box.
OUTLINE = 4  # Thickness of the outline around the text (in pixels).
SHADOW = 1  # Thickness of the shadow behind the text (in pixels).
ALIGNMENT = 5  # Text alignment: 1 (bottom-left), 2 (bottom-center), 3 (bottom-right), etc.
MARGIN_L = 30  # Left margin (in pixels).
MARGIN_R = 30  # Right margin (in pixels).
MARGIN_V = 30  # Vertical margin (distance from the bottom of the screen, in pixels).
ENCODING = 1  # Character encoding: 0 for ANSI, 1 for default (UTF-8), etc.

def parse_srt(srt_text):
    entries = []
    blocks = srt_text.strip().split('\n\n')
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            idx = lines[0]
            time_line = lines[1]
            text = ' '.join(lines[2:])
            start_str, end_str = time_line.split(' --> ')
            def parse_time(s):
                h, m, rest = s.split(':')
                s, ms = rest.split(',')
                return timedelta(hours=int(h), minutes=int(m), seconds=int(s), milliseconds=int(ms))
            start = parse_time(start_str)
            end = parse_time(end_str)
            entries.append((start, end, text))
    return entries

def group_words(entries, max_gap=timedelta(seconds=2), max_words=5):
    sentences = []
    current = []
    for i, (start, end, word) in enumerate(entries):
        if current:
            prev_end = current[-1][1]
            if (start - prev_end > max_gap or 
                re.search(r'[.!?]$', current[-1][2]) or 
                len(current) >= max_words):
                current[-1] = (current[-1][0], start, current[-1][2])
                sentences.append(current)
                current = []
        current.append((start, end, word))
    if current:
        sentences.append(current)
    return sentences

def ass_header():
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{FONT_NAME},{FONT_SIZE},{PRIMARY_COLOR},{SECONDARY_COLOR},{OUTLINE_COLOR},{BACK_COLOR},{BOLD},{ITALIC},{UNDERLINE},{STRIKEOUT},{SCALE_X},{SCALE_Y},{SPACING},{ANGLE},{BORDER_STYLE},{OUTLINE},{SHADOW},{ALIGNMENT},{MARGIN_L},{MARGIN_R},{MARGIN_V},{ENCODING}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"""

def format_time(t: timedelta):
    h = t.seconds // 3600
    m = (t.seconds % 3600) // 60
    s = t.seconds % 60
    cs = t.microseconds // 10000
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"

def make_ass_events(sentences):
    ass_lines = []
    for sentence in sentences:
        full_text = ' '.join([w for _, _, w in sentence])
        for i, (start, end, word) in enumerate(sentence):
            highlighted = []
            for j, (_, _, w) in enumerate(sentence):
                if i == j:
                    highlighted.append(r"{\b1\c&H00FFFF&}" + w + r"{\b0\c}")
                else:
                    highlighted.append(w)
            ass_text = ' '.join(highlighted)
            ass_lines.append(
                f"Dialogue: 0,{format_time(start)},{format_time(end)},Default,,0,0,0,,{ass_text}"
            )
    return ass_lines

def srt_to_ass(srt_path, ass_path):
    with open(srt_path, encoding='utf-8') as f:
        srt_text = f.read()
    entries = parse_srt(srt_text)
    sentences = group_words(entries)
    header = ass_header()
    events = make_ass_events(sentences)
    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(header + '\n' + '\n'.join(events))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert SRT subtitles to ASS format with word highlighting.")
    parser.add_argument("srt_path", help="Path to the input SRT file.")
    parser.add_argument("ass_path", help="Path to the output ASS file.")
    args = parser.parse_args()

    srt_to_ass(args.srt_path, args.ass_path)
