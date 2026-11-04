"""Kimodo の渡し方を直した時の試験台。tools/bench_scenes の VMD から、MMD を通さずに pipeline.prepare → run_kimodo で作り、数字を出す。

    E:\Projects\mmd-mcp\.venv\Scripts\python.exe tools\kimodo_bench.py [名前の一部 …] [--seeds=2,7]

11-04 昼に作った（README の「Kimodo の渡し方の突き合わせ」）。直す前と後で同じシードの数字を比べる。モデルの場所はマスターの MMD のもの。

数字（Kimodo の座標・m）:
  キー: キーのフレームの関節の位置のずれの最大（Kimodo の後処理の後）
  腰目印: 全ての親だけのキー（腰の XZ）とのずれの最大・向きのずれの最大（度）
  跳び: 腰の 1 フレームの動きの最大（m/フレーム）と、その前後の平均との比（区間のつなぎ目の跳びの目安）
  関節: 1 フレームで回った量の最大（度）
  足滑り: 床から 3cm 以内のつま先・かかとの水平の速さの平均（m/s）
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from mmdkimodo import pipeline, vmd
from mmdkimodo import quat as Q

HERE = os.path.dirname(os.path.abspath(__file__))
SCENES_DIR = os.path.join(HERE, "bench_scenes")
WORK = os.path.join(os.path.dirname(HERE), "work", "bench")
TDA = r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\UserFile\Model\Tda式初音ミクV4X_Ver1.00\Tda式初音ミクV4X_Ver1.00.pmx"
NOINIKU = r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\UserFile\Model\EL-Pr237(№1209)\ノイニク.pmx"
SCENES = [
    dict(name="走って止まる", pmx=TDA, vmd=os.path.join(SCENES_DIR, "run_stop.vmd"),
         prompt="A person runs forward and comes to a stop.", kw=dict(cfg=(6.0, 2.0), stop_at_last_key=True)),
    dict(name="スラローム", pmx=TDA, vmd=os.path.join(SCENES_DIR, "slalom.vmd"),
         prompt="A person runs along a winding path.", kw=dict()),
    dict(name="パンチ", pmx=NOINIKU, vmd=os.path.join(SCENES_DIR, "punch_noiniku.vmd"),
         prompt="A person takes a fighting stance and steps forward.\n45: A person throws a right straight punch.\n60: A person holds the follow-through and relaxes.",
         kw=dict(length=91)),
    dict(name="区間の始めにキー", pmx=TDA, vmd=os.path.join(SCENES_DIR, "run_stop.vmd"),
         prompt="A person runs forward.\n30: A person slows down and stops.\n60: A person stands still.", kw=dict(length=90, cfg=(6.0, 2.0))),
]
SOMA = json.load(open(pipeline.SOMA_JSON, encoding="utf-8"))
NEUTRAL = np.array(SOMA["neutral_joints"])
NAMES = SOMA["names"]
FEET = [NAMES.index(n) for n in ("LeftToeBase", "RightToeBase", "LeftFoot", "RightFoot")]


def fk(root, local):
    T = len(root)
    P = np.zeros((T, 30, 3))
    for t in range(T):
        G = [None] * 30
        for j, p in enumerate(SOMA["parents"]):
            if p < 0:
                G[j] = local[t, j]
                P[t, j] = root[t]
            else:
                G[j] = Q.mul(G[p], local[t, j])
                P[t, j] = P[t, p] + Q.rotate(G[p], NEUTRAL[j] - NEUTRAL[p])
    return P


def measure(job, res):
    T = res["num_frames"]
    root = np.array(res["root"]).reshape(T, 3)
    rot = np.array(res["local_rot"]).reshape(T, 30, 4)
    T = min(T, job.num_frames)
    root, rot = root[:T], rot[:T]
    P = fk(root, rot)
    step = np.linalg.norm(np.diff(root[:, [0, 2]], axis=0), axis=1)
    i = int(step.argmax())
    around = np.r_[step[max(0, i - 4):i], step[i + 1:i + 5]]
    jump = step[i] / max(1e-6, around.mean()) if len(around) else 0.0
    dq = np.abs(np.sum(rot[1:] * rot[:-1], axis=2))
    ang = np.degrees(2 * np.arccos(np.clip(dq, 0, 1)))
    floor = P[:, FEET, 1].min()
    slide = []
    for t in range(1, T):
        for j in FEET:
            if P[t, j, 1] - floor < 0.03 and P[t - 1, j, 1] - floor < 0.03:
                slide.append(np.linalg.norm((P[t, j] - P[t - 1, j])[[0, 2]]) * 30)
    return {
        "キー": max(res.get("key_max_error_m") or [0]) * 100,
        "腰目印": max(res.get("root_key_error_m") or [0]) * 100,
        "向き": max(res.get("root_heading_error_deg") or [0]),
        "跳び": (step[i], i + 1 + job.first, jump),
        "関節": float(ang.max()),
        "足滑り": float(np.mean(slide)) if slide else 0.0,
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    seeds = [2, 7]
    for a in sys.argv[1:]:
        if a.startswith("--seeds"):
            seeds = [int(x) for x in a.split("=", 1)[1].split(",")]
    for sc in SCENES:
        if args and not any(a in sc["name"] for a in args):
            continue
        motion = vmd.read(sc["vmd"])
        for seed in seeds:
            job = pipeline.prepare(sc["pmx"], motion, sc["prompt"], seed=seed, **sc["kw"])
            t = time.perf_counter()
            res = pipeline.run_kimodo(job, WORK)
            m = measure(job, res)
            s, f, ratio = m["跳び"]
            print(f"{sc['name']:10s} seed {seed}: キー {m['キー']:4.1f}cm・腰目印 {m['腰目印']:4.1f}cm・向き {m['向き']:3.0f}°・"
                  f"跳び {s * 100:4.1f}cm/F（{f}F・前後の {ratio:3.1f} 倍）・関節 {m['関節']:4.1f}°/F・足滑り {m['足滑り']:.2f}m/s・"
                  f"{time.perf_counter() - t:.0f} 秒", flush=True)


if __name__ == "__main__":
    main()
