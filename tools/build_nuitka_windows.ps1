# AstroSwarm Windows 桌面端 Nuitka 加固构建
# 前置：安装 Visual Studio 2022 Build Tools（勾选“使用 C++ 的桌面开发”，含 MSVC v143 + Windows 10/11 SDK）
# 用法（PowerShell）：
#   $env:PYTHONPATH='D:\ai\QBotManager'
#   powershell -ExecutionPolicy Bypass -File D:\ai\QBotManager\tools\build_nuitka_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location "D:\ai\QBotManager"

$python = "D:\ai\QBotManager\.build_venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = "python"
}

& $python -m nuitka `
    --standalone `
    --assume-yes-for-downloads `
    --enable-plugin=pyside6 `
    --enable-plugin=multiprocessing `
    --windows-console-mode=disable `
    --windows-icon-from-ico=D:\ai\QBotManager\assets\logo.ico `
    --output-dir=D:\ai\QBotManager\dist-nuitka `
    --output-filename=AstroSwarm.exe `
    --remove-output `
    --warn-implicit-exceptions `
    D:\ai\QBotManager\src\main.py

Write-Host "Nuitka 构建完成：D:\ai\QBotManager\dist-nuitka\AstroSwarm.dist\AstroSwarm.exe"
