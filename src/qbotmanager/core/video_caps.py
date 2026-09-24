# -*- coding: utf-8 -*-
"""视频背景能力探测：GPU / 显存 / 内存 / 渲染后端。"""
import ctypes

SOFTWARE_BACKENDS = {"Software", "Null", "Unknown"}


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


_IID_FACTORY1 = _GUID(0x770aae78, 0xf26f, 0x4dba, (0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87))
_IID_ADAPTER3 = _GUID(0x645967A4, 0x1392, 0x4310, (0xA7, 0x98, 0x80, 0x53, 0xCE, 0x3E, 0x93, 0xFD))


class _DXGI_ADAPTER_DESC(ctypes.Structure):
    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", ctypes.c_uint), ("DeviceId", ctypes.c_uint),
        ("SubSysId", ctypes.c_uint), ("Revision", ctypes.c_uint),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("AdapterLuid", ctypes.c_ulonglong),
    ]


class _DXGI_QUERY_VIDEO_MEMORY_INFO(ctypes.Structure):
    _fields_ = [("Budget", ctypes.c_ulonglong), ("CurrentUsage", ctypes.c_ulonglong),
                ("AvailableForReservation", ctypes.c_ulonglong),
                ("CurrentReservation", ctypes.c_ulonglong)]


def _vfn(addr, idx, restype, *argtypes):
    vp = ctypes.POINTER(ctypes.c_void_p).from_address(addr)
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(
        ctypes.cast(vp[idx], ctypes.c_void_p).value)


def query_gpu():
    """枚举显卡，返回显存最大的适配器；显存占用查询失败时 usage=None。"""
    try:
        dxgi = ctypes.WinDLL("dxgi")
        f = dxgi.CreateDXGIFactory1
        f.argtypes = [ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        f.restype = ctypes.c_long
        factory = ctypes.c_void_p()
        if f(ctypes.byref(_IID_FACTORY1), ctypes.byref(factory)) != 0 or not factory.value:
            return None
        best = None
        adapters = []
        for i in range(8):
            adapter = ctypes.c_void_p()
            hr = _vfn(factory.value, 7, ctypes.c_long, ctypes.c_uint,
                      ctypes.POINTER(ctypes.c_void_p))(factory, i, ctypes.byref(adapter))
            if hr != 0 or not adapter.value:
                break
            desc = _DXGI_ADAPTER_DESC()
            if _vfn(adapter.value, 8, ctypes.c_long,
                    ctypes.POINTER(_DXGI_ADAPTER_DESC))(adapter, ctypes.byref(desc)) != 0:
                continue
            item = {"name": desc.Description.strip(),
                    "vram_mb": round(desc.DedicatedVideoMemory / 1048576.0, 1),
                    "usage": None}
            adapters.append(item)
            if best is None or item["vram_mb"] > best["vram_mb"]:
                best = item
        if best is None:
            return None
        if adapters:
            a0 = ctypes.c_void_p()
            if _vfn(factory.value, 7, ctypes.c_long, ctypes.c_uint,
                    ctypes.POINTER(ctypes.c_void_p))(factory, 0, ctypes.byref(a0)) == 0 and a0.value:
                a3 = ctypes.c_void_p()
                if _vfn(a0.value, 0, ctypes.c_long, ctypes.POINTER(_GUID),
                        ctypes.POINTER(ctypes.c_void_p))(a0, ctypes.byref(_IID_ADAPTER3),
                                                         ctypes.byref(a3)) == 0 and a3.value:
                    m = _DXGI_QUERY_VIDEO_MEMORY_INFO()
                    if _vfn(a3.value, 12, ctypes.c_long, ctypes.c_uint,
                            ctypes.POINTER(_DXGI_QUERY_VIDEO_MEMORY_INFO))(a3, 0, ctypes.byref(m)) == 0:
                        best["usage"] = {"budget_mb": round(m.Budget / 1048576.0, 1),
                                         "used_mb": round(m.CurrentUsage / 1048576.0, 1)}
        return best
    except Exception:  # noqa: BLE001
        return None


def query_ram():
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64)]
    m = MS()
    m.dwLength = ctypes.sizeof(MS)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        return {"total_mb": round(m.ullTotalPhys / 1048576.0, 1),
                "avail_mb": round(m.ullAvailPhys / 1048576.0, 1)}
    return None


def backend_name(widget):
    """返回 QQuickWidget 实际使用的渲染后端名。"""
    try:
        from PySide6.QtQuick import QSGRendererInterface

        api = widget.quickWindow().rendererInterface().graphicsApi()
        for n in QSGRendererInterface.GraphicsApi:
            if api == n:
                return n.name
    except Exception:  # noqa: BLE001
        pass
    return "Unknown"
