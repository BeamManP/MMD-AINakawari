"""11-18: 「全ての親に載せる」で全部を作った後、長さなどを変えて全部を作り直すと、前回の元のキーに戻してから作るか（作り物の MMD・Kimodo は呼ばない）。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_root_redo_1118.py

11-13 までは、前回打った全ての親のキーがマスターのキーと区別できず、腰の通り道の目印になって載らなかった（DEVELOPMENT.md の「残っている穴」）。
1. 前回全ての親に載せた・全部 → 長さを変えて全部: 前回の元に戻す（全ての親は 0F だけ・体も前回の元）
2. 前回全ての親に載せていない・全部 → 長さを変えて全部: 戻さない（今までどおり）
3. 前回全ての親に載せた・全部 → 範囲を選んで作る: 戻さない（前回作った所の外の結果を消さない）
4. 前回全ての親に載せた・全部 → その後に全ての親を手で直した: 戻さない（マスターのキー）
5. 前回全ての親に載せた・全部 → 同じ長さで全部（今までの作り直し）: 戻す
モデルは Tda式初音ミク V4X、動きは work\\demo のキーだけの VMD（30F おき）。どちらも手元に無ければ止める。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from mmd_ainakawari import pipeline, runner, vmd  # noqa: E402

PMX = r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\UserFile\Model\Tda式初音ミクV4X_Ver1.00\Tda式初音ミクV4X_Ver1.00.pmx"
DEMO = os.path.join(HERE, "work", "demo", "demo_keys_20261106_023634.vmd")
for p in (PMX, DEMO):
    if not os.path.exists(p):
        sys.exit(f"確かめに使う物がありません: {p}")
TMP = tempfile.mkdtemp(prefix="ainakawari_check_")
ROOT = vmd.vmd_name(pipeline.ROOT_BONE)
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'OK ' if ok else 'NG '} {name}" + (f" … {detail}" if detail else ""))


class FakeLink:
    """runner.generate が使う MMDLink の口だけを持つ作り物。"""
    key = "check-1118"

    def __init__(self, motion):
        self.motion = motion

    def current_frame(self):
        return 0

    def state(self):
        return {"model_selected": True, "model": "Tda式初音ミクV4X"}

    def selected_model(self):
        return {"path": PMX, "name": "Tda式初音ミクV4X"}

    def read_motion(self, path):
        vmd.write(path, self.motion)
        return vmd.read(path)

    def load_motion(self, path, frame=0, **kw):
        pass

    def set_frame(self, frame):
        pass


class Captured(Exception):
    pass


def root_key(frame, x):
    return vmd.BoneKey(pipeline.ROOT_BONE, frame, np.array([x, 0.0, 0.0]), np.array([0.0, 0.0, 0.0, 1.0]))


demo = vmd.read(DEMO)
start = vmd.read(DEMO)
start.bones = [k for k in start.bones if k.frame == 0 and k.name != ROOT] + [root_key(0, 0.0)]   # 前回の元: 0F の立ち姿勢だけ
made = vmd.read(DEMO)
made.bones = [k for k in made.bones if k.name != ROOT] + [root_key(0, 0.0), root_key(60, 5.0), root_key(120, 9.0)]   # 前回の結果: 全ての親に載せた
backup0, out0 = os.path.join(TMP, "backup0.vmd"), os.path.join(TMP, "out0.vmd")
vmd.write(backup0, start)
vmd.write(out0, made)


def original_for(settings, current, prev_settings, root_written):
    """generate が prepare に渡す元の動き。"""
    previous = {"backup": backup0, "output": out0, "span": runner._span_key(prev_settings), "root_written": root_written}
    seen = {}

    def capture(pmx, motion, *a, **k):
        seen["original"] = motion
        raise Captured()

    real = pipeline.prepare
    pipeline.prepare = capture
    try:
        runner.generate(settings, log=lambda _l: None, link=FakeLink(current), previous=previous)
    except Captured:
        pass
    finally:
        pipeline.prepare = real
    return seen.get("original")


def roots(m):
    return sorted(k.frame for k in m.bones if k.name == ROOT) if m is not None else None


def body_frames(m):
    """書き戻す骨（上半身）のキーのフレーム。指など書き戻さない骨は今の MMD の物を残す決まり（11-07）なので見ない。"""
    upper = vmd.vmd_name("上半身")   # i18n: skip
    return sorted({k.frame for k in m.bones if k.name == upper}) if m is not None else None


base = dict(prompt="A person walks forward.", use_keys=False, root_move=True, root_turn=True)
prev = runner.Settings(length=150, **base)

o = original_for(runner.Settings(length=200, **base), vmd.read(out0), prev, True)
check("1. 載せた全部 → 長さを変えて全部: 全ての親は 0F だけに戻る", roots(o) == [0], f"{roots(o)}")
check("1. 体も前回の元（0F だけ）に戻る", body_frames(o) == [0], f"{body_frames(o)}")

o = original_for(runner.Settings(length=200, **base), vmd.read(out0), prev, False)
check("2. 載せていない全部 → 長さを変えて全部: 戻さない", roots(o) == [0, 60, 120], f"{roots(o)}")

o = original_for(runner.Settings(range_start=0, range_end=90, **base), vmd.read(out0), prev, True)
check("3. 載せた全部 → 範囲を選んで作る: 戻さない", roots(o) == [0, 60, 120], f"{roots(o)}")

edited = vmd.read(out0)
edited.bones = [k for k in edited.bones if not (k.name == ROOT and k.frame == 120)] + [root_key(120, 12.0)]
o = original_for(runner.Settings(length=200, **base), edited, prev, True)
check("4. その後に全ての親を手で直した: 戻さない", roots(o) == [0, 60, 120], f"{roots(o)}")

o = original_for(runner.Settings(length=150, **base), vmd.read(out0), prev, True)
check("5. 同じ長さで全部（今までの作り直し）: 戻す", roots(o) == [0], f"{roots(o)}")

print("---")
print("全部 OK" if all(results) else f"NG {results.count(False)} 件")
sys.exit(0 if all(results) else 1)
