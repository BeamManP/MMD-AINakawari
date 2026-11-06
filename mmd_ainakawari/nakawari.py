"""キーとキーの間を MotionBricks だけで埋める（中割り。プロンプトは使わない）。

pipeline.prepare が出すキーの姿勢（Kimodo の形・最初のキーを原点と正面に揃えたもの）を目標にして、
キーごとに MotionBricks で 1 回ずつ作ってつなぐ。結果は Kimodo の結果と同じ形なので、書き戻しは pipeline.build_motion のまま。

- MotionBricks の 1 回は 17〜57 フレーム（文脈の最後から目標まで）。キーの間がそれより短い・長い所は作らず、MMD の補間のまま残す
  （job.mmd_frames に入れて書き戻さない）。作れる間が続く所は、前の結果の最後の 4 フレームを次の文脈にしてつなぐ
- 目標の姿勢 1 つ = そのキーで止まる。key_stop でなければ、次のキーへ 1 フレーム進んだ姿勢も渡して、その速さで通る
- 11-04 のテスト（VPD の立ちポーズ 10 個・30F おき）で、MotionBricks は手首をキーの差より大きく回した
  （左手首: キーどうしの差 20° の区間で合計 379°・1 フレームで最大 131°）。wrist_lerp なら手首だけキーの間を球面の補間でつなぐ
"""
import numpy as np

from . import paths, pipeline, smooth_stop
from . import quat as Q

WRISTS = ("LeftHand", "RightHand")


def _step_toward(a, b, t):
    """キーの姿勢 a から b へ t だけ進んだ姿勢（腰は直線・回転は球面の補間）。"""
    rot = [Q.slerp(x, y, t) for x, y in zip(np.reshape(a["local_rot"], (-1, 4)), np.reshape(b["local_rot"], (-1, 4)))]
    root = np.asarray(a["root"]) + (np.asarray(b["root"]) - np.asarray(a["root"])) * t
    return {"root": root.tolist(), "local_rot": [float(v) for q in rot for v in q]}


def _pose(key):
    return {"root": key["root"], "local_rot": key["local_rot"]}


def generate(job, work_dir, key_stop=False, wrist_lerp=False, log=print):
    if not smooth_stop.available():
        raise RuntimeError("MotionBricks が入っていません。詳細の窓のセットアップで MotionBricks を入れてください")
    keys = sorted(job.request["keys"], key=lambda k: k["frame"])
    if len(keys) < 2:
        raise ValueError("中割りには体のキーが 2 つ以上要ります")
    if job.root_frames or job.limb_frames:
        log("  中割りに使うのは体のキーです（全ての親だけ・手足の IK だけのキーは対象外）")
    poses = [_pose(k) for k in keys]
    frames = [k["frame"] for k in keys]
    gaps = [b - a for a, b in zip(frames, frames[1:])]
    ok = [smooth_stop.MIN_LEN <= g <= smooth_stop.MAX_LEN for g in gaps]
    # 作れる間が続く所ごとに 1 つの依頼にする（[始めのキーの番号, 終わりのキーの番号]）
    runs, i = [], 0
    while i < len(gaps):
        if ok[i]:
            j = i
            while j + 1 < len(gaps) and ok[j + 1]:
                j += 1
            runs.append((i, j + 1))
            i = j + 1
        else:
            log(f"  {frames[i] + job.first}〜{frames[i + 1] + job.first}F は {gaps[i]} フレーム"
                f"（MotionBricks は {smooth_stop.MIN_LEN}〜{smooth_stop.MAX_LEN}）なので、MMD の補間のままにします")
            i += 1
    if not runs:
        raise ValueError(f"キーの間が {smooth_stop.MIN_LEN}〜{smooth_stop.MAX_LEN} フレームの所がありません")
    jobs = []
    for s, e in runs:
        targets = []
        for k in range(s + 1, e + 1):
            target = [poses[k]]
            if not key_stop and k + 1 < len(keys):
                target.append(_step_toward(poses[k], poses[k + 1], 1 / gaps[k]))
            elif not key_stop and job.context_after and frames[k] + job.first == job.anchors[-1]:
                target.append(_pose(job.context_after[0]))   # 範囲の終わり: 外の動きの次のフレームへ通り抜ける
            targets.append({"poses": target, "frames": gaps[k - 1], "num_poses_to_use": len(target)})
        # 文脈は始めのキーの姿勢で止まっている形。範囲の始まりからの時は、範囲の手前の MMD の動き（外の勢いをつなぐ）
        context = [poses[s]] * 4
        if s == 0 and job.anchors and job.context_before:
            context = ([_pose(job.context_before[0])] * 4 + [_pose(p) for p in job.context_before] + [poses[0]])[-4:]
        jobs.append({"context": context, "targets": targets})
    res = smooth_stop._run({"skeleton": paths.soma_json(), "jobs": jobs}, work_dir, log=log)

    T = job.num_frames
    J = len(keys[0]["local_rot"]) // 4
    root = np.zeros((T, 3))
    rot = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (T, J, 1))
    covered = np.zeros(T, bool)
    names = None
    sunk = 0.0
    for (s, e), r in zip(runs, res["results"]):
        n = r["num_frames"]
        a = frames[s]
        root[a:a + n] = np.array(r["root"]).reshape(n, 3)
        rot[a:a + n] = np.array(r["local_rot"]).reshape(n, J, 4)
        covered[a:a + n] = True
        for k in range(s, e):   # キーとキーの間ごとに（途中のキーは床に着いた姿勢のまま動かさない）
            sunk = max(sunk, smooth_stop.keep_above_ground(root, rot, frames[k], frames[k + 1]))
        names = r["names"]
    if wrist_lerp:
        for jn in WRISTS:
            j = names.index(jn)
            for s, e in runs:
                for k in range(s, e):
                    a, b = frames[k], frames[k + 1]
                    qa, qb = np.reshape(poses[k]["local_rot"], (J, 4))[j], np.reshape(poses[k + 1]["local_rot"], (J, 4))[j]
                    for f in range(a, b + 1):
                        rot[f, j] = Q.slerp(qa, qb, (f - a) / (b - a))
    job.mmd_frames = {f + job.first for f in range(T) if not covered[f]}
    err = [float(np.linalg.norm(root[f] - np.asarray(p["root"]))) for f, p in zip(frames, poses) if covered[f]]
    done = sum(gaps[k] for s, e in runs for k in range(s, e))
    log(f"  MotionBricks で {len(runs)} 回・{done} フレームを作りました（{res['seconds_generate']:.1f} 秒・"
        f"{'キーごとに止まる' if key_stop else 'キーを通る'}・手首は{'補間' if wrist_lerp else ' MotionBricks のまま'}）"
        + (f"・床に沈んだ足を最大 {sunk * 100:.1f}cm 持ち上げ" if sunk else ""))
    return {"fps": 30.0, "num_frames": T, "names": names, "root": root.reshape(-1).tolist(),
            "local_rot": rot.reshape(-1).tolist(), "key_max_error_m": err, "seconds_generate": res["seconds_generate"]}
