# Builds dist\FileConverter.exe (single file, no console window).
# Run from the repo root with the venv active: .\build.ps1
# No $ErrorActionPreference = "Stop": PyInstaller logs to stderr, which
# Windows PowerShell 5.1 would turn into a fatal error. The exit code check covers failures.

python -m PyInstaller --noconfirm --clean --onefile --windowed --name FileConverter `
  --collect-all pypdfium2 `
  --collect-all pypdfium2_raw `
  --collect-all magika `
  --collect-all markitdown `
  --collect-binaries onnxruntime `
  --hidden-import keyring.backends.Windows `
  fileconverter/__main__.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }
Get-Item dist\FileConverter.exe | Select-Object Name, @{n = "SizeMB"; e = { [math]::Round($_.Length / 1MB) } }
