import zipfile, pathlib, sys
sp = pathlib.Path(r"D:\程序测试1\python\Lib\site-packages")
for w in ("pip.whl", "setuptools.whl"):
    p = sp / w
    with zipfile.ZipFile(p) as z:
        z.extractall(sp)
    try:
        p.unlink()
    except OSError:
        pass
print("extracted OK")