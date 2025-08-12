param(
    [Parameter(Mandatory=$true)]
    [string]$MarkdownFolder,
    [Parameter(Mandatory=$true)]
    [string]$TargetDirectory
)

# Construct the prompt.txt path
$PromptPath = Join-Path -Path $TargetDirectory -ChildPath "prompt.txt"

# Get all markdown files in the folder
$MarkdownFiles = Get-ChildItem -Path $MarkdownFolder -Filter *.md
$TotalFiles = $MarkdownFiles.Count
$ProcessedFiles = 0
$TotalTime = 0

# Update to handle two outputs from generate_script.py
foreach ($MarkdownFile in $MarkdownFiles) {
    $StartTime = Get-Date

    # Get the base name (without extension) of the markdown file
    $BaseName = [System.IO.Path]::GetFileNameWithoutExtension($MarkdownFile.Name)

    # Run the Python script
    python generate_script.py --topic_file "$($MarkdownFile.FullName)" --character_file "$PromptPath"

    # Construct paths for the generated scripts
    $GeneratedScript = Join-Path -Path "./scripts" -ChildPath ("$BaseName.txt")

    # Run the flow.ps1 script with the no curly script
    ./flow2.ps1 "$GeneratedScript" "$TargetDirectory" --delete_output

    # Move the processed .md file to ./done
    $DoneDir = Join-Path -Path $MarkdownFolder -ChildPath "done"
    if (-not (Test-Path $DoneDir)) {
        New-Item -ItemType Directory -Path $DoneDir | Out-Null
    }
    Move-Item -Path $MarkdownFile.FullName -Destination $DoneDir

    $EndTime = Get-Date
    $IterationTime = ($EndTime - $StartTime).TotalSeconds
    $TotalTime += $IterationTime
    $ProcessedFiles++

    $AverageTime = $TotalTime / $ProcessedFiles
    $RemainingFiles = $TotalFiles - $ProcessedFiles
    $ETA = [TimeSpan]::FromSeconds($AverageTime * $RemainingFiles)

    Write-Host "Processed file: $($MarkdownFile.Name)"
    Write-Host "Time taken: $IterationTime seconds"
    Write-Host "ETA for remaining files: $($ETA.ToString())"
}