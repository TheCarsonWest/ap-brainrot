import sys
import os
import whisper
from datetime import timedelta

def transcribe_to_srt(mp3_file, srt_file):
    # Load the Whisper model
    model = whisper.load_model("base")

    # Transcribe the audio
    print("Transcribing audio...")
    result = model.transcribe(mp3_file)

    # Generate SRT content
    print("Generating SRT file...")
    srt_content = []
    for i, segment in enumerate(result['segments']):
        start_time = str(timedelta(seconds=int(segment['start'])))
        end_time = str(timedelta(seconds=int(segment['end'])))
        srt_content.append(f"{i + 1}\n{start_time},000 --> {end_time},000\n{segment['text']}\n")

    # Write to SRT file
    with open(srt_file, "w", encoding="utf-8") as f:
        f.writelines(srt_content)

    print(f"SRT file saved to {srt_file}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python transcriber.py <input_mp3_file> <output_srt_file>")
        sys.exit(1)

    input_mp3 = sys.argv[1]
    output_srt = sys.argv[2]

    if not os.path.exists(input_mp3):
        print(f"Error: File {input_mp3} does not exist.")
        sys.exit(1)

    transcribe_to_srt(input_mp3, output_srt)