# 重新打包客户分发：dist exe -> dist_package\AstroSwarm_客户版 -> 桌面两个 zip
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$desktop = [Environment]::GetFolderPath('Desktop')
$pkg = Join-Path $root 'dist_package\AstroSwarm_客户版'
$zips = @(
    (Join-Path $desktop 'AstroSwarm_客户分发版.zip'),
    (Join-Path $desktop 'AstroSwarm_客户版_nooffline.zip')
)

# 1) 同步 exe 到分发目录
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'dist\AstroSwarm.exe') -Destination $pkg -Force
Copy-Item -LiteralPath (Join-Path $root 'dist\uninstall.exe') -Destination $pkg -Force
$docOld = Join-Path $root 'dist_package\QBotManager_客户版\使用说明.docx'
$docNew = Join-Path $pkg '使用说明.docx'
if (-not (Test-Path -LiteralPath $docNew) -and (Test-Path -LiteralPath $docOld)) {
    Copy-Item -LiteralPath $docOld -Destination $docNew -Force
}
Write-Output 'COPIED exe -> dist_package\AstroSwarm_客户版'

# 2) 在临时目录摆出与 zip 一致的顶层目录，再打包
$stage = Join-Path $env:TEMP ('qbm_zip_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
Copy-Item -LiteralPath $pkg -Destination $stage -Recurse -Force
Add-Type -AssemblyName System.IO.Compression.FileSystem
foreach ($z in $zips) {
    $tmp = Join-Path $env:TEMP ('qbm_' + [IO.Path]::GetFileName($z))
    if (Test-Path -LiteralPath $tmp) { [IO.File]::Delete($tmp) }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $stage, $tmp, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    Move-Item -LiteralPath $tmp -Destination $z -Force
    Write-Output "SYNCED $z"
}

# 3) 校验：dist exe 哈希 + zip 内 exe 哈希
$sha = [System.Security.Cryptography.SHA256]::Create()
foreach ($name in @('AstroSwarm.exe', 'uninstall.exe')) {
    $fs = [IO.File]::OpenRead((Join-Path $root ("dist\$name")))
    $h = [BitConverter]::ToString($sha.ComputeHash($fs)) -replace '-', ''
    $fs.Dispose()
    Write-Output "DIST $name $h"
}
foreach ($z in $zips) {
    $a = [System.IO.Compression.ZipFile]::OpenRead($z)
    foreach ($name in @('AstroSwarm.exe', 'uninstall.exe')) {
        $e = $a.GetEntry("AstroSwarm_客户版/$name")
        $ms = New-Object IO.MemoryStream
        $s = $e.Open()
        $s.CopyTo($ms)
        $s.Dispose()
        $h = [BitConverter]::ToString($sha.ComputeHash($ms.ToArray())) -replace '-', ''
        Write-Output "ZIP $z :: $name $h"
    }
    $a.Dispose()
}

# 4) 清理临时目录
[System.IO.Directory]::Delete($stage, $true)
Write-Output 'DONE'
