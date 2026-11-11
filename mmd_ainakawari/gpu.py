"""GPU とメインメモリの診断。Kimodo・MotionBricks で足りるかを決める。

窓（app.py）の Python には torch が無いので、nvidia-smi とWindows の関数で読む。
目安の数字は 11-04・11-07 に RTX 3090・メインメモリ 64GB で測った値から（docs/DEVELOPMENT.md の「文の読み取り」）。
11-07 まで高速モード（VRAM 20GB 以上）と低負荷モード（メインメモリ 24GB 以上）の 2 段だったが、文の読み取りを GGUF にして 1 段にした。

計算の方式（paths.backend）が cuda の時は、今までどおり NVIDIA の GPU を nvidia-smi で見る。
directml・cpu の時（11-10。NVIDIA 以外の GPU・今の CUDA では動かない GPU）は、Windows が知っている GPU（レジストリ）を見る。
セットアップの前（方式がまだ決まっていない）で NVIDIA の GPU が無い時も、Windows が知っている GPU を出して「動く見込み」とする
（セットアップの試しの生成が DirectML で通れば、その方式になる）。
"""
import ctypes
import os
import shutil
import subprocess
from dataclasses import dataclass

from .i18n import _

# VRAM: Kimodo 1.5GB ＋ MotionBricks 1.0GB（常駐を片付けた時の差。11-04）。MMD の描画と Windows の分を見て 6GB
VRAM_GB = 6.0
# メインメモリ: 文の読み取り（llama-server・GGUF Q8_0）約 7.6GB（11-07）＋ Kimodo の常駐 ＋ MMD・Windows の分で 16GB。
# 16GB の PC は Windows が 15.8GB ほどと数えるので、判定は 15GB 以上にする。16GB の PC での実地は未確認
RAM_GB = 16.0
RAM_CHECK_GB = 15.0


@dataclass
class Diagnosis:
    gpu: str            # GPU の名前（無ければ ""）
    vram_gb: float      # VRAM の合計
    vram_free_gb: float # 今空いている VRAM
    ram_gb: float       # メインメモリの合計
    ram_free_gb: float  # 今空いているメインメモリ
    ok: bool            # 目安を満たす（GPU を調べられない時も、試せるので True）
    note: str           # 窓に出す一言
    backend: str = "cuda"   # 計算の方式（paths.BACKENDS）

    @property
    def usable(self):
        """生成できる見込みがある。GPU が無い・無効にされている時だけ False（調べられない時は試せる。足りないかもしれない時も試せる）。"""
        return bool(self.gpu) or self.ok

    def summary(self):
        if not self.gpu:
            return self.note
        vram = _("（VRAM {gb:.0f}GB）", gb=self.vram_gb) if self.vram_gb else ""   # NVIDIA 以外では分からないことがある
        return _("{gpu}{vram}・メインメモリ {ram:.0f}GB", gpu=self.gpu, vram=vram, ram=self.ram_gb)


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
        raise _Unknown(f"nvidia-smi が答えません（{type(e).__name__}）")  # i18n: skip
    if out.returncode != 0:
        raise _Unknown(f"nvidia-smi が失敗しました（{(out.stderr or out.stdout).strip()[:80]}）")  # i18n: skip
    rows = []
    try:
        for line in out.stdout.strip().splitlines():
            index, uuid, name, total, used = [x.strip() for x in line.split(",")]
            rows.append((index, uuid, name, float(total) / 1024, (float(total) - float(used)) / 1024))
    except ValueError:
        raise _Unknown(f"nvidia-smi の出力を読めません（{out.stdout.strip()[:80]}）")  # i18n: skip
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    want = visible.split(",")[0].strip() if visible is not None else "0"
    hits = [r for r in rows if r[0] == want] or [r for r in rows if want.startswith("GPU-") and r[1].startswith(want)]
    if len(hits) == 1:
        _, _, name, total, free = hits[0]
        return name, total, free
    if len(hits) > 1:   # 短い UUID は 1 枚に決まる時だけ（CUDA の決まり）
        raise _Unknown(f"CUDA_VISIBLE_DEVICES={visible!r} が GPU を 1 枚に決めていません")  # i18n: skip
    raise _Unknown(f"使う GPU（CUDA_VISIBLE_DEVICES={visible!r}）が見つかりません" if visible is not None else "GPU の一覧が空です")  # i18n: skip


def _adapters():
    """Windows が知っている GPU の [(名前, VRAM GB)]（VRAM の多い順）。読めなければ空。
    レジストリのディスプレイ アダプターの一覧から。VRAM は HardwareInformation.qwMemorySize（専用の分。内蔵 GPU は小さく出る）。"""
    import winreg

    found = []
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            for i in range(64):
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as key:
                        name = str(winreg.QueryValueEx(key, "DriverDesc")[0]).strip()
                        try:
                            size = winreg.QueryValueEx(key, "HardwareInformation.qwMemorySize")[0]
                            vram = (int.from_bytes(size, "little") if isinstance(size, bytes) else int(size)) / 2**30
                        except (OSError, ValueError, TypeError):
                            vram = 0.0
                except OSError:
                    continue
                if name and "Basic Display" not in name and "Basic Render" not in name:   # ドライバの無い時の仮の物は GPU として数えない
                    found.append((name, vram))
    except OSError:
        return []
    return sorted(found, key=lambda a: -a[1])


def _backend():
    """Kimodo の計算の方式。まだセットアップしていない・設定を読めない時は None（方式が決まっていない）。"""
    from . import paths
    try:
        if os.environ.get(paths.BACKEND_ENV) or "kimodo_backend" in paths.load():
            return paths.backend("kimodo")
    except paths.NotSetUp:
        pass
    return None


def _diagnose_other(backend, ram, ram_free):
    """NVIDIA の GPU を CUDA で使わない時の診断（DirectML・CPU。まだ方式が決まっていなくて NVIDIA の GPU が無い時も）。"""
    ram_ok = ram >= RAM_CHECK_GB
    ram_note = "" if ram_ok else _("。メインメモリが足りないかもしれません（目安 {gb:.0f}GB 以上）", gb=RAM_GB)
    if backend == "cpu":
        return Diagnosis("", 0.0, 0.0, ram, ram_free, True,
                         _("GPU を使わずに作ります（時間がかかります。2 秒の動きに 1 分ほど）") + ram_note, "cpu")
    adapters = _adapters()
    if not adapters:
        if backend == "directml":   # セットアップでは通っている。名前を読めないだけ
            return Diagnosis("", 0.0, 0.0, ram, ram_free, True, _("DirectML で動かします（GPU の名前は読めませんでした）") + ram_note, "directml")
        return Diagnosis("", 0.0, 0.0, ram, ram_free, True,
                         _("GPU が見つかりません。セットアップで試して、動けば GPU なしで作ります（時間がかかります）") + ram_note, "cpu")
    name, vram = adapters[0]
    if backend == "directml":
        note = _("この PC で動きます（DirectML）")
    else:   # まだセットアップしていない
        note = _("NVIDIA 以外の GPU です。DirectML で動かします（セットアップの試しの生成で確かめます）")
    return Diagnosis(name, vram, 0.0, ram, ram_free, ram_ok, note + ram_note, "directml")


def diagnose():
    ram, ram_free = _ram()
    backend = _backend()
    if backend in ("directml", "cpu"):
        return _diagnose_other(backend, ram, ram_free)
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible is not None and visible.split(",")[0].strip() in ("", "-1"):   # GPU を見せない設定。どちらのモードも動かない
        return Diagnosis("", 0.0, 0.0, ram, ram_free, False,
                         _("CUDA_VISIBLE_DEVICES={visible} で GPU が無効になっています（この設定を外してください）", visible=repr(visible)))
    try:
        g = _gpu()
    except _Unknown as e:   # 調べられない時も窓は開き、試せる。理由（nvidia-smi の名前など）は記録にだけ書く
        from . import applog
        applog.write(f"GPU を調べられませんでした: {e}")
        return Diagnosis("", 0.0, 0.0, ram, ram_free, True, _("GPU を調べられませんでした。「生成」を押して試してください"))
    if g is None:
        if backend is None:   # まだセットアップしていない。NVIDIA 以外の GPU なら DirectML で動かせる（11-10）
            return _diagnose_other(None, ram, ram_free)
        return Diagnosis("", 0.0, 0.0, ram, ram_free, False,
                         _("NVIDIA の GPU が見つかりません（計算の方式が CUDA になっています。「セットアップ」を押して入れ直してください）"))
    name, vram, vram_free = g
    ok = vram >= VRAM_GB and ram >= RAM_CHECK_GB
    if ok:
        note = _("この PC で動きます")
    elif vram < VRAM_GB:
        note = _("VRAM が足りないかもしれません（目安 {gb:.0f}GB 以上）", gb=VRAM_GB)
    else:
        note = _("メインメモリが足りないかもしれません（目安 {gb:.0f}GB 以上）", gb=RAM_GB)
    return Diagnosis(name, vram, vram_free, ram, ram_free, ok, note)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    d = diagnose()
    print(d.summary(), "→", d.note, f"（計算の方式 {d.backend}・空き VRAM {d.vram_free_gb:.1f}GB・空きメモリ {d.ram_free_gb:.1f}GB）")  # i18n: skip
    print("Windows が知っている GPU:", _adapters())  # i18n: skip
