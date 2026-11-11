"""11-11 issue #1: 親の骨が子より後に計算されるモデル（親の変形階層が高い・親が物理後）で、キーの間引きが KeyError で止まっていた件を確かめる。

    work\\release\\stage\\MMD-AINakawari\\python\\python.exe -X utf8 tests\\check_parent_order_1111.py

報告のモデル（レミリア・S）は手元に無いので、Tda式初音ミクの「左腕」「頭」の変形階層を上げて、子（左ひじ・左手首・目など）より後に回る並びを作る。
間引きの全身の確かめ（thin.Thinner._poser）が落ちずに、mmd_skel.MMDSkeleton.pose（IK なし）と同じ位置を出すかを見る。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from mmd_ainakawari import mmd_skel, thin, vmd  # noqa: E402

PMX = r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\UserFile\Model\Tda式初音ミクV4X_Ver1.00\Tda式初音ミクV4X_Ver1.00.pmx"
DEMO = os.path.join(HERE, "work", "demo", "demo_keys_20261106_023634.vmd")
for p in (PMX, DEMO):
    if not os.path.exists(p):
        sys.exit(f"確かめに使う物がありません: {p}")
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'OK ' if ok else 'NG '} {name}" + (f" … {detail}" if detail else ""))


sk = mmd_skel.MMDSkeleton(PMX)
moved = [sk.i("左腕"), sk.i("頭")]
for p in moved:
    sk.bones[p]["layer"] = 5   # 子より後に回す（mmd_skel の順の決め方そのままで並べ直す）
sk.order = sorted(range(len(sk.bones)), key=lambda i: (bool(sk.bones[i]["flags"] & 0x1000), sk.bones[i]["layer"], i))
sk.rank = {i: r for r, i in enumerate(sk.order)}
late = [i for i in sk.order if sk.parent[i] in moved and sk.rank[sk.parent[i]] > sk.rank[i]]
check("作った骨の並びで、親が子より後に回る骨がある", bool(late), ", ".join(sk.names[i] for i in late))

motion = vmd.read(DEMO)
tracks = thin._pmx_tracks(sk, motion)
frames = list(range(0, max(k.frame for k in motion.bones) + 1, 5))
watch = [sk.i(n) for n in ("左手首", "左ひじ", "左目", "右手首", "右足首")]
try:
    got = thin.Thinner(sk, None, thin.DEFAULT_LEVEL)._poser(watch)(tracks, frames)
    err = ""
except Exception as e:   # 前は KeyError
    got, err = None, f"{type(e).__name__}: {e}"
check("間引きの全身の確かめが、落ちずに通る", got is not None, err)

if got is not None:
    worst = 0.0
    for t, f in enumerate(frames):
        rot, pos = {}, {}
        for name, keys in tracks.items():
            tr, r = thin._sample_all(keys, [f])
            rot[name], pos[name] = r[0] / np.linalg.norm(r[0]), tr[0]
        _G, P = sk.pose(rot, pos, solve_ik=False)
        worst = max(worst, float(np.abs(P[watch] - got[t]).max()))
    check("mmd_skel.pose（IK なし）と同じ位置になる", worst < 1e-4, f"差の最大 {worst:.2e}（{len(frames)} フレーム）")

print("---")
print(f"{sum(results)}/{len(results)} 通った")
sys.exit(0 if all(results) else 1)
