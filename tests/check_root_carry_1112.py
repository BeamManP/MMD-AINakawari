"""11-12: 歩いた分の移動・向きを全ての親に載せる（pipeline.carry_root）を確かめる。MMD は使わない。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_root_carry_1112.py

Kimodo で「歩いて曲がる」を 1 回作り（work/root_carry/ に残し、2 回目からはそれを使う）、
載せない・移動だけ・向きだけ・両方の 4 通りで書き戻して比べる:
1. 体の見た目（全身の骨の世界の位置。IK も解く）が、載せない時と同じか（間引きなし・ふつう の両方）
2. 両方の時、センターの横の移動が小さくなり、全ての親が腰の通り道について行くか
3. 全ての親の最後の向きが、腰の向きと合うか
4. 全ての親のキーが間引かれているか
5. 途中に体のキーがある時・全ての親のキーがある時は載せないか（理由が出るか）
"""
import copy
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from mmd_ainakawari import paths, pipeline, thin, vmd  # noqa: E402
from mmd_ainakawari import quat as Q  # noqa: E402

PMX = r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\UserFile\Model\Tda式初音ミクV4X_Ver1.00\Tda式初音ミクV4X_Ver1.00.pmx"
DEMO = os.path.join(HERE, "work", "demo", "demo_keys_20261106_023634.vmd")
OUT = os.path.join(HERE, "work", "root_carry")
PROMPT = "A person walks forward and then turns left while walking in a big circle."
LENGTH = 150
ROOT = pipeline.ROOT_BONE
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'OK ' if ok else 'NG '} {name}" + (f" … {detail}" if detail else ""))


def start_only(motion):
    """0F のキーだけ残す（始まりの姿勢だけが決まっている形）。"""
    return vmd.Motion(model_name=motion.model_name, bones=[k for k in motion.bones if k.frame == 0],
                      tail=motion.tail, name_raw=motion.name_raw)


def build(job, result, original, move, turn, level):
    job = copy.deepcopy(job)
    added = None
    if move or turn:
        added = pipeline.carry_root(job, result, move=move, turn=turn)
    gen = pipeline.build_motion(job, result, workers=1)
    merged = pipeline.merge(original, gen, job)
    if added is not None:
        pipeline.splice_root(merged, added)
    if level:
        skel = pipeline.MMDSkeleton(PMX)
        merged, _info = thin.thin_motion(merged, gen, skel, pipeline.Retargeter(skel, paths.soma_json()), level)
    return merged, added


def world(motion, frames):
    skel = pipeline.MMDSkeleton(PMX)
    rt = pipeline.Retargeter(skel, paths.soma_json())
    tracks = pipeline.tracks_of(skel, motion)
    watch = [skel.i(n) for n in rt.mapped if n in skel]
    out = []
    for f in frames:
        _G, P = pipeline.pose_at(skel, tracks, f, solve_ik=True, skip_ik=set(rt.idle_iks))
        out.append(np.asarray(P)[watch])
    return np.array(out)


def main():
    for p in (PMX, DEMO):
        if not os.path.exists(p):
            sys.exit(f"確かめに使う物がありません: {p}")
    original = start_only(vmd.read(DEMO))
    job = pipeline.prepare(PMX, original, PROMPT, length=LENGTH, use_keys=False, stop_at_last_key=False)
    check("始まりの姿勢だけなら載せられる", job.root_blocker is None, f"{job.root_blocker}")
    os.makedirs(OUT, exist_ok=True)
    cached = os.path.join(OUT, "result.json")
    if os.path.exists(cached):
        result = json.load(open(cached, encoding="utf-8"))
        print(f"作った結果を使います: {cached}")
    else:
        print("Kimodo で作ります…")
        result = pipeline.run_kimodo(job, OUT, on_line=lambda l: print("  " + l))
    frames = list(range(job.first, job.first + job.num_frames))

    base, _ = build(job, result, original, False, False, 0)
    ref = world(base, frames)
    variants = {}
    for name, move, turn in (("移動だけ", True, False), ("向きだけ", False, True), ("両方", True, True)):
        m, added = build(job, result, original, move, turn, 0)
        variants[name] = (m, added)
        d = np.linalg.norm(world(m, frames) - ref, axis=2).max()
        check(f"{name}: 体の見た目は載せない時と同じ（間引きなし）", d < 0.02, f"ずれ最大 {d:.4f}（MMD の単位）・全ての親のキー {len(added)} 個")

    # 間引き（ふつう）でも、載せない時の間引きと同じくらいに収まるか
    base_t, _ = build(job, result, original, False, False, thin.DEFAULT_LEVEL)
    both_t, _ = build(job, result, original, True, True, thin.DEFAULT_LEVEL)
    d0 = np.linalg.norm(world(base_t, frames) - ref, axis=2).max()
    d1 = np.linalg.norm(world(both_t, frames) - ref, axis=2).max()
    n0 = len(base_t.bones)
    n1 = len(both_t.bones)
    check("両方・間引きふつう: 見た目のずれが載せない時の間引きと同じくらい", d1 < max(0.2, d0 * 1.5),
          f"載せない {d0:.3f}・両方 {d1:.3f}（MMD の単位）・キー {n0} → {n1} 個")

    # センターと全ての親の動き
    skel = pipeline.MMDSkeleton(PMX)
    m, added = variants["両方"]
    tr = pipeline.tracks_of(skel, m)
    tb = pipeline.tracks_of(skel, base)
    last = frames[-1]
    from mmd_ainakawari.mmd_skel import sample
    c_base = sample(tb, "センター", last)[0]   # i18n: skip
    c_both = sample(tr, "センター", last)[0]   # i18n: skip
    r_pos, r_rot = sample(tr, ROOT, last)
    xz = lambda v: float(np.hypot(v[0], v[2]))  # noqa: E731
    check("両方: 全ての親が歩いた分ついて行く", xz(r_pos) > 0.7 * xz(c_base),
          f"載せない時のセンターの横の移動 {xz(c_base):.1f}・全ての親 {xz(r_pos):.1f}")
    check("両方: センターの横の移動が小さくなる", xz(c_both) < 0.25 * xz(c_base) + 1.0,
          f"センター {xz(c_base):.1f} → {xz(c_both):.1f}")
    # 最後の向き: 全ての親の Y 回転と、載せない時の下半身の世界の向きの変化
    def yaw(q):
        f = Q.rotate(q, np.array([0.0, 0.0, 1.0]))
        return float(np.degrees(np.arctan2(f[0], f[2])))
    G_first = pipeline.pose_at(skel, tb, frames[0], solve_ik=False)[0]
    G_last = pipeline.pose_at(skel, tb, last, solve_ik=False)[0]
    lo = skel.i("下半身")   # i18n: skip
    body_turn = (yaw(G_last[lo]) - yaw(G_first[lo]) + 180) % 360 - 180
    root_turn = (yaw(r_rot) + 180) % 360 - 180
    check("両方: 全ての親の向きが腰の向きの変化に合う", abs((root_turn - body_turn + 180) % 360 - 180) < 25,
          f"下半身 {body_turn:.0f}°・全ての親 {root_turn:.0f}°")
    check("全ての親のキーが間引かれている", len(added) < job.num_frames / 3, f"{len(added)} 個（{job.num_frames} フレーム）")
    vmd.write(os.path.join(OUT, "both.vmd"), m)
    vmd.write(os.path.join(OUT, "off.vmd"), base)

    # 載せない時（理由ごとに 1 つずつ。デモの VMD は全ての親にも 30F ごとにキーがあるので、体のキーの判定は全ての親のキーを外して見る）
    demo = vmd.read(DEMO)
    no_root = vmd.Motion(model_name=demo.model_name, bones=[k for k in demo.bones if k.name != ROOT or k.frame == 0],
                         tail=demo.tail, name_raw=demo.name_raw)
    fill = pipeline.prepare(PMX, no_root, PROMPT)
    check("途中に体のキーがあると載せない", fill.root_blocker and "体の姿勢" in fill.root_blocker, f"{fill.root_blocker}")
    rng = pipeline.prepare(PMX, no_root, PROMPT, frame_range=(0, 60))
    check("範囲の終わりが後ろの動きに続く時は載せない", rng.root_blocker and "60F" in rng.root_blocker and "体の姿勢" in rng.root_blocker,
          f"{rng.root_blocker}")
    open_end = vmd.Motion(model_name=no_root.model_name, bones=[k for k in no_root.bones if k.frame <= 30],
                          tail=no_root.tail, name_raw=no_root.name_raw)
    j3 = pipeline.prepare(PMX, open_end, PROMPT, frame_range=(30, 90))
    check("範囲の後ろにキーが無ければ載せられる", j3.root_blocker is None and j3.root_start == 30, f"{j3.root_blocker}・始まり {j3.root_start}F")
    later = vmd.Motion(model_name=original.model_name,
                       bones=original.bones + [vmd.BoneKey("センター", 200, np.zeros(3), Q.IDENTITY.copy())],   # i18n: skip
                       tail=original.tail, name_raw=original.name_raw)
    j4 = pipeline.prepare(PMX, later, PROMPT, length=LENGTH, use_keys=False, stop_at_last_key=False)
    check("作る所より後ろに体のキーがあると載せない", j4.root_blocker and "200F" in j4.root_blocker, f"{j4.root_blocker}")
    with_root = vmd.Motion(model_name=original.model_name,
                           bones=original.bones + [vmd.BoneKey(ROOT, 60, np.array([0.0, 0.0, -10.0]), Q.IDENTITY.copy())],
                           tail=original.tail, name_raw=original.name_raw)
    j2 = pipeline.prepare(PMX, with_root, PROMPT, length=LENGTH, use_keys=False, stop_at_last_key=False)
    check("全ての親のキーがあると載せない", j2.root_blocker is not None, f"{j2.root_blocker}")
    print("---")
    print("全部 OK" if all(results) else f"NG {results.count(False)} 件")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
