# -*- coding: utf-8 -*-
"""AstroSwarm 独立卸载器：停服务 -> 删安装目录 -> 删程序文件夹（含自身）。"""
import json
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from qbotmanager.core.uninstall_standalone import (
    collect_info,
    run_uninstall,
)


_STAGE_PCT = {
    "正在停止服务": 35,
    "正在删除安装目录": 75,
    "正在删除程序文件夹": 95,
}

def _check_mode(out_path: str) -> int:
    """打包后自检：把卸载信息写入 JSON 后退出。"""
    try:
        info = collect_info()
        info["ok"] = True
    except Exception as e:  # noqa: BLE001
        info = {"ok": False, "error": repr(e)}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    return 0 if info.get("ok") else 1


class UninstallerApp:
    def __init__(self, root_override: str | None = None):
        self.root_override = root_override
        self.q = queue.Queue()

        self.win = tk.Tk()
        self.win.title("AstroSwarm 卸载程序")
        self.win.geometry("640x520")
        self.win.minsize(560, 440)

        pad = {"padx": 16, "pady": 6}

        tk.Label(self.win, text="AstroSwarm 卸载程序", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w", **pad)

        self.info_var = tk.StringVar()
        tk.Label(self.win, textvariable=self.info_var, justify="left",
                 font=("Microsoft YaHei UI", 10), fg="#333").pack(anchor="w", **pad)

        self.keep_act = tk.BooleanVar(value=True)
        tk.Checkbutton(
            self.win,
            text="保留激活状态（下次安装无需重新激活）",
            variable=self.keep_act,
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", **pad)

        self.log_text = tk.Text(self.win, height=10, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, **pad)

        self.bar = ttk.Progressbar(self.win, maximum=100, mode="determinate")
        self.bar.pack(fill="x", **pad)

        btns = tk.Frame(self.win)
        btns.pack(fill="x", **pad)
        self.btn_uninstall = tk.Button(btns, text="开始卸载", font=("Microsoft YaHei UI", 11, "bold"),
                                       bg="#c0392b", fg="white", command=self._start)
        self.btn_uninstall.pack(side="left")
        self.btn_cancel = tk.Button(btns, text="取消", font=("Microsoft YaHei UI", 11),
                                    command=self.win.destroy)
        self.btn_cancel.pack(side="right")

        self._refresh_info()
        self.win.after(100, self._poll)

    def _refresh_info(self):
        info = collect_info(self.root_override)
        lines = ["将卸载以下内容："]
        if info["install_root"]:
            lines.append("  - 机器人安装目录: " + info["install_root"])
        else:
            lines.append("  - 未检测到机器人安装目录（跳过）")
        if info["program_dir"]:
            lines.append("  - AstroSwarm 程序文件夹: " + info["program_dir"])
        else:
            lines.append("  - 独立运行模式：不会自动删除程序文件夹")
        lines.append("  - 启动记录（%APPDATA%\\QBotManager）")
        if info["license_exists"]:
            lines.append("  - 激活状态（按下方选项决定是否清除）")
        self.info_var.set("\n".join(lines))

    def _log(self, line):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _start(self):
        if messagebox.askyesno("确认卸载", "确定要卸载 AstroSwarm 吗？\n\n"
                               "将停止服务并删除安装目录、程序文件夹，且无法恢复。"):
            self.btn_uninstall.configure(state="disabled")
            self.btn_cancel.configure(state="disabled")
            threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        def stage(label):
            self.q.put(("stage", label))
        try:
            result = run_uninstall(
                clear_activation=not self.keep_act.get(),
                log=lambda line: self.q.put(("log", line)),
                on_stage=stage,
                root_override=self.root_override,
                remove_program=True,
            )
            self.q.put(("done", result))
        except Exception as e:  # noqa: BLE001
            self.q.put(("fail", str(e)))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "stage":
                    self._log("== " + payload + " ==")
                    self.bar["value"] = _STAGE_PCT.get(payload, min(100, self.bar["value"] + 5))
                elif kind == "done":
                    self.bar["value"] = 100
                    self._log("---- 卸载完成 ----")
                    self.btn_uninstall.configure(state="disabled")
                    self.btn_cancel.configure(state="normal")
                    messagebox.showinfo("卸载完成", "卸载完成。\n\n程序文件夹将在几秒后自动删除。")
                    self.win.destroy()
                    return
                elif kind == "fail":
                    self.bar["value"] = 0
                    self._log("!! " + payload)
                    self.btn_uninstall.configure(state="normal")
                    self.btn_cancel.configure(state="normal")
                    messagebox.showerror("卸载失败", payload)
                    return
        except queue.Empty:
            pass
        self.win.after(100, self._poll)

    def run(self):
        self.win.mainloop()


def main():
    argv = sys.argv
    if len(argv) >= 3 and argv[1] == "--check":
        sys.exit(_check_mode(argv[2]))
    root_override = None
    if len(argv) >= 3 and argv[1] == "--root":
        root_override = argv[2]
    UninstallerApp(root_override=root_override).run()


if __name__ == "__main__":
    main()
