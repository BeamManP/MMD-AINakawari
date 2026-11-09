"""生成したキーの間引き（thin.py。11-09 マスター）を、作り物の MMD・Kimodo・MotionBricks で確かめる。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_thin_1109.py

各モード（範囲の作り直し・全部・センターに合わせて・続きを足す・MotionBricks の中割り）で、間引きなしと「ふつう」で同じ結果から作り、
1. キーの数が減るか
2. 生成した骨の全フレームの値が、骨ごとの許容差（移動 0.05・回転 0.5°）に収まるか
3. 手・頭・IK のボーンの位置（IK は解かない）のずれが、全身の許容差（0.06）に収まるか。足首は IK を解いた位置も測る
4. 生成していないキー（マスターのキー・範囲の端・範囲の外）が、値も曲線もそのまま残るか。範囲の外の動きが変わらないか
を見る。あわせて、元に戻すがバックアップ（間引く前の元）を読み込むか、同じ範囲の作り直しで前回の元のキーから作り直すかも見る。
Kimodo の動きは work\\kimodo\\result.json（前に本物で作った物）を使い回す。生成するたびに上書きされるので、
キーの数は回す時によって違う（確かめるのは「減るか」と「ずれが許容差に収まるか」）。モデルは Tda式初音ミク V4X、キーは work\\demo の VMD（30F おき）。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import json  # noqa: E402

import numpy as np  # noqa: E402

from mmd_ainakawari import paths, pipeline, runner, smooth_stop, thin, vmd  # noqa: E402
from mmd_ainakawari.mmd_skel import MMDSkeleton, curve_points, sample  # noqa: E402

PMX = r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\UserFile\Model\Tda式初音ミクV4X_Ver1.00\Tda式初音ミクV4X_Ver1.00.pmx"
DEMO = os.path.join(HERE, "work", "demo", "demo_keys_20261106_023634.vmd")
RESULT = os.path.join(HERE, "work", "kimodo", "result.json")

def main():
    # 書き戻しの計算は子プロセスに分けることがある（pipeline.build_motion）。Windows の子はこのファイルを読み直すので、
    # 中身は全部ここに入れる（守らずに回すと、子がテストをもう一度始めて止まった。11-09）
    for p in (PMX, DEMO, RESULT):
        if not os.path.exists(p):
            sys.exit(f"確かめに使う物がありません: {p}")
    TMP = tempfile.mkdtemp(prefix="ainakawari_thin_")
    runner.WORK_DIR = TMP   # 控え・結果・前回の記録は作業用のフォルダに（work の last_run.json を触らない）
    runner.LAST_RUN = os.path.join(TMP, "last_run.json")
    results = []


    def check(name, ok, detail=""):
        results.append(bool(ok))
        print(f"{'OK ' if ok else 'NG '} {name}" + (f" … {detail}" if detail else ""))


    # ---- 作り物の Kimodo・MotionBricks（本物の動きを長さに合わせて往復させる） --------------------------
    REAL = json.load(open(RESULT, encoding="utf-8"))
    RT_N, RJ = REAL["num_frames"], len(REAL["names"])
    R_ROOT = np.array(REAL["root"]).reshape(RT_N, 3)
    R_ROT = np.array(REAL["local_rot"]).reshape(RT_N, RJ, 4)


    def frames_of(n, offset=0):
        idx = [(offset + k) % (2 * RT_N - 2) for k in range(n)]
        idx = [i if i < RT_N else 2 * RT_N - 2 - i for i in idx]
        return R_ROOT[idx], R_ROT[idx]


    def fake_kimodo(job, work_dir, on_line=None, **_kw):
        n = job.request["num_frames"]
        root, rot = frames_of(n)
        return {"fps": 30.0, "num_frames": n, "names": REAL["names"], "root": root.reshape(-1).tolist(),
                "local_rot": rot.reshape(-1).tolist(), "key_max_error_m": [0.0], "seconds_generate": 0.0}


    def fake_mb_run(payload, work_dir, log=print):
        out = []
        for i, j in enumerate(payload["jobs"]):
            n = sum(t["frames"] for t in j["targets"]) + 1
            root, rot = frames_of(n, offset=37 * i)
            out.append({"num_frames": n, "names": REAL["names"], "root": root.reshape(-1).tolist(),
                        "local_rot": rot.reshape(-1).tolist()})
        return {"results": out, "seconds_generate": 0.0}


    pipeline.run_kimodo = fake_kimodo
    smooth_stop.available = lambda: True
    smooth_stop._run = fake_mb_run


    class FakeLink:
        """runner.generate・undo が使う MMDLink の口だけを持つ作り物。読み込んだファイルを覚え、次に読む中身にする。"""
        key = "check-thin"

        def __init__(self, motion):
            self.motion, self.loaded = motion, []

        def current_frame(self):
            return 0

        def state(self):
            return {"model_selected": True, "model": "Tda式初音ミクV4X"}

        def selected_model(self):
            return {"path": PMX, "name": "Tda式初音ミクV4X"}

        def check_model(self, model):
            pass

        def read_motion(self, path):
            vmd.write(path, self.motion)
            return vmd.read(path)

        def load_motion(self, path, frame=0, **kw):
            self.loaded.append(path)
            self.motion = vmd.read(path)

        def return_to(self, frame):
            return None


    def run(settings, motion, previous=None):
        logs = []
        link = FakeLink(motion)
        got = runner.generate(settings, log=logs.append, link=link, previous=previous)
        return got, vmd.read(got["output"]), logs, link


    # ---- 比べ方 ------------------------------------------------------------------------------------------
    skel = MMDSkeleton(PMX)
    rt = pipeline.Retargeter(skel, paths.soma_json())
    written = {vmd.vmd_name(n) for n in pipeline.body_bone_names(skel, rt)}
    by_ik = set()
    for n in rt.our_iks:
        ik = skel.bones[skel.i(n)]["ik"]
        by_ik |= {l["bone_index"] for l in ik["links"]} | {ik["target_index"]}
    WATCH = [n for n in dict.fromkeys(list(rt.mapped) + list(thin.WATCH_EXTRA) + list(rt.our_iks))
             if n in skel and skel.i(n) not in by_ik]
    FEET = [n for n in ("左足首", "右足首") if n in skel]


    def angle(a, b):
        a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
        return np.degrees(4 * np.arcsin(min(1.0, min(np.linalg.norm(a - b), np.linalg.norm(a + b)) / 2)))


    def compare(name, job, dense, thinned, lo, hi, ik_frames=12):
        """dense（間引きなし）と thinned（ふつう）を比べる。lo〜hi: 生成した範囲（MMD のフレーム）。job: 間引いた方の生成の Job。"""
        check(f"{name}: キーが減る", len(thinned.bones) < len(dense.bones), f"{len(dense.bones)} → {len(thinned.bones)}")
        td, tt = dense.tracks(), thinned.tracks()
        last = max(k.frame for k in dense.bones)
        worst_t = worst_r = 0.0
        outside = 0.0
        for n in written & set(td):
            for f in range(0, last + 2):
                (ta, qa), (tb, qb) = sample(td, n, f), sample(tt, n, f)
                dt, dr = np.abs(ta - tb).max(), angle(qa, qb)
                worst_t, worst_r = max(worst_t, dt), max(worst_r, dr)
                if not lo <= f <= hi:
                    outside = max(outside, dt, dr)
        check(f"{name}: 骨ごとのずれが許容差まで", worst_t <= thin.MOVE_TOLERANCE + 1e-6 and worst_r <= thin.ANGLE_TOLERANCE + 1e-3,
              f"移動 {worst_t:.4f}・回転 {worst_r:.3f}°")
        check(f"{name}: 範囲の外の動きは変わらない", outside < 1e-5, f"{outside:.2e}")
        if job.mmd_frames:   # 範囲の中でも、MMD の補間のまま残す間（中割りで作れない間）は変わらない
            gap = max(max(np.abs(sample(td, n, f)[0] - sample(tt, n, f)[0]).max(), angle(sample(td, n, f)[1], sample(tt, n, f)[1]))
                      for n in written & set(td) for f in job.mmd_frames)
            check(f"{name}: MMD の補間のまま残す間の動きは変わらない", gap < 1e-5,
                  f"{min(job.mmd_frames)}〜{max(job.mmd_frames)}F・{gap:.2e}")
        # 生成していないキー（マスターのキー・範囲の端に足したキー・範囲の外のキー）は、値も曲線もそのまま。
        # 書き戻す骨の、範囲の中で job.frames（キーのポーズを守るフレーム）でもMMD の補間のまま残す所でもないキーは、生成したキー
        # （センターに合わせて作る時は、範囲の中の元のキーも生成で上書きされる）
        protected = set(job.frames) | set(job.mmd_frames)
        thin_at = {(k.name, k.frame): k for k in thinned.bones}
        lost, curve = [], []
        for k in dense.bones:
            if vmd.vmd_name(k.name) in written and lo <= k.frame <= hi and k.frame not in protected:
                continue
            t = thin_at.get((k.name, k.frame))
            if t is None or np.abs(t.pos - k.pos).max() > 1e-6 or angle(t.rot, k.rot) > 1e-4:
                lost.append((k.name, k.frame))
            elif t.interp != k.interp and not (vmd.vmd_name(k.name) in written and lo < k.frame <= hi + 1
                                               and k.frame - 1 not in job.mmd_frames):
                curve.append((k.name, k.frame))   # 生成した区間の終わりのキーだけは、曲線を書き換えてよい
        check(f"{name}: 生成していないキーは残る", not lost, f"{lost[:5]}")
        check(f"{name}: 生成した区間の外のキーの曲線はそのまま", not curve, f"{curve[:5]}")
        # 全身の位置（IK は解かない）
        pd, pt = pipeline.tracks_of(skel, dense), pipeline.tracks_of(skel, thinned)
        idx = [skel.i(n) for n in WATCH]
        world, where = 0.0, ""
        for f in range(lo, hi + 1):
            a = pipeline.pose_at(skel, pd, f, solve_ik=False)[1][idx]
            b = pipeline.pose_at(skel, pt, f, solve_ik=False)[1][idx]
            d = np.linalg.norm(a - b, axis=1)
            if d.max() > world:
                world, where = float(d.max()), f"{WATCH[int(d.argmax())]} {f}F"
        check(f"{name}: 手・頭・IK のボーンのずれが全身の許容差まで", world <= thin.WORLD_TOLERANCE + 1e-6,
              f"{world:.4f}（{world * 8:.2f}cm・{where}）")
        # 足首は MMD と同じく IK を解いた位置も（数フレームだけ。参考に出し、4cm を超えたら止める）
        feet = 0.0
        for f in np.linspace(lo, hi, ik_frames).astype(int):
            a = pipeline.pose_at(skel, pd, int(f), skip_ik=rt.idle_iks)[1][[skel.i(n) for n in FEET]]
            b = pipeline.pose_at(skel, pt, int(f), skip_ik=rt.idle_iks)[1][[skel.i(n) for n in FEET]]
            feet = max(feet, float(np.linalg.norm(a - b, axis=1).max()))
        check(f"{name}: IK を解いた足首のずれ（参考）", feet <= 0.5, f"{feet:.4f}（{feet * 8:.2f}cm）")


    # ---- 0. 曲線そのものの当てはめ ------------------------------------------------------------------------
    curve = (40, 5, 90, 127)
    row = [curve[r] for r in range(4) for _ch in range(4)]
    interp = bytes(sum(([*row[k:], *([0] * k)] for k in range(4)), []))
    a = vmd.BoneKey("x", 0, np.zeros(3), np.array([0.0, 0.0, 0.0, 1.0]))
    b = vmd.BoneKey("x", 30, np.array([3.0, -1.0, 2.0]), np.array([0.0, 0.38268343, 0.0, 0.92387953]), interp)
    dense_keys = [vmd.BoneKey("x", f, *sample({"x": [a, b]}, "x", f)) for f in range(31)]
    got = thin.fit_segment(dense_keys, thin.MOVE_TOLERANCE, thin.ANGLE_TOLERANCE)
    check("0. 曲線どおりの毎フレームのキーは、両端 2 つにできる", got is not None,
          f"元の曲線 {curve}・当てた曲線（X）{tuple(curve_points(got)[0::4][:4]) if got else None}")
    bump = list(dense_keys)
    bump[15] = vmd.BoneKey("x", 15, bump[15].pos + np.array([0.0, 0.3, 0.0]), bump[15].rot)
    check("0. 途中で外れたキーがあると、まとめない", thin.fit_segment(bump, thin.MOVE_TOLERANCE, thin.ANGLE_TOLERANCE) is None)
    over = [vmd.BoneKey("x", f, np.array([np.sin(f / 30 * np.pi) * 2, 0, 0]), a.rot) for f in range(31)]
    check("0. 行って戻る動き（両端より外へ出る）は、まとめない", thin.fit_segment(over, thin.MOVE_TOLERANCE, thin.ANGLE_TOLERANCE) is None)

    demo = vmd.read(DEMO)
    P = "A person dances happily."
    modes = [
        ("1. 範囲の作り直し 30〜90F", dict(prompt=P, range_start=30, range_end=90, smooth_stop=False), (30, 90)),
        ("2. 全部（キーの間を埋める）", dict(prompt=P, smooth_stop=False), None),
        ("3. センターに合わせて 30〜90F", dict(prompt=P, range_start=30, range_end=90, use_keys=False, use_center=True,
                                         stop_at_last_key=False, smooth_stop=False), (30, 90)),
        ("4. 続きを足す（最後のキーの後ろに 60F）", dict(prompt=P, extend=60, smooth_stop=False), None),
        ("5. MotionBricks の中割り", dict(prompt="", engine="motionbricks"), None),
        # 90F のキーを抜いて 60〜120F を 60 フレーム空ける（MotionBricks は 57 フレームまで）→ その間は MMD の補間のまま
        ("5b. MotionBricks の中割り（作れない間あり）", dict(prompt="", engine="motionbricks"), None),
    ]
    gap_demo = vmd.Motion(model_name=demo.model_name, bones=[k for k in demo.bones if k.frame != 90], tail=demo.tail,
                          name_raw=demo.name_raw)
    kept_run = None
    for name, kw, rng in modes:
        src = gap_demo if name.startswith("5b.") else demo
        got_d, dense, _logs, _l = run(runner.Settings(thin=0, **kw), src)
        got_t, thinned, logs, _l = run(runner.Settings(thin=thin.DEFAULT_LEVEL, **kw), src)
        job = got_t["job"]
        lo, hi = (job.first, job.first + job.num_frames - 1)
        if rng:
            lo, hi = rng
        line = next((l for l in logs if "モデル全体のキー" in l), "")
        check(f"{name}: ログに間引いた数が出る", "→" in line, line.strip()[:80])
        if name.startswith("5b."):
            check(f"{name}: MMD の補間のまま残す間がある", bool(job.mmd_frames),
                  f"{min(job.mmd_frames)}〜{max(job.mmd_frames)}F" if job.mmd_frames else "無し")
        compare(name, job, dense, thinned, lo, hi)
        if name.startswith("1."):
            kept_run = (got_t, thinned)

    # ---- 6. 元に戻す: 間引く前の元（バックアップ）を読み込む --------------------------------------------
    got_t, thinned = kept_run
    link = FakeLink(thinned)
    runner.undo(got_t["backup"], log=lambda _l: None, link=link, model=PMX)
    back = link.motion
    same = {(k.name, k.frame) for k in back.bones} == {(k.name, k.frame) for k in demo.bones}
    check("6. 元に戻すと、生成の前のキーに戻る", link.loaded == [got_t["backup"]] and same, f"{len(back.bones)} 個（元 {len(demo.bones)} 個）")

    # ---- 7. 同じ範囲の作り直し: MMD の中身が前回の間引いた結果なら、前回の元のキーから作る ----------------
    s = runner.Settings(prompt=P, range_start=30, range_end=90, smooth_stop=False, thin=thin.DEFAULT_LEVEL)
    again, out2, logs, _l = run(s, thinned, previous=got_t)
    check("7. 作り直しで、前回の元のキーから作り直す", any("前回の元のキーから作り直します" in l for l in logs))
    check("7. 作り直した結果も、前回と同じ数まで間引く", len(out2.bones) == len(thinned.bones), f"{len(out2.bones)}・前回 {len(thinned.bones)}")

    # ---- 8. しない（0）なら何も変えない ------------------------------------------------------------------
    merged = vmd.read(got_t["output"])
    same_out, info = thin.thin_motion(merged, vmd.Motion(bones=merged.bones[:3]), skel, rt, 0)
    check("8. 「しない」では間引かない", same_out is merged and info is None)

    print(f"---\n{sum(results)}/{len(results)} 通った")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
