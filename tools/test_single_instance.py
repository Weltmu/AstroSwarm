# -*- coding: utf-8 -*-
"""单实例机制冒烟测试：进程 A 持有互斥体，进程 B 应被拦截。"""
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from qbotmanager.app import _single_instance  # noqa: E402


class _Holder:
    pass


def _child_a(name: str) -> int:
    holder = _Holder()
    ok = _single_instance(holder, name=name)
    print("A_ACQUIRED" if ok else "A_FAILED")
    time.sleep(2.5)
    return 0 if ok else 1


def _child_b(name: str) -> int:
    holder = _Holder()
    ok = _single_instance(holder, name=name)
    print("B_ACQUIRED_UNEXPECTED" if ok else "B_BLOCKED")
    return 0 if not ok else 1


def main():
    if len(sys.argv) > 2:
        name, role = sys.argv[1], sys.argv[2]
        return _child_a(name) if role == "A" else _child_b(name)
    name = "AstroSwarm-Test-" + str(time.time_ns())
    a = subprocess.Popen(
        [sys.executable, __file__, name, "A"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    time.sleep(0.8)
    b = subprocess.run(
        [sys.executable, __file__, name, "B"],
        capture_output=True, text=True, timeout=10,
    )
    out_a, _ = a.communicate(timeout=10)
    print("A:", out_a.strip())
    print("B:", b.stdout.strip())
    assert "A_ACQUIRED" in out_a, out_a
    assert "B_BLOCKED" in b.stdout, b.stdout
    print("SINGLE_INSTANCE_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
