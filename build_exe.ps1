$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$versionMatch = Select-String -LiteralPath (Join-Path $PSScriptRoot "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"' | Select-Object -First 1
if (-not $versionMatch) {
    throw "Unable to read the project version from pyproject.toml."
}

$version = $versionMatch.Matches[0].Groups[1].Value
if ($version -notmatch '^\d+\.\d+\.\d+$') {
    throw "Expected a numeric major.minor.patch version."
}
$appName = "SpriteMakerPySide-$version"
$iconPath = Join-Path $PSScriptRoot "main.ico"
if (-not (Test-Path -LiteralPath $iconPath -PathType Leaf)) {
    throw "Required application icon not found: $iconPath"
}

# Prefer the repository virtual environment. When it is absent (for example in
# GitHub Actions after actions/setup-python), use the active python on PATH
# instead of the Windows `py` launcher, which may select a different Python
# installation that does not contain PyInstaller.
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$pythonArgs = @()
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $python = $venvPython
} else {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $python = $pythonCommand.Source
    } else {
        $python = "py"
        $pythonArgs = @("-3")
    }
}

$versionParts = $version.Split('.')
$versionTuple = "$($versionParts[0]), $($versionParts[1]), $($versionParts[2]), 0"
$versionFile = Join-Path $PSScriptRoot "build\version-$version.txt"
New-Item -ItemType Directory -Path (Join-Path $PSScriptRoot "build") -Force | Out-Null
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($versionTuple), prodvers=($versionTuple), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', 'SpriteMaker PySide'),
    StringStruct('FileVersion', '$version'),
    StringStruct('ProductName', 'SpriteMaker PySide'),
    StringStruct('ProductVersion', '$version'),
    StringStruct('OriginalFilename', '$appName.exe')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -LiteralPath $versionFile -Encoding utf8

& $python @pythonArgs -m PyInstaller --noconfirm --clean --windowed --icon $iconPath --version-file $versionFile --name $appName run.py
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$builtFolder = Join-Path $PSScriptRoot "dist\$appName"
$packageFolder = Join-Path $PSScriptRoot "$appName-win64"
$zipPath = "$packageFolder.zip"
# Check absolute targets before recursive package replacement/copy.
$workspaceRoot = [System.IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\') + '\'
foreach ($targetPath in @($builtFolder, $packageFolder, $zipPath)) {
    $absoluteTarget = [System.IO.Path]::GetFullPath($targetPath)
    if (-not $absoluteTarget.StartsWith($workspaceRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Package target is outside the workspace: $absoluteTarget"
    }
    if (Test-Path -LiteralPath $targetPath) {
        $targetItem = Get-Item -LiteralPath $targetPath
        if ($targetItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Refusing to replace or copy a linked package target: $absoluteTarget"
        }
    }
}
if (Test-Path -LiteralPath $packageFolder) {
    Remove-Item -LiteralPath $packageFolder -Recurse -Force
}
if (Test-Path -LiteralPath $zipPath) {
    Remove-Item -LiteralPath $zipPath -Force
}
Copy-Item -LiteralPath $builtFolder -Destination $packageFolder -Recurse
Copy-Item -LiteralPath (Join-Path $PSScriptRoot "README.zh-TW.md"), (Join-Path $PSScriptRoot "README.md"), (Join-Path $PSScriptRoot "LICENSE") -Destination $packageFolder
Compress-Archive -LiteralPath $packageFolder -DestinationPath $zipPath

Write-Host "Created $zipPath"
