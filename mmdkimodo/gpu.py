"""GPU とメインメモリの診断。高速モード（テキストの読み取りも GPU）が使えるか、低負荷モード（テキストの読み取りは CPU）で足りるかを決める。

窓（app.py）の Python には torch が無いので、nvidia-smi とWindows の関数で読む。
目安の数字は 11-04 に RTX 3090・メインメモリ 64GB で測った値から（README の「動作モード」）。
"""
import ctypes
import os
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


class _Unknown(Exception):
    """GPU を調べられなかった（nvidia-smi が答えない・失敗した・出力を読めない）。理由を持つ。"""


def _gpu():
    """使う GPU の (名前, VRAM の合計 GB, 空き GB)。nvidia-smi が無ければ None。

    Kimodo・MotionBricks は cuda:0 を使う。cuda:0 は CUDA_VISIBLE_DEVICES の最初の GPU（無ければ 0 番）で、
    常駐には CUDA_DEVICE_ORDER=PCI_BUS_ID を渡して nvidia-smi と同じ並びにしている（pipeline.kimodo_server・smooth_stop）。
    前は nvidia-smi の 0 番を決め打ちで見ていて、GPU が複数ある PC では診断と実際に使う GPU が食い違いえた（11-04 Codex のレビュー）。
    """
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--query-gpu=index,uuid,name,memory.total,memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as e:
        raise _Unknown(f"nvidia-smi が答えません（{type(e).__name__}）")
    if out.returncode != 0:
        raise _Unknown(f"nvidia-smi が失敗しました（{(out.stderr or out.stdout).strip()[:80]}）")
    rows = []
    try:
        for line in out.stdout.strip().splitlines():
            index, uuid, name, total, used = [x.strip() for x in line.split(",")]
            rows.append((index, uuid, name, float(total) / 1024, (float(total) - float(used)) / 1024))
    except ValueError:
        raise _Unknown(f"nvidia-smi の出力を読めません（{out.stdout.strip()[:80]}）")
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    want = visible.split(",")[0].strip() if visible is not None else "0"
    for index, uuid, name, total, free in rows:
        if want == index or (want and uuid.startswith(want)):
            return name, total, free
    raise _Unknown(f"使う GPU（CUDA_VISIBLE_DEVICES={visible!r}）が見つかりません" if visible is not None else "GPU の一覧が空です")


def diagnose():
    ram, ram_free = _ram()
    try:
        g = _gpu()
    except _Unknown as e:   # 調べられない時も窓は開く。高速は選べず、低負荷で試せる
        return Diagnosis("", 0.0, 0.0, ram, ram_free, False, True, f"GPU を調べられませんでした（{e}）。低負荷モードで試せます")
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
