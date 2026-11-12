"""11-12: 全ての親に載せた後の 2 回目の生成を、本物の MMD・MMM で通す（live_root_carry_1112.py の続き）。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\live_root_carry2_1112.py --host mmd|mmm

前もって: live_root_carry_1112.py と同じ（0F だけのモーション）。
1. 載せて生成（0〜149F）→ 読み直した全ての親のキーの補間曲線が、書いた物と同じか
2. 続きを足す（+100F・載せる）→ 全ての親が 149F の続きから進み、センターの横の移動が小さいか
3. 同じ設定で続きを作り直す → また載るか → 元に戻す → 1 の結果に戻るか
4. 長さを変えて作り直す（150 → 200F）→ 何が起きるかを記録する（前回載せた全ての親のキーが、マスターのキーと区別できない）
5. 元に戻す
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from mmd_ainakawari import pipeline, runner, vmd  # noqa: E402
from mmd_ainakawari.mmd_skel import MMDSkeleton, curve_points, sample  # noqa: E402

OUT = os.path.join(HERE, "work", "root_carry")
PROMPT = "A person walks forward and then turns left while walking in a big circle."
ROOT = pipeline.ROOT_BONE
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'OK ' if ok else 'NG '} {name}" + (f" … {detail}" if detail else ""), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", choices=("mmd", "mmm"), required=True)
    a = ap.parse_args()
    if a.host == "mmd":
        from mmd_ainakawari.mmd_link import MMDLink
        link = MMDLink()
    else:
        from mmd_ainakawari.mmm_link import MMMLink
        link = MMMLink()
    log = lambda line: print("  | " + line, flush=True)  # noqa: E731
    pmx = link.selected_model()["path"]
    skel = MMDSkeleton(pmx)

    def now(tag):
        m = link.read_motion(os.path.join(OUT, f"live2_{a.host}_{tag}.vmd"))
        return m, pipeline.tracks_of(skel, m)

    def center_max(t, frames):
        c = np.array([sample(t, "センター", f)[0] for f in frames])   # i18n: skip
        return float(np.hypot(c[:, 0], c[:, 2]).max())

    base = dict(prompt=PROMPT, use_keys=False, stop_at_last_key=False, seed=7, thin=2, root_move=True, root_turn=True)
    r1 = runner.generate(runner.Settings(length=150, **base), log, link=link, previous=None)
    _m, t1 = now("gen1")
    wrote = {k.frame: k for k in pipeline.tracks_of(skel, vmd.read(r1["output"])).get(ROOT, [])}
    got = {k.frame: k for k in t1.get(ROOT, [])}
    same = sorted(wrote) == sorted(got) and all(
        np.abs(np.array(curve_points(wrote[f].interp)) - np.array(curve_points(got[f].interp))).max() <= 1 for f in wrote)
    check("1: 全ての親のキーの補間曲線が書いた物と同じ", same,
          "; ".join(f"{f}F 書いた {curve_points(wrote[f].interp)[12:16]} 読んだ {curve_points(got[f].interp)[12:16]}" for f in sorted(wrote)
                    if f in got))
    # 書いた全ての親で計算した毎フレームの値と、ホストから読み直したキーで計算した値（ホストの曲線で補間した時に体がずれないか）
    wt = pipeline.tracks_of(skel, vmd.read(r1["output"]))
    dev = max(np.abs(sample(wt, ROOT, f)[0] - sample(t1, ROOT, f)[0]).max() for f in range(150))
    check("1: 読み直した全ての親の毎フレームの位置が書いた物と同じ", dev < 0.05, f"ずれ最大 {dev:.4f}")

    ext = dict(base, prompt="A person keeps walking forward.")
    r2 = runner.generate(runner.Settings(extend=100, **ext), log, link=link, previous=r1)
    _m, t2 = now("ext1")
    roots2 = [k.frame for k in t2.get(ROOT, [])]
    check("2: 続きを足す: 全ての親が 149F の後ろへ続く", r2.get("root_written") and max(roots2) > 149, f"{roots2}")
    p149, p_end = sample(t2, ROOT, 149)[0], sample(t2, ROOT, max(roots2))[0]
    check("2: 続きを足す: 全ての親が 149F から進む", float(np.hypot(*(p_end - p149)[[0, 2]])) > 5,
          f"149F {np.round(p149, 1)} → {max(roots2)}F {np.round(p_end, 1)}")
    check("2: 続きを足す: センターの横の移動が小さい", center_max(t2, range(149, 250)) < 5.0, f"{center_max(t2, range(149, 250)):.1f}")

    r3 = runner.generate(runner.Settings(extend=100, **ext), log, link=link, previous=r2)
    _m, t3 = now("ext2")
    roots3 = [k.frame for k in t3.get(ROOT, [])]
    check("3: 続きの作り直し: また載る", r3.get("root_written") and max(roots3) > 149, f"{roots3}")
    check("3: 続きの作り直し: センターの横の移動が小さい", center_max(t3, range(149, 250)) < 5.0, f"{center_max(t3, range(149, 250)):.1f}")
    runner.undo(r3["backup"], log, link=link, model=pmx)
    _m, t4 = now("ext_undo")
    check("3: 元に戻す: 1 の全ての親に戻る", [k.frame for k in t4.get(ROOT, [])] == sorted(got), f"{[k.frame for k in t4.get(ROOT, [])]}")

    print("=== 4: 長さを変えて作り直す（150 → 200F。何が起きるかの記録）")
    r5 = runner.generate(runner.Settings(length=200, **base), log, link=link, previous=r1)
    _m, t5 = now("len200")
    print(f"  記録: 全ての親に載ったか {r5.get('root_written')}・全ての親のキー {[k.frame for k in t5.get(ROOT, [])]}", flush=True)
    runner.undo(r5["backup"], log, link=link, model=pmx)
    # r1 の控えは、後の生成の記録で置き換わった時に片付けられている（runner._save_last_run）ので、0F だけのモーションを入れ直す
    link.load_motion(os.path.join(OUT, "start.vmd"), 0, model=pmx)
    _m, t6 = now("undo_all")
    check("5: 元に戻す: 全ての親は 0F だけ", [k.frame for k in t6.get(ROOT, [])] == [0], f"{[k.frame for k in t6.get(ROOT, [])]}")
    print("---")
    print("全部 OK" if all(results) else f"NG {results.count(False)} 件")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
