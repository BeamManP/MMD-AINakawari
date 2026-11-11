"""窓の相手（MMD か MMM＝MikuMikuMoving か）を見分ける。app.py の Hub・App はここを通して相手を探し、やり取りの部品（link）を作る。

MMD の窓は mmd-mcp の list_windows（検証済みの MMD 9.32 x64 だけ）。MMM の窓は、MikuMikuMoving64.exe のプロセスのトップレベルの見える窓。
MMM とのやり取りは MMM の中の橋渡し（E:\\Projects\\MMM\\mmm-mcp の MmmBridge.dll）を通すので、MMM は 1 つだけ相手にする（橋渡しの待ち受けが 1 つのため）。
"""
import os
from dataclasses import dataclass

import psutil
import win32gui
import win32process

from mmd_mcp.windows import list_windows

MMM_EXE = "mikumikumoving64.exe"


@dataclass
class Host:
    hwnd: int
    kind: str            # "mmd" か "mmm"
    pid: int = 0
    process_started: float = 0.0

    @property
    def name(self):
        return "MMM" if self.kind == "mmm" else "MMD"

    def link(self):
        if self.kind == "mmm":
            from .mmm_link import MMMLink
            return MMMLink(self)
        from .mmd_link import MMDLink
        return MMDLink(self.hwnd)

    def scene_name(self):
        """場面（プロジェクト）の名前。題から取る。MMD は「…[場面の場所]」、MMM は「MikuMikuMoving - 名前 *」。"""
        title = win32gui.GetWindowText(self.hwnd) if win32gui.IsWindow(self.hwnd) else ""
        if self.kind == "mmm":
            name = title.partition(" - ")[2].rstrip(" *")
            return "" if name in ("", "新規プロジェクト") else name   # i18n: skip
        return os.path.basename(title.partition("[")[2].rstrip("]"))


def _mmm_windows():
    out = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetParent(hwnd):
            return
        if not win32gui.GetWindowText(hwnd).startswith("MikuMikuMoving"):
            return
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            p = psutil.Process(pid)
            if p.name().lower() != MMM_EXE:
                return
            out.append(Host(hwnd, "mmm", pid, p.create_time()))
        except psutil.Error:
            return
    win32gui.EnumWindows(visit, None)
    return out


def all_hosts():
    hosts = [Host(w.hwnd, "mmd", w.pid, w.process_started) for w in list_windows()]
    return hosts + _mmm_windows()


def find(hwnd):
    """その窓が MMD か MMM のトップレベルの窓なら Host。違えば None。"""
    return next((h for h in all_hosts() if h.hwnd == hwnd), None)


def front():
    """一番手前の MMD か MMM の窓。無ければ None。"""
    hosts = {h.hwnd: h for h in all_hosts()}
    order = []
    win32gui.EnumWindows(lambda hwnd, _: order.append(hwnd), None)  # 手前から順に並ぶ
    return next((hosts[h] for h in order if h in hosts), None)
