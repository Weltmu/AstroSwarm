$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$py = ".build_venv\Scripts\python.exe"
Write-Host "打包 uninstall.exe ..."
& $py -m PyInstaller --noconfirm --clean --onefile --windowed --name uninstall `
  --paths src `
  --collect-all nacl --collect-all cffi --hidden-import _cffi_backend `
  src\uninstall_main.py
Write-Host "完成: dist\uninstall.exe"
