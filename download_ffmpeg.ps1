$url = 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'
$zip = "$env:TEMP\ffmpeg_dl.zip"
$dest = "$PSScriptRoot\mayihear-api\bin\ffmpeg.exe"

Write-Host "Downloading ffmpeg (~90MB)..."
Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
Write-Host "Extracting ffmpeg.exe..."

Add-Type -AssemblyName System.IO.Compression.FileSystem
$z = [System.IO.Compression.ZipFile]::OpenRead($zip)
$entry = $z.Entries | Where-Object { $_.Name -eq 'ffmpeg.exe' } | Select-Object -First 1
[System.IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $dest, $true)
$z.Dispose()

Remove-Item $zip
Write-Host "Done! ffmpeg.exe saved to: $dest"
