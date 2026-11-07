"""11-07 の Codex のレビュー 5 件を、作り物の MMD で確かめる（窓の Python・mmd-mcp の .venv で回す。Kimodo は呼ばない）。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_review_1107.py

1. 作り直しで、書き戻さない骨（指など）と表情・表示/IK を今の MMD の物から取るか
2. 読み込む直前に、生成を始めた時と違うモデルが選ばれていたら、キーを消さずに止まるか
3. 読み込みが失敗したら、バックアップを読み込み直すか
4. IK をオフにしたフレームの姿勢を、IK を解かずに読むか
5. 長い日本語のモデル名で、書く・読む・書くを繰り返しても止まらないか
モデルは Tda式初音ミク V4X、動きは work\\demo のキーだけの VMD（30F おき）。どちらも手元に無ければ止める。
"""
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from mmd_ainakawari import mmd_link, mmd_memory, pipeline, runner, vmd  # noqa: E402

PMX = r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\UserFile\Model\Tda式初音ミクV4X_Ver1.00\Tda式初音ミクV4X_Ver1.00.pmx"
DEMO = os.path.join(HERE, "work", "demo", "demo_keys_20261106_023634.vmd")
for p in (PMX, DEMO):
    if not os.path.exists(p):
        sys.exit(f"確かめに使う物がありません: {p}")
TMP = tempfile.mkdtemp(prefix="ainakawari_check_")
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'OK ' if ok else 'NG '} {name}" + (f" … {detail}" if detail else ""))


def tail_with_ik(motion, off_names, frame=0):
    """motion の表示/IK の欄を、frame で off_names の IK だけオフにした 1 行に差し替えた tail を返す（表情・カメラ・照明・影はそのまま）。"""
    _morphs, iks = mmd_memory.read_pmx_names(PMX)
    head = vmd.split_tail(motion.tail)[0]
    row = struct.pack("<IBI", frame, 1, len(iks))
    for n in iks:
        row += n.encode("cp932", errors="replace")[:20].ljust(20, b"\0") + bytes([0 if n in off_names else 1])
    return head + struct.pack("<I", 1) + row


class FakeLink:
    """runner.generate が使う MMDLink の口だけを持つ作り物。読み込みは記録するだけ。"""
    key = "check-1107"

    def __init__(self, motion):
        self.motion, self.model, self.loaded = motion, PMX, []

    def current_frame(self):
        return 0

    def state(self):
        return {"model_selected": True, "model": "Tda式初音ミクV4X"}

    def selected_model(self):
        return {"path": self.model, "name": "Tda式初音ミクV4X"}

    def read_motion(self, path):
        vmd.write(path, self.motion)
        return vmd.read(path)

    def load_motion(self, path, frame=0, **kw):
        self.loaded.append((path, kw))

    def set_frame(self, frame):
        pass


class Captured(Exception):
    pass


# ---- 1. 作り直しで、ほかの編集が残るか -------------------------------------------------------------
demo = vmd.read(DEMO)
backup0 = os.path.join(TMP, "backup0.vmd")
out0 = os.path.join(TMP, "out0.vmd")
vmd.write(backup0, demo)
vmd.write(out0, demo)   # 前回の結果（書き戻す骨は今の MMD と同じ）
current = vmd.read(DEMO)
finger = vmd.BoneKey("右人指１", 45, np.zeros(3), np.array([0.0, 0.0, 0.3826834, 0.9238795]))
current.bones.append(finger)   # 生成の後に足した指のキー
current.tail = tail_with_ik(current, {"左足ＩＫ"}, frame=0)   # 生成の後に変えた表示/IK
settings = runner.Settings(prompt="A person walks forward.")
previous = {"backup": backup0, "output": out0, "span": runner._span_key(settings)}
seen = {}
real_prepare = pipeline.prepare


def capture(pmx, motion, *a, **k):
    seen["original"] = motion
    raise Captured()


pipeline.prepare = capture
try:
    runner.generate(settings, log=lambda _l: None, link=FakeLink(current), previous=previous)
except Captured:
    pass
finally:
    pipeline.prepare = real_prepare
orig = seen.get("original")
kept = orig is not None and any(k.name == "右人指１" and k.frame == 45 for k in orig.bones)
check("1. 作り直しで、生成の後に足した指のキーが残る", kept)
check("1. 作り直しで、生成の後に変えた表示/IK が残る", orig is not None and orig.tail == current.tail)
body = {(k.name, k.frame) for k in demo.bones}
check("1. 書き戻す骨のキーは前回の元のキーのまま", orig is not None and body <= {(k.name, k.frame) for k in orig.bones})


# ---- 2・3. 読み込む直前の確かめと、失敗の戻し ------------------------------------------------------
class Calls:
    def __init__(self, load_ok=(True,)):
        self.log, self.load_ok = [], list(load_ok)


def fake_link(selected, calls):
    link = mmd_link.MMDLink(hwnd=1)
    link.state = lambda: {"model_selected": True, "model": os.path.basename(selected)}
    link.selected_model = lambda: {"path": selected, "name": os.path.basename(selected)}
    link.current_frame = lambda: 0
    mmd_link.playback.get = lambda hwnd=None: {"playing": False}
    mmd_link.timeline.select_range = lambda *a, **k: (calls.log.append("select"), {"status": "completed"})[1]
    mmd_link.edit_actions.perform = lambda *a, **k: (calls.log.append("delete"), {"status": "completed"})[1]
    mmd_link.scene.set_frame = lambda *a, **k: None

    def load_file(kind, path, hwnd=None):
        ok = calls.load_ok.pop(0) if calls.load_ok else True
        calls.log.append(("load", os.path.basename(path), ok))
        if ok == "raise":   # mmd-mcp はファイルが無い時などに例外を投げる
            raise ValueError("MMD has a modal dialog open.")
        return {"status": "completed" if ok else "failed"}
    mmd_link.files.load_file = load_file
    return link


calls = Calls()
link = fake_link(r"C:\other\別のモデル.pmx", calls)
try:
    link.load_motion(out0, 0, model=PMX)
    stopped = False
except (RuntimeError, TypeError) as e:
    stopped = isinstance(e, RuntimeError)
check("2. 違うモデルが選ばれていたら、キーを消さずに止まる", stopped and "delete" not in calls.log, str(calls.log))

calls = Calls(load_ok=(False, True))
link = fake_link(PMX, calls)
try:
    link.load_motion(out0, 0, model=PMX, restore=backup0)
    msg = ""
except (RuntimeError, TypeError) as e:
    msg = str(e)
restored = ("load", "backup0.vmd", True) in calls.log
check("3. 読み込みが失敗したら、バックアップを読み込み直す", restored, str(calls.log))
check("3. 失敗は知らせる（黙って成功にしない）", bool(msg) and "TypeError" not in type(msg).__name__)

calls = Calls(load_ok=("raise", True))
link = fake_link(PMX, calls)
try:
    link.load_motion(out0, 0, model=PMX, restore=backup0)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("3. 読み込みが例外を投げても、バックアップを読み込み直す", ("load", "backup0.vmd", True) in calls.log and "戻しました" in msg,
      str(calls.log))


# ---- 11-07 夜: フレームを移す所が、読み込みの直後のタイミングで落ちる（マスター） -------------------
def flaky(fails):
    """最初の fails 回は mmd-mcp と同じ RuntimeError を投げ、その後は通る set_frame。"""
    state = {"n": 0}

    def set_frame(*a, **k):
        state["n"] += 1
        if state["n"] <= fails:
            raise RuntimeError("MMD did not display the requested frame in the same model context.")
    return set_frame, state


calls = Calls()
link = fake_link(PMX, calls)
mmd_link.scene.set_frame, st = flaky(1)
link.set_frame(30, wait=0)
check("フレームを移す所が 1 回落ちても、やり直して通る", st["n"] == 2, f"{st['n']} 回")

calls = Calls()
link = fake_link(PMX, calls)
link.current_frame = lambda: 5   # 消した後で、フレームが 0F からずれていた
mmd_link.scene.set_frame, st = flaky(0)
real_set = link.set_frame
moves = []


def set_after_delete(frame, **k):
    moves.append(frame)
    if "delete" in calls.log:   # 消した後で移ろうとした時だけ、何度やっても落ちる
        raise RuntimeError("MMD did not display the requested frame in the same model context.")
    return real_set(frame, wait=0)


link.set_frame = set_after_delete
try:
    link.load_motion(out0, 0, model=PMX, restore=backup0)
    msg = ""
except RuntimeError as e:
    msg = str(e)
check("消した後でフレームを移せなくても、戻しの手順に入って知らせる（黙って消えたままにしない）",
      "delete" in calls.log and moves[0] == 0 and "バックアップ" in msg, f"{calls.log}・{msg[:60]}")

lines = []
s3 = runner.Settings(prompt="A person walks forward.", smooth_stop=False)   # MotionBricks は呼ばない


class ReturnFails(FakeLink):
    def return_to(self, frame):
        return "MMD did not display the requested frame in the same model context."


rf = ReturnFails(vmd.read(DEMO))
real_run = pipeline.run_kimodo
real_build = pipeline.build_motion
pipeline.run_kimodo = lambda job, *a, **k: {"key_max_error_m": [0.0]}
pipeline.build_motion = lambda job, result, *a, **k: vmd.Motion(model_name=demo.model_name, bones=[])
try:
    r = runner.generate(s3, log=lines.append, link=rf, previous={})
    ok = r is not None and any("戻せませんでした" in l for l in lines) and any(l.startswith("できました") for l in lines)
except Exception as e:
    ok, lines = False, [f"{type(e).__name__}: {e}"]
finally:
    pipeline.run_kimodo, pipeline.build_motion = real_run, real_build
check("最後に押した時のフレームへ戻せなくても、生成は失敗にしない（ログで知らせる）", ok, lines[-1][:80] if lines else "")


# ---- 4. IK をオフにしたフレームの姿勢 --------------------------------------------------------------
def keys_of(motion):
    job = pipeline.prepare(PMX, motion, "A person walks forward.", context_keys=True)
    return job.request["keys"]


on = vmd.read(DEMO)
off = vmd.read(DEMO)
off.tail = tail_with_ik(off, {"右足ＩＫ"}, frame=0)
ka, kb = keys_of(on), keys_of(off)
differ = any(not np.allclose(a["local_rot"], b["local_rot"], atol=1e-6) for a, b in zip(ka, kb))
check("4. 右足 IK をオフにすると、渡す姿勢が変わる", differ)


# ---- 5. 長い日本語のモデル名 ------------------------------------------------------------------------
m = vmd.read(DEMO)
m.model_name = "A" + "あ" * 10
p1, p2 = os.path.join(TMP, "name1.vmd"), os.path.join(TMP, "name2.vmd")
try:
    vmd.write(p1, m)
    vmd.write(p2, vmd.read(p1))
    again = vmd.read(p2).model_name
    ok5 = again == vmd.read(p1).model_name and "\ufffd" not in again
    detail = again
except UnicodeEncodeError as e:
    ok5, detail = False, f"UnicodeEncodeError: {e}"
check("5. 長い日本語のモデル名で、書く・読む・書くが通り、文字化けしない", ok5, detail)

print(f"---\n{sum(results)}/{len(results)} 通った")
sys.exit(0 if all(results) else 1)
