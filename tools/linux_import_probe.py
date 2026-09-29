"""Linux 导入探针：逐个 import qbotmanager 核心/任务模块，输出 OK/FAIL。
退出码 = 失败模块数。
"""
import importlib
import pkgutil
import sys

import qbotmanager.core


def _module_names(package) -> list:
    names = []
    for mod in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
        names.append(mod.name)
    return names


def main() -> int:
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    names = set(_module_names(qbotmanager.core))
    if target in ("all", "tasks"):
        try:
            tasks_pkg = importlib.import_module("qbotmanager.tasks")

            names |= set(_module_names(tasks_pkg))
        except Exception as exc:  # noqa: BLE001
            print("WARN tasks 包无法导入（headless 垫片待 M2）：", repr(exc))
    names = sorted(names)
    fails = []
    for name in names:
        try:
            importlib.import_module(name)
            print("OK  ", name)
        except Exception as exc:  # noqa: BLE001
            fails.append((name, repr(exc)))
            print("FAIL", name, repr(exc))
    print(f"---- {len(names) - len(fails)}/{len(names)} modules OK ----")
    return len(fails)


if __name__ == "__main__":
    sys.exit(main())
