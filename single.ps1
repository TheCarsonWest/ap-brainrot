param(
    [Parameter(Mandatory=$true)]
    [string]$MarkdownFile,
    [Parameter(Mandatory=$true)]
    [string]$TargetDirectory
)

# Get the base name (without extension) of the markdown file
$BaseName = [System.IO.Path]::GetFileNameWithoutExtension($MarkdownFile)

# Construct the prompt.txt path
$PromptPath = Join-Path -Path $TargetDirectory -ChildPath "prompt.txt"

# Run the Python script
python generate_script.py --topic_file "$MarkdownFile" --character_file "$PromptPath"

# Construct the generated script path
$GeneratedScript = Join-Path -Path "./scripts" -ChildPath ("$BaseName.txt")

# Run the flow.ps1 script
./flow.ps1 "$GeneratedScript" "$TargetDirectory"