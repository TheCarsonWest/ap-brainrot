from faster_whisper import WhisperModel
import argparse

model = WhisperModel("base", compute_type="int8")  # or "medium", "large-v2"

segments, _ = model.transcribe("trump.mp3", word_timestamps=True)



def format_srt_time(seconds):
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hrs:02}:{mins:02}:{secs:02},{millis:03}"

with open("output.srt", "w", encoding="utf-8") as f:
    counter = 1
    for segment in segments:
        for word in segment.words:
            f.write(f"{counter}\n")
            start = word.start
            end = word.end
            text = word.word.strip()
            f.write(f"{format_srt_time(start)} --> {format_srt_time(end)}\n")
            f.write(f"{text}\n\n")
            counter += 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Transcribe audio to SRT subtitles.")
    parser.add_argument("input_file", type=str, help="Path to the input audio file.")
    parser.add_argument("output_file", type=str, help="Path to the output SRT file.")
    args = parser.parse_args()

    input_file = args.input_file
    output_file = args.output_file
    segments, _ = model.transcribe(input_file, word_timestamps=True)

    with open(output_file, "w", encoding="utf-8") as f:
        counter = 1
        for segment in segments:
            for word in segment.words:
                f.write(f"{counter}\n")
                start = word.start
                end = word.end
                text = word.word.strip()
                f.write(f"{format_srt_time(start)} --> {format_srt_time(end)}\n")
                f.write(f"{text}\n\n")
                counter += 1