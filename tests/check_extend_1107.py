"""「続きを足す」を「範囲の終わり（全部なら最後のキー）の後ろに N フレーム足す」にした直し（11-07 マスター）を、作り物の MMD で確かめる。
Kimodo は呼ばない（prepare までと、merge の上書き）。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_extend_1107.py

モデルは Tda式初音ミク V4X、動きは work\\demo のキーだけの VMD（30F おき）。どちらも手元に無ければ止める。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from mmd_ainakawari import paths, pipeline, runner, vmd  # noqa: E402
from mmd_ainakawari.mmd_skel import MMDSkeleton  # noqa: E402

PMX = r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\UserFile\Model\Tda式初音ミクV4X_Ver1.00\Tda式初音ミクV4X_Ver1.00.pmx"
DEMO = os.path.join(HERE, "work", "demo", "demo_keys_20261106_023634.vmd")
for p in (PMX, DEMO):
    if not os.path.exists(p):
        sys.exit(f"確かめに使う物がありません: {p}")
TMP = tempfile.mkdtemp(prefix="ainakawari_extend_")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'OK ' if ok else 'NG '} {name}" + (f" … {detail}" if detail else ""))


demo = vmd.read(DEMO)
skel = MMDSkeleton(PMX)
rt = pipeline.Retargeter(skel, paths.soma_json())
body = {vmd.vmd_name(n) for n in pipeline.body_bone_names(skel, rt)}
frames_by_name = {n: [k.frame for k in ks] for n, ks in demo.tracks().items()}
body_frames = sorted({f for n in body for f in frames_by_name.get(n, ())})
last = max(f for n in body | {pipeline.ROOT_BONE} for f in frames_by_name.get(n, ()))
print(f"デモの体のキー: {body_frames}（最後 {last}F）")

# ---- 区間の決め方 ----------------------------------------------------------------------------------
start, end, hit = pipeline.extend_plan(frames_by_name, body, 60, 100)
inner = [f for f in body_frames if 60 < f < 160]
check("範囲 30〜60F・長さ 100 なら 60F の後ろ 61〜160F を作る", (start, end) == (60, 160), f"{start}〜{end}")
check("足す所の体のキーを上書きの注意に出す", hit == inner or hit == inner + [160], f"{hit}")
start, end, hit = pipeline.extend_plan(frames_by_name, body, None, 50)
check("範囲が全部なら、最後のキーの後ろに足す", (start, end) == (last, last + 50) and hit == [], f"{start}〜{end}・{hit}")
try:
    pipeline.extend_plan(frames_by_name, body, 60, 0)
    check("長さ 0 は止める", False)
except ValueError:
    check("長さ 0 は止める", True)

# ---- prepare: 足す所の中のキーは使わない -------------------------------------------------------------
job = pipeline.prepare(PMX, demo, "A person walks forward.", frame_range=(60, 160), extend=True)
later = any(f > 160 for f in body_frames)
# 後ろにもキーがある時は、終わり（160F）の姿勢と、その後ろ 3 フレームもつなぐための目印にする（書き戻さない）
want = [57, 58, 59, 60] + ([160, 161, 162, 163] if later else [])
check("目印は 60F の姿勢・手前 3 フレーム（と、後ろにつなぐ時は 160F と後ろ 3 フレーム）だけ", job.frames == want, f"{job.frames}")
check("止める目印は付けない", not job.stop_frames)
check("後ろにキーがある時は、終わり（160F）の姿勢でつなぐ", (job.anchors == [60, 160]) == later, f"anchors {job.anchors}")
old = pipeline.prepare(PMX, demo, "A person walks forward.", frame_range=(60, 160))
check("範囲の作り直し（埋める）の方は、今までどおり中のキーも通る", set(inner) <= set(old.frames), f"{old.frames}")

# ---- merge: 足す所の体のキーは上書き、外のキーはそのまま ------------------------------------------
gen_bones = []
for n in sorted(body)[:5]:
    for f in range(61, 161 if not later else 160):
        gen_bones.append(vmd.BoneKey(n, f, np.zeros(3), np.array([0.0, 0.0, 0.0, 1.0])))
generated = vmd.Motion(model_name=demo.model_name, bones=gen_bones)
merged = pipeline.merge(demo, generated, job)
names = {k.name for k in gen_bones}
orig_inside = [k for k in demo.bones if k.name in names and 60 < k.frame < 160]
left = [k for k in merged.bones if k.name in names and 60 < k.frame < 160 and not any(k is g for g in gen_bones)]
check("足す所にあった体のキーは、作った動きに置き換わる", orig_inside and not left, f"元 {len(orig_inside)} 個・残り {len(left)} 個")
before = {(k.name, k.frame) for k in demo.bones if k.frame <= 60}
check("始まりより前のキーはそのまま", before <= {(k.name, k.frame) for k in merged.bones})


# ---- runner: 区間を決める所と、作り直し ----------------------------------------------------------
class Captured(Exception):
    pass


class FakeLink:
    key = "check-extend"

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


seen = {}
real_prepare = pipeline.prepare


def capture(pmx, motion, *a, **k):
    seen.clear()
    seen.update(k, motion=motion)
    raise Captured()


def run(settings, motion, previous=None):
    pipeline.prepare = capture
    try:
        runner.generate(settings, log=lambda _l: None, link=FakeLink(motion), previous=previous)
    except Captured:
        pass
    finally:
        pipeline.prepare = real_prepare
    return dict(seen)


s = runner.Settings(prompt="A person walks forward.", range_start=30, range_end=60, extend=100)
got = run(s, demo)
check("範囲 30〜60F で続きを足すと、prepare に 60〜160F・extend を渡す",
      got.get("frame_range") == (60, 160) and got.get("extend") is True and got.get("length") is None
      and got.get("stop_at_last_key") is False, f"{got.get('frame_range')}・{got.get('extend')}・{got.get('stop_at_last_key')}")
s_all = runner.Settings(prompt="A person walks forward.", extend=50)
got = run(s_all, demo)
check("全部で続きを足すと、最後のキーの後ろ", got.get("frame_range") == (last, last + 50), f"{got.get('frame_range')}")

# 作り直し: MMD の中身が前回の結果のままなら、前回の元から区間を決める（さらに後ろへ足さない）
backup0, out0 = os.path.join(TMP, "backup0.vmd"), os.path.join(TMP, "out0.vmd")
vmd.write(backup0, demo)
extended = vmd.read(DEMO)
extended.bones += [vmd.BoneKey(k.name, last + 50, k.pos, k.rot) for k in demo.bones if k.frame == last and k.name in body]
vmd.write(out0, extended)
previous = {"backup": backup0, "output": out0, "span": runner._span_key(runner.Settings(prompt="", extend=80))}
got = run(s_all, vmd.read(out0), previous)
check("長さを変えて作り直すと、前回の元の最後のキーから足し直す", got.get("frame_range") == (last, last + 50), f"{got.get('frame_range')}")
check("範囲が違う続き（30〜60F）は別の区間として扱う",
      runner._span_key(s) != runner._span_key(s_all) and runner._span_key(s) != runner._span_key(
          runner.Settings(prompt="", range_start=30, range_end=60)))

print(f"---\n{sum(results)}/{len(results)} 通った")
sys.exit(0 if all(results) else 1)
