param(
    [string]$Installation = 'C:\Software\microscope-software-mic3',
    [string]$Original = 'C:\Software\leica_microscope',
    [string]$Python = "$env:USERPROFILE\anaconda3\python.exe",
    [string]$Desktop = [Environment]::GetFolderPath('Desktop')
)
$ErrorActionPreference = 'Stop'
$package = Join-Path $Original 'leica_microscope'
foreach ($path in @($Python, "$package\LiveViewer.py", "$package\generate_record.py", "$package\ConfigCreator\ConfigCreator.py")) {
    if (!(Test-Path -LiteralPath $path)) { throw "Missing original application: $path" }
}
$launch = Join-Path $Installation '.desktop\old'
New-Item -ItemType Directory -Path $launch -Force | Out-Null
$settings = Join-Path $env:APPDATA 'Microscope\Config-old.txt'
if (!(Test-Path -LiteralPath $settings)) {
    New-Item -ItemType Directory -Path (Split-Path $settings) -Force | Out-Null
    Copy-Item -LiteralPath "$package\ConfigCreator\Config_Default.txt" -Destination $settings
}
$commands = @{
    'LiveViewer old' = '"' + $package + '\LiveViewer.py"'
    'Record old' = '"' + $package + '\ConfigCreator\ConfigCreator.py" -c Config-old.txt -p "' + $package + '\generate_record.py" -i "' + $Installation + '\leica_microscope\icons\RecordOld.ico"'
}
$shell = New-Object -ComObject WScript.Shell
foreach ($name in $commands.Keys) {
    $bat = Join-Path $launch ($name + '.bat')
    @"
@echo off
setlocal
set "PYTHONPATH=$Original"
pushd "$package" || exit /b 1
"$Python" $($commands[$name])
set "result=%ERRORLEVEL%"
popd
if not "%result%"=="0" pause
exit /b %result%
"@ | Set-Content -LiteralPath $bat -Encoding ASCII
    $linkPath = Join-Path $Desktop ($name + '.lnk')
    if (Test-Path -LiteralPath $linkPath) { throw "Shortcut already exists: $linkPath" }
    $link = $shell.CreateShortcut($linkPath)
    $link.TargetPath = $bat
    $link.WorkingDirectory = $package
    $icon = if ($name -eq 'Record old') { 'RecordOld.ico' } else { 'LiveViewerOld.ico' }
    $link.IconLocation = "$Installation\leica_microscope\icons\$icon,0"
    $link.Description = 'Original microscope application; independent legacy recording settings'
    $link.Save()
    Write-Output $linkPath
}
