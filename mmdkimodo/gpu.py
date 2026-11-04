"""GPU とメインメモリの診断。高速モード（テキストの読み取りも GPU）が使えるか、低負荷モード（テキストの読み取りは CPU）で足りるかを決める。

窓（app.py）の Python には torch が無いので、nvidia-smi とWindows の関数で読む。
目安の数字は 11-04 に RTX 3090・メインメモリ 64GB で測った値から（README の「動作モード」）。
"""
import ctypes
import shutil
import subprocess
from dataclasses import dataclass

# 高速モード: テキストの読み取り（Llama-3-8B・bfloat16）約 16.8GB ＋ Kimodo ＋ MotionBricks
FAST_VRAM_GB = 20.0
# 低負荷モード: Kimodo 1.5GB ＋ MotionBricks 1.0GB（常駐を片付けた時の差。11-04）。MMD の描画と Windows の分を見て 6GB
LOW_VRAM_GB = 6.0
# 低負荷モードのメインメモリ: テキストの読み取りと Kimodo の常駐で約 15.3GB（11-04）＋ MMD・Windows の分
LOW_RAM_GB = 24.0


@dataclass
class Diagnosis:
    gpu: str            # GPU の名前（無ければ ""）
    vram_gb: float      # VRAM の合計
    vram_free_gb: float # 今空いている VRAM
    ram_gb: float       # メインメモリの合計
    ram_free_gb: float  # 今空いているメインメモリ
    fast_ok: bool       # 高速モードが使える
    low_ok: bool        # 低負荷モードが使える
    note: str           # 窓に出す一言

    def summary(self):
        if not self.gpu:
            return self.note
        return f"{self.gpu}（VRAM {self.vram_gb:.0f}GB）・メインメモリ {self.ram_gb:.0f}GB"


class _MemoryStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _ram():
    st = _MemoryStatus()
    st.dwLength = ctypes.sizeof(st)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
    return st.ullTotalPhys / 2**30, st.ullAvailPhys / 2**30


def _gpu():
    """(名前, VRAM の合計 GB, 空き GB)。NVIDIA の GPU が無ければ None。一番 VRAM の大きいものを使う（Kimodo は cuda:0 を使う）。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    out = subprocess.run([exe, "--query-gpu=index,name,memory.total,memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if out.returncode != 0:
        return None
    rows = []
    for line in out.stdout.strip().splitlines():
        index, name, total, used = [x.strip() for x in line.split(",")]
        rows.append((int(index), name, float(total) / 1024, (float(total) - float(used)) / 1024))
    if not rows:
        return None
    first = min(rows)   # Kimodo・MotionBricks は cuda:0（番号 0）を使う
    return first[1], first[2], first[3]


def diagnose():
    ram, ram_free = _ram()
    g = _gpu()
    if g is None:
        return Diagnosis("", 0.0, 0.0, ram, ram_free, False, False,
                         "NVIDIA の GPU が見つかりません（Kimodo・MotionBricks は NVIDIA の GPU が要ります）")
    name, vram, vram_free = g
    fast_ok = vram >= FAST_VRAM_GB
    low_ok = vram >= LOW_VRAM_GB and ram >= LOW_RAM_GB
    if fast_ok:
        note = "高速モードも使えます"
    elif low_ok:
        note = f"低負荷モードで動きます（高速モードは VRAM {FAST_VRAM_GB:.0f}GB 以上）"
    elif vram < LOW_VRAM_GB:
        note = f"VRAM が足りないかもしれません（低負荷モードの目安 {LOW_VRAM_GB:.0f}GB 以上）"
    else:
        note = f"メインメモリが足りないかもしれません（低負荷モードの目安 {LOW_RAM_GB:.0f}GB 以上）"
    return Diagnosis(name, vram, vram_free, ram, ram_free, fast_ok, low_ok, note)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    d = diagnose()
    print(d.summary(), "→", d.note, f"（空き VRAM {d.vram_free_gb:.1f}GB・空きメモリ {d.ram_free_gb:.1f}GB）")
