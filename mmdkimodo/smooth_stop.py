"""最後のキーへの止まり方を MotionBricks（NVlabs/motionbricks）で作り直す。

Kimodo のキーは「その瞬間にこの姿勢を通る」だけなので、止める目印（pipeline.STOP_HOLD）を足しても、
走りなどはキーの 5 フレームほど手前で急に止まる（11-04 実験: 一番強い減速 26.6 m/s²）。
MotionBricks は「今の 4 フレーム → 目標の姿勢 1 つ」で、そこへ着いて止まる動きを作れるので、
Kimodo の結果のキーの手前 L フレームを、MotionBricks の「キーの姿勢へ歩み寄って止まる」動きに差し替える。

- L は 18〜57（MotionBricks の 1 回の長さ）の候補をまとめて作り、腰の速さ（3 フレームならし）の
  一番強い加速・減速が小さいものを選ぶ。長いほど Kimodo の動き（プロンプトの動き）を多く置き換えるので、短い方を少し優先する
  （11-04 実験: 走って 60F のキーに着く動きで 42F が選ばれ、一番強い減速 26.6 → 10.3 m/s²）
- MotionBricks は途中の目印を知らないので、L はその手前のキー・全ての親・手足の目印より前には伸ばさない
- キーの手前で腰がほとんど動いていない時は作り直さない（止まり方の問題が無く、プロンプトの動きを置き換えるだけになる）

MotionBricks は別の Python（3.12・TensorRT）なので、橋渡し（tools/mb_gen.py）を別プロセスで呼ぶ。
"""
import json
import os

import numpy as np

from . import pipeline, resident

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MB_PYTHON = r"F:\motionbricks\.venv\Scripts\python.exe"
MB_DIR = r"F:\motionbricks"
MB_SCRIPT = os.path.join(ROOT_DIR, "tools", "mb_gen.py")
MB_PORT = 9552   # 常駐の MotionBricks（tools/mb_gen.py --serve）
MIN_LEN, MAX_LEN = 17, 57    # MotionBricks の 1 回で作れる、文脈の最後から目標までのフレーム数
LEN_STEP = 3
LEN_COST = 0.05              # 長さ 1 フレームあたりの減点（m/s² 相当）。57F と 42F で 0.75 の差
MIN_SPEED = 1.0              # キーの 30〜10 フレーム手前の腰の平均の速さ（m/s）がこれ未満なら作り直さない


def available():
    return os.path.exists(MB_PYTHON) and os.path.exists(MB_SCRIPT)


def _speeds(roots, fps):
    """腰の地面での速さ（m/s）を 3 フレームでならしたもの。"""
    v = np.r_[0.0, np.linalg.norm(np.diff(roots[:, [0, 2]], axis=0), axis=1) * fps]
    return np.convolve(v, np.ones(3) / 3, mode="same")


def _peak_change(v, start, end, fps):
    """start〜end の速さの変化の一番強いところ（m/s²）。(加速, 減速)"""
    acc = np.diff(v[start:end + 1]) * fps
    return float(max(acc.max(), 0.0)), float(max(-acc.min(), 0.0))


def apply(job, result, work_dir, log=print):
    """result（Kimodo の結果）の止まる所を作り直したものを返す。作り直さない時は result をそのまま返す。"""
    if not job.stop_frames:
        return result
    if not available():
        raise RuntimeError(f"MotionBricks が見つかりません（{MB_PYTHON}）。「なめらかに止まる」を外すか、MotionBricks を入れてください")
    stop = job.stop_frames[0] - 1
    kf = stop - job.first
    key = next(k for k in job.request["keys"] if k["frame"] == kf)
    T = result["num_frames"]
    J = len(result["names"])
    fps = float(result.get("fps", 30.0))
    roots = np.array(result["root"]).reshape(T, 3)
    rots = np.array(result["local_rot"]).reshape(T, J, 4)
    v = _speeds(roots, fps)
    approach = float(v[max(0, kf - 30):max(1, kf - 10)].mean())
    if approach < MIN_SPEED:
        log(f"  キーの手前の腰の速さ {approach:.2f} m/s（{MIN_SPEED} 未満）なので、止まり方は Kimodo のままにします")
        return result
    # 手前の目印（キー・全ての親・手足）より前には伸ばさない。文脈に 4 フレーム要る
    earlier = [f - job.first for f in job.frames + job.root_frames + job.limb_frames if f < stop]
    limit = min(kf - max(earlier, default=0), kf - 3, MAX_LEN)
    if limit < MIN_LEN:
        log(f"  キーの手前の目印まで {limit} フレームしかない（MotionBricks は {MIN_LEN} フレームから）ので、止まり方は Kimodo のままにします")
        return result
    lengths = sorted(set(range(18, limit + 1, LEN_STEP)) | {limit})
    key_pose = {"root": key["root"], "local_rot": key["local_rot"]}
    jobs = [{"context": [{"root": roots[t].tolist(), "local_rot": rots[t].reshape(-1).tolist()} for t in range(kf - L - 3, kf - L + 1)],
             "targets": [{"poses": [key_pose], "frames": L, "num_poses_to_use": 1}]} for L in lengths]
    res = _run({"skeleton": pipeline.SOMA_JSON, "jobs": jobs}, work_dir, log=log)

    best = None
    for L, r in zip(lengths, res["results"]):
        n = r["num_frames"]
        a = kf - L
        mb_roots = np.array(r["root"]).reshape(n, 3)
        mb_rots = np.array(r["local_rot"]).reshape(n, J, 4)
        sr = np.concatenate([roots[:a], mb_roots, roots[kf + 1:]])
        sv = _speeds(sr, fps)
        acc, dec = _peak_change(sv, a - 3, kf, fps)
        score = max(acc, dec) + LEN_COST * L
        if best is None or score < best[0]:
            best = (score, L, acc, dec, sr, np.concatenate([rots[:a], mb_rots, rots[kf + 1:]]))
    _, L, acc, dec, sr, so = best
    a = kf - L
    base_acc, base_dec = _peak_change(v, a - 3, kf, fps)
    log(f"  止まり方を MotionBricks で作り直しました: {a + job.first}〜{stop}F（{L} フレーム・候補 {len(lengths)} 通りから）・"
        f"一番強い減速 {base_dec:.1f} → {dec:.1f} m/s²・加速 {base_acc:.1f} → {acc:.1f} m/s²（{res['seconds_generate']:.1f} 秒）")
    out = dict(result)
    out["root"] = sr.reshape(-1).tolist()
    out["local_rot"] = so.reshape(-1).tolist()
    out["smooth_stop"] = {"start": a + job.first, "stop": stop, "frames": L, "decel": dec, "decel_before": base_dec}
    return out


def _run(request, work_dir, log=print):
    """常駐の MotionBricks に頼む（いなければ立ち上げる。エンジンの読み込みが 1 回で済む）。依頼と結果は work_dir に残す。"""
    os.makedirs(work_dir, exist_ok=True)
    json.dump(request, open(os.path.join(work_dir, "request.json"), "w", encoding="utf-8"))
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    result, _line = resident.call(resident.Server("MotionBricks", MB_PORT, MB_PYTHON, MB_SCRIPT, MB_DIR, env), request, log=log)
    json.dump(result, open(os.path.join(work_dir, "result.json"), "w", encoding="utf-8"))
    return result
