import re
from datetime import timedelta
import argparse

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

def group_words(entries, max_gap=timedelta(seconds=2)):
    sentences = []
    current = []
    for i, (start, end, word) in enumerate(entries):
        if current:
            prev_end = current[-1][1]
            # Adjust the end time of the previous subtitle to match the start time of the current one
            if start - prev_end > max_gap or re.search(r'[.!?]$', current[-1][2]):
                # Update the end time of the last word in the current group
                current[-1] = (current[-1][0], start, current[-1][2])
                sentences.append(current)
                current = []
        current.append((start, end, word))
    if current:
        sentences.append(current)
    return sentences

def ass_header():
    return """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans,36,&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,30,30,30,1

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
                    highlighted.append(r"{\c&H00FFFF&}" + w + r"{\c}")
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

