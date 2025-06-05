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



# Create a version of the script without {{double curly brackets}} and their contents
$scriptNoCurly = Join-Path $outputDir "$baseName`_no_curly.txt"
$scriptContent = Get-Content -Path $script -Raw
$scriptContentNoCurly = $scriptContent -replace '\{\{.*?\}\}', ''
Set-Content -Path $scriptNoCurly -Value $scriptContentNoCurly

# Define asset paths
$mp3Path = Join-Path $charPath "audio.mp3"
$refTextPath = Join-Path $charPath "ref_text.txt"
$imagePath = Join-Path $charPath "image.png"

if (-not (Test-Path $mp3Path) -or -not (Test-Path $refTextPath) -or -not (Test-Path $imagePath)) {
    Write-Warning "Missing one or more required files in $charPath. Exiting."
    exit 1
}

$refText = Get-Content -Path $refTextPath -Raw

# Update infer command to append _no_curly to the file name

# Run TTS with the no curly script
$inferCmd = "f5-tts_infer-cli --ref_audio `"$mp3Path`" --ref_text `"$refText`" --gen_file `"$scriptNoCurly`" --output_dir `"$outputDir`" --remove_silence"
Invoke-Expression $inferCmd

# Convert infer_cli_basic.mp3 to infer_cli_basic.wav
$wavInferPath = Join-Path $outputDir "infer_cli_basic.wav"
# Enhance audio using audio.py
$enhancedWavPath = Join-Path $outputDir "infer_cli_basic_cleaned.wav"
Invoke-Expression "python audio.py `"$wavInferPath`""

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

# Create frames directory inside the output folder
$framesDir = Join-Path $outputDir "frames"
if (-not (Test-Path $framesDir)) {
    New-Item -ItemType Directory -Path $framesDir | Out-Null
}

# Create image cache directory inside the output folder
$cacheDir = Join-Path $outputDir "cache"
if (-not (Test-Path $cacheDir)) {
    New-Item -ItemType Directory -Path $cacheDir | Out-Null
}


# Usage: python =
# Use the script with curly brackets for integrated.py
Invoke-Expression "python bounce.py `"$imagePath`" `"$framesDir`" `"$wavInferPath`""

$script = $script -replace '\\', '/'
$srtPath = $srtPath -replace '\\', '/'
$wavPath = $wavPath -replace '\\', '/'
$framesDir = $framesDir -replace '\\', '/'
$cacheDir = $cacheDir -replace '\\', '/'
$outputDir = $outputDir -replace '\\', '/'

# python image_search_superimpose.py <script.txt> <subtitles.srt> <wav_path> <input_frames_dir> <cache_dir> <output_dir
# Execute the command
$cmd = @(
    "python",
    "image_search.py",
    """$script""",  # Double quotes to handle spaces in the path
    """$srtPath""",        # Double quotes to handle spaces in the path
    """$wavPath""",        # Double quotes to handle spaces in the path
    """$framesDir""",      # Double quotes to handle spaces in the path
    """$cacheDir""",       # Double quotes to handle spaces in the path
    """$framesDir"""       # Double quotes to handle spaces in the path
) -join " "

Write-Host "Executing command: $cmd"

# Execute the command
Invoke-Expression $cmd
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
# Overlay frames, add audio, output to final.mp4
$finalVideo = Join-Path $outputDir "final.mp4"
$framesPattern = Join-Path $framesDir "frame_%04d.png"

# Escape and quote paths for ffmpeg
$escapedAssPath = $assPath -replace '\\', '\\\\' -replace "'", "'\\''"
$quotedAssPath = "`"$escapedAssPath`""
$quotedInputVideo = "`"$inputVideo`""
$quotedFramesPattern = "`"$framesPattern`""  # Sequential frame pattern
$quotedWavPath = "`"$wavPath`""
$quotedFinalVideo = "`"$finalVideo`""

Write-Host "Start Time: $startTime"
Write-Host "Duration: $durationPlusOne"
Write-Host "Input Video: $quotedInputVideo"
Write-Host "Frames Pattern: $quotedFramesPattern"
Write-Host "WAV Path: $quotedWavPath"
Write-Host "Subtitles Path: $quotedAssPath"
Write-Host "Final Video: $quotedFinalVideo"

# Use -filter_complex for multiple inputs
$filterComplex = "[0:v]crop=720:1080:(in_w-720)/2:(in_h-1080)/2,subtitles=$quotedAssPath[vid];[vid][1:v]overlay=shortest=1[outv]"

$arguments = @(
    '-y'
    '-ss', "$startTime"
    '-t', "$durationPlusOne"
    '-i', $quotedInputVideo
    '-framerate', '30'
    '-i', $quotedFramesPattern  # Use sequential frame pattern
    '-i', $quotedWavPath
    '-filter_complex', $filterComplex
    '-map', '[outv]'
    '-map', '2:a:0'
    '-c:v', 'h264_nvenc'
    '-preset', 'p7'
    '-rc', 'vbr'
    '-cq', '19'
    '-b:v', '0'
    '-c:a', 'aac'
    '-b:a', '192k'
    '-shortest'
    $quotedFinalVideo
)

Start-Process -NoNewWindow -Wait -FilePath "ffmpeg" -ArgumentList $arguments


# Copy final video to ./videos/ using subfolder name
$videosDir = "./videos"
if (-not (Test-Path $videosDir)) {
    New-Item -ItemType Directory -Path $videosDir | Out-Null
}
$finalVideoDest = Join-Path $videosDir ("$baseName.mp4")
Copy-Item -Path $finalVideo -Destination $finalVideoDest -Force


