Set-Location -LiteralPath $PSScriptRoot
py -m PyInstaller --noconfirm --windowed --name SpriteMakerPySide run.py
