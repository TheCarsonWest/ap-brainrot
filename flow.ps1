# Script to make a video from a single character based on a script
# Usage: flow.ps1 [script_file] [character_folder]
$outputRoot = "./output"
if (-not (Test-Path $outputRoot)) {
    New-Item -ItemType Directory -Path $outputRoot | Out-Null
}

if ($args.Count -lt 2) {
    Write-Host "Usage: flow.ps1 [script_file] [character_folder]"
    exit 1
}

$script = $args[0]
$charPath = $args[1]

if (-not (Test-Path $script)) {
    Write-Warning "Script file '$script' not found."
    exit 1
}
if (-not (Test-Path $charPath)) {
    Write-Warning "Character folder '$charPath' not found."
    exit 1
}

$baseName = [System.IO.Path]::GetFileNameWithoutExtension($script)
$outputDir = Join-Path $outputRoot $baseName

if (-not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}
Copy-Item -Path $script -Destination $outputDir

# Define asset paths
$mp3Path = Join-Path $charPath "audio.mp3"
$refTextPath = Join-Path $charPath "ref_text.txt"
$imagePath = Join-Path $charPath "image.png"

if (-not (Test-Path $mp3Path) -or -not (Test-Path $refTextPath) -or -not (Test-Path $imagePath)) {
    Write-Warning "Missing one or more required files in $charPath. Exiting."
    exit 1
}

$refText = Get-Content -Path $refTextPath -Raw

# Run TTS
$inferCmd = "f5-tts_infer-cli --ref_audio `"$mp3Path`" --ref_text `"$refText`" --gen_file `"$script`" --output_dir `"$outputDir`" --speed 1.2 --remove_silence"
Invoke-Expression $inferCmd

# Convert infer_cli_basic.mp3 to infer_cli_basic.wav
$wavInferPath = Join-Path $outputDir "infer_cli_basic.wav"
# Enhance audio using audio.py
$enhancedWavPath = Join-Path $outputDir "infer_cli_basic_cleaned.wav"
Invoke-Expression "python audio.py `"$wavInferPath`""

# Use enhanced WAV for the rest of the workflow
$wavPath = $enhancedWavPath
$srtPath = Join-Path $outputDir "output.srt"
$assPath = Join-Path $outputDir "subtitles.ass"

if (Test-Path $wavPath) {
    Invoke-Expression "python transcriber.py `"$wavPath`" `"$srtPath`""
} else {
    Write-Warning "Expected audio file '$wavPath' not found. Skipping transcription."
    exit 1
}

if (Test-Path $srtPath) {
    Invoke-Expression "python subtitle.py `"$srtPath`" `"$assPath`""
} else {
    Write-Warning "Expected SRT file '$srtPath' not found. Skipping subtitle rendering."
    exit 1
}

# Create frames folder
$framesDir = Join-Path $outputDir "frame"
if (-not (Test-Path $framesDir)) {
    New-Item -ItemType Directory -Path $framesDir | Out-Null
}

# Run parametric_image.py
Invoke-Expression "python parametric_image.py `"$imagePath`" `"$framesDir`" `"$wavPath`""

# Get duration of wav + 1 second
$durationCmd = "ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 `"$wavPath`""
$duration = (& cmd /c $durationCmd).Trim()
if ($duration -match '^[\d\.]+$') {
    $durationPlusOne = [math]::Round([double]$duration + 1, 2)
} else {
    Write-Warning "Could not determine duration of $wavPath. Skipping video processing."
    exit 1
}

# Get input.mp4 duration
$inputVideo = "./input.mp4"
$inputDurationCmd = "ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 `"$inputVideo`""
$inputDuration = (& cmd /c $inputDurationCmd).Trim()
if ($inputDuration -match '^[\d\.]+$') {
    $inputDurationNum = [double]$inputDuration
} else {
    Write-Warning "Could not determine duration of $inputVideo. Skipping video processing."
    exit 1
}

# Pick random start time so that the trimmed segment fits
if ($inputDurationNum -le $durationPlusOne) {
    $startTime = 0
} else {
    $maxStart = [math]::Round($inputDurationNum - $durationPlusOne, 2)
    $startTime = [math]::Round((Get-Random -Minimum 0 -Maximum ($maxStart * 1000)) / 1000, 2)
}
# Trim, crop to 720x1080, and bake subtitles in one ffmpeg command
$subtitledVideo = Join-Path $outputDir "subtitled_video.mp4"
$assPathEscaped = $assPath -replace '\\', '\\\\'
$trimCropSubsCmd = "ffmpeg -y -ss $startTime -i `"$inputVideo`" -t $durationPlusOne -filter:v `"crop=720:1080:(in_w-720)/2:(in_h-1080)/2,subtitles='$assPathEscaped'`" -c:a copy `"$subtitledVideo`""
Invoke-Expression $trimCropSubsCmd

# Overlay frames, add audio, output to final.mp4
$finalVideo = Join-Path $outputDir "final.mp4"
$framesPattern = Join-Path $framesDir "frame_%04d.png"
# Align overlay at top-left (0,0)
$ffmpegOverlayCmd = @"
ffmpeg -y -i "$subtitledVideo" -i "$framesPattern" -i "$wavPath" -filter_complex "[0:v][1:v]overlay=0:0:shortest=1[v]" -map "[v]" -map 2:a -c:v libx264 -c:a aac "$finalVideo"
"@
Invoke-Expression $ffmpegOverlayCmd
if (Test-Path $framesDir) {
    Remove-Item -Path $framesDir -Recurse -Force
}