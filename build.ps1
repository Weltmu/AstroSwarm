$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Test-Path ".build_venv\Scripts\python.exe")) {
    Write-Host "创建构建虚拟环境 ..."
    python -m venv .build_venv
}
$py = ".build_venv\Scripts\python.exe"
Write-Host "安装 PySide6 / PyInstaller ..."
& $py -m pip install -U pip -i https://pypi.tuna.tsinghua.edu.cn/simple
& $py -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

Write-Host "打包 AstroSwarm.exe（AstroSwarm.spec，含 logo 图标）..."
& $py -m PyInstaller --noconfirm --clean AstroSwarm.spec

Write-Host "打包 uninstall.exe（uninstall.spec）..."
& $py -m PyInstaller --noconfirm --clean uninstall.spec
Write-Host "完成: dist\AstroSwarm.exe / dist\uninstall.exe"
