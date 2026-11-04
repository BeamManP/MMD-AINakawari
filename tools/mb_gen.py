"""MotionBricks の橋渡し（MotionBricks の Python で動かす）。依頼の JSON → 結果の JSON。

    F:\\motionbricks\\.venv\\Scripts\\python.exe tools\\mb_gen.py 依頼.json 結果.json     1 回だけ
    F:\\motionbricks\\.venv\\Scripts\\python.exe tools\\mb_gen.py --serve 9552         常駐（mmdkimodo/resident.py から頼む）

姿勢は Kimodo と同じ形（SOMA 30 関節・Y が上・+Z が前・メートル。回転は基準の T ポーズで 0 の、親から見た四元数 x,y,z,w）。
MotionBricks の骨格（77 関節の USD）は基準の回転が 0 でないので、世界の向きを介して付け替える:
    MotionBricks の世界の向き = Kimodo の世界の回転 × MotionBricks の基準の世界の向き
（11-04 確認: 基準の姿勢は両方 T ポーズで向きも同じ。関節の位置の差は腰から見て平均 0.8cm・最大 3.9cm）

依頼:
    {"skeleton": "somaskel30.json の場所",
     "context": [4 つの姿勢],                       # 姿勢 = {"root": [x, y, z], "local_rot": [30 × 4]}
     "targets": [{"poses": [1〜4 つの姿勢], "frames": 着くまでのフレーム数, "num_poses_to_use": 1〜4}, …]}
    目標の姿勢 1 つ = そこで止まる。2〜4 つ = その速さ・勢いで通る（30Hz で並べる）。
    frames は文脈の最後の姿勢から目標の姿勢までの間隔（両端を含めて frames + 1 フレーム）。17〜57。
結果（Kimodo の結果と同じ形）:
    {"fps": 30, "num_frames": T, "names": [...], "root": [T × 3], "local_rot": [T × 30 × 4],
     "foot_contacts": [T × 4], "segments": [{"frames": …, "tokens": …, "generated": …}], "seconds_generate": …}
    0 フレーム目は文脈の最後の姿勢。目標が複数なら、前の結果の最後の 4 フレームを次の文脈にしてつなぐ。
まとめて頼む時（読み込みは 1 回で済む）:
    {"skeleton": …, "jobs": [{"context": …, "targets": …}, …]}  →  {"results": [上の結果, …], "seconds_generate": …}
"""
import json
import os
import sys
import threading
import time
import traceback

import numpy as np
import warp as wp
from scipy.spatial.transform import Rotation as R
from scipy.spatial.transform import Slerp

from motionbricks.io.usd import load_skeleton_from_usd
from motionbricks.io.utils import SOMA_SKELETON_PRIM_PATH, get_asset_file
from motionbricks.model.config import MotionBricksInferenceConfig
from motionbricks.model.soma.contract import SOMA_N1_FP32_ONNX_PATH
from motionbricks.model.soma.engine import MotionBricksSOMAEngine

MIN_TOKENS, MAX_TOKENS = 6, 16   # 1 回で 4k-6 フレーム（両端込み）＝ 18〜58
AUTHKEY = b"MMDKimodo.resident.v1"   # mmdkimodo/resident.py と同じ
IDLE_SECONDS = 30 * 60               # 常駐で、これだけ頼まれなければ終わる


class Rig:
    """Kimodo の 30 関節 ⇔ MotionBricks の 77 関節の付け替え。"""

    def __init__(self, soma_json):
        soma = json.load(open(soma_json, encoding="utf-8"))
        self.names = soma["names"]
        self.parents = soma["parents"]
        self.skeleton = load_skeleton_from_usd(get_asset_file("human", "soma_base_skel_minimal_no_root.usd"), SOMA_SKELETON_PRIM_PATH)
        self.mb_names = list(self.skeleton.joint_names)
        self.mb_parents = [int(p) for p in self.skeleton.parent_indices.numpy()]
        self.ref = self.skeleton.reference_local_transforms.numpy()   # [77, 7] 位置 + 四元数 x,y,z,w
        self.mb_index = {n: i for i, n in enumerate(self.mb_names)}
        self.k_to_mb = [self.mb_index[n] for n in self.names]
        self.rest_global = [None] * len(self.mb_names)   # MotionBricks の基準の世界の向き
        for j, p in enumerate(self.mb_parents):
            r = R.from_quat(self.ref[j, 3:7])
            self.rest_global[j] = r if p < 0 else self.rest_global[p] * r

    def to_mb(self, pose):
        """Kimodo の形の姿勢 → MotionBricks の親から見た変換 [77, 7]。"""
        local = R.from_quat(np.asarray(pose["local_rot"], float).reshape(-1, 4))
        k_global = [None] * len(self.names)
        for i, p in enumerate(self.parents):
            k_global[i] = local[i] if p < 0 else k_global[p] * local[i]
        model = {self.k_to_mb[i]: k_global[i] for i in range(len(self.names))}
        out = self.ref.copy()
        world = [None] * len(self.mb_names)
        for j, p in enumerate(self.mb_parents):
            if j in model:
                world[j] = model[j] * self.rest_global[j]
            else:   # 指・HeadEnd など、モデルが扱わない関節は基準のまま親に付いていく
                world[j] = (world[p] if p >= 0 else R.identity()) * R.from_quat(self.ref[j, 3:7])
            local_j = world[j] if p < 0 else world[p].inv() * world[j]
            out[j, 3:7] = local_j.as_quat()
        out[0, :3] = pose["root"]
        return out

    def from_mb(self, frames):
        """MotionBricks の親から見た変換 [T, 77, 7] → Kimodo の形（腰の位置 [T, 3]・回転 [T, 30, 4]）。"""
        T = len(frames)
        roots = frames[:, 0, :3].copy()
        rots = np.zeros((T, len(self.names), 4))
        for t in range(T):
            world = [None] * len(self.mb_names)
            for j, p in enumerate(self.mb_parents):
                r = R.from_quat(frames[t, j, 3:7])
                world[j] = r if p < 0 else world[p] * r
            k_global = [world[self.k_to_mb[i]] * self.rest_global[self.k_to_mb[i]].inv() for i in range(len(self.names))]
            for i, p in enumerate(self.parents):
                rots[t, i] = (k_global[i] if p < 0 else k_global[p].inv() * k_global[i]).as_quat()
        return roots, rots


def resample(roots, rots, contacts, count):
    """生成したフレームを count フレーム（両端込み）に、時間を均等に伸び縮みさせる。"""
    n = len(roots)
    if n == count:
        return roots, rots, contacts
    src = np.arange(n)
    dst = np.linspace(0, n - 1, count)
    out_roots = np.stack([np.interp(dst, src, roots[:, a]) for a in range(3)], axis=1)
    out_contacts = np.stack([np.interp(dst, src, contacts[:, a]) for a in range(contacts.shape[1])], axis=1)
    out_rots = np.zeros((count, rots.shape[1], 4))
    for j in range(rots.shape[1]):
        out_rots[:, j] = Slerp(src, R.from_quat(rots[:, j]))(dst).as_quat()
    return out_roots, out_rots, out_contacts


def generate(engine, rig, job):
    """1 つの依頼（文脈と目標の並び）→ Kimodo の形の結果。"""
    context = [rig.to_mb(p) for p in job["context"]]
    if len(context) != 4:
        raise ValueError("context は 4 つの姿勢")
    all_roots, all_rots, all_contacts, segments = [], [], [], []
    ctx = engine.create_input(rig.skeleton)
    tgt = engine.create_input(rig.skeleton)
    out = engine.create_output(rig.skeleton)
    for target in job["targets"]:
        count = int(target["frames"]) + 1
        tokens = min(MAX_TOKENS, max(MIN_TOKENS, round((count + 6) / 4)))
        if not 4 * MIN_TOKENS - 6 <= count <= 4 * MAX_TOKENS - 6:
            raise ValueError(f"目標までの間隔 {target['frames']} フレームは MotionBricks の 1 回（17〜57）に入りません")
        poses = [rig.to_mb(p) for p in target["poses"]][: int(target.get("num_poses_to_use", len(target["poses"])))]
        ctx.update_from_poses(wp.array(np.stack(context), dtype=wp.transform), stream=engine.stream)
        tgt.update_from_poses(wp.array(np.stack(poses), dtype=wp.transform), stream=engine.stream)
        engine.generate_animation(ctx, tgt, out, config=MotionBricksInferenceConfig(allowed_token_counts=(tokens,)))
        engine.synchronize()
        n = out.num_frames
        frames = out.poses[:n].numpy().reshape(n, -1, 7)
        contacts = out.foot_contacts[:n].numpy()
        roots, rots = rig.from_mb(frames)
        roots, rots, contacts = resample(roots, rots, contacts, count)
        start = 0 if not all_roots else 1   # つなぎ目の 1 フレームは前の区間の最後と同じ
        all_roots.append(roots[start:])
        all_rots.append(rots[start:])
        all_contacts.append(contacts[start:])
        segments.append({"frames": int(target["frames"]), "tokens": tokens, "generated": int(n)})
        context = [rig.to_mb({"root": roots[k], "local_rot": rots[k].reshape(-1)}) for k in range(count - 4, count)]
    roots = np.concatenate(all_roots)
    rots = np.concatenate(all_rots)
    contacts = np.concatenate(all_contacts)
    return {"fps": 30.0, "num_frames": int(len(roots)), "names": rig.names,
            "root": roots.reshape(-1).tolist(), "local_rot": rots.reshape(-1).tolist(),
            "foot_contacts": contacts.reshape(-1).tolist(), "segments": segments}


def run(engine, rigs, req):
    """依頼 → (結果, 1 行のまとめ)。rigs は骨格のファイルごとの Rig の控え。"""
    rig = rigs.get(req["skeleton"]) or rigs.setdefault(req["skeleton"], Rig(req["skeleton"]))
    jobs = req["jobs"] if "jobs" in req else [req]
    t0 = time.time()
    results = [generate(engine, rig, job) for job in jobs]
    seconds = time.time() - t0
    result = {"results": results, "seconds_generate": seconds} if "jobs" in req else dict(results[0], seconds_generate=seconds)
    return result, f"ok jobs={len(results)} frames={[r['num_frames'] for r in results]} seconds={seconds:.2f}"


def serve(port):
    """エンジンを開いたまま、127.0.0.1:port で依頼を待つ。1 つずつ順に作る。IDLE_SECONDS 頼まれなければ終わる。"""
    from multiprocessing.connection import Listener

    listener = Listener(("127.0.0.1", port), authkey=AUTHKEY)   # 口がふさがっていれば（もう常駐がいれば）ここで落ちる
    wp.init()
    wp.set_device("cuda:0")
    rigs = {}
    last = [time.time()]

    def watch():
        while True:
            time.sleep(30)
            if time.time() - last[0] > IDLE_SECONDS:
                print("idle exit", flush=True)
                os._exit(0)
    threading.Thread(target=watch, daemon=True).start()
    t0 = time.time()
    with MotionBricksSOMAEngine(SOMA_N1_FP32_ONNX_PATH) as engine, wp.ScopedStream(engine.stream):
        print(f"ready port={port} load={time.time() - t0:.1f}s", flush=True)
        born = os.path.getmtime(__file__)   # このファイルが書き換わったら、古いコードのまま作らずに終わる（resident.py が立ち上げ直す）
        while True:
            conn = listener.accept()
            last[0] = time.time() + 24 * 3600   # 作っている間は終わらない
            try:
                req = conn.recv()
                if os.path.getmtime(__file__) != born:
                    conn.send({"ok": False, "stale": True})
                    conn.close()
                    print("stale exit", flush=True)
                    os._exit(0)
                result, line = run(engine, rigs, req)
                conn.send({"ok": True, "result": result, "line": line})
                print(line, flush=True)
            except Exception:
                text = traceback.format_exc()
                print(text, flush=True)
                try:
                    conn.send({"ok": False, "error": text})
                except OSError:
                    pass
            finally:
                conn.close()
                last[0] = time.time()


def main():
    if sys.argv[1] == "--serve":
        serve(int(sys.argv[2]))
        return
    req = json.load(open(sys.argv[1], encoding="utf-8"))
    wp.init()
    wp.set_device("cuda:0")
    with MotionBricksSOMAEngine(SOMA_N1_FP32_ONNX_PATH) as engine, wp.ScopedStream(engine.stream):
        result, line = run(engine, {}, req)
    json.dump(result, open(sys.argv[2], "w", encoding="utf-8"))
    print(line)


if __name__ == "__main__":
    main()
