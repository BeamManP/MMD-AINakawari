"""11-12: 全ての親に載せる（pipeline.carry_root）を、本物の MMD・MMM で通す。窓は使わず、窓の「生成」と同じ runner.generate を呼ぶ。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\live_root_carry_1112.py --host mmd|mmm

前もって: MMD（または MMM）にモデルを 1 体読み込んで選び、0F だけにキーのあるモーションを入れておく
（work/root_carry/start.vmd。--write-start で作る）。
1. 生成（プロンプトだけで作る・移動と向きを載せる）→ MMD から読み直して、全ての親に 0F より後ろのキーがあり、センターの横の移動が小さいか
2. 同じ設定で作り直す → 前回の元のキーから作り直し、また全ての親に載るか（全ての親のキーを目印にしないか）
3. 元に戻す → 全ての親が 0F だけに戻るか
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from mmd_ainakawari import pipeline, runner, vmd  # noqa: E402
from mmd_ainakawari.mmd_skel import MMDSkeleton, sample  # noqa: E402

DEMO = os.path.join(HERE, "work", "demo", "demo_keys_20261106_023634.vmd")
OUT = os.path.join(HERE, "work", "root_carry")
START = os.path.join(OUT, "start.vmd")
PROMPT = "A person walks forward and then turns left while walking in a big circle."
ROOT = pipeline.ROOT_BONE
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'OK ' if ok else 'NG '} {name}" + (f" … {detail}" if detail else ""), flush=True)


def read_now(link, pmx, tag):
    path = os.path.join(OUT, f"live_{tag}.vmd")
    m = link.read_motion(path)
    t = pipeline.tracks_of(MMDSkeleton(pmx), m)
    roots = [k.frame for k in t.get(ROOT, [])]
    c = np.array([sample(t, "センター", f)[0] for f in range(150)])   # i18n: skip
    return roots, float(np.hypot(c[:, 0], c[:, 2]).max())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", choices=("mmd", "mmm"))
    ap.add_argument("--write-start", action="store_true")
    a = ap.parse_args()
    if a.write_start:
        os.makedirs(OUT, exist_ok=True)
        m = vmd.read(DEMO)
        vmd.write(START, vmd.Motion(model_name=m.model_name, bones=[k for k in m.bones if k.frame == 0], tail=m.tail,
                                    name_raw=m.name_raw))
        print(START)
        return 0
    if a.host == "mmd":
        from mmd_ainakawari.mmd_link import MMDLink
        link = MMDLink()
    else:
        from mmd_ainakawari.mmm_link import MMMLink
        link = MMMLink()
    log = lambda line: print("  | " + line, flush=True)  # noqa: E731
    s = runner.Settings(prompt=PROMPT, length=150, use_keys=False, stop_at_last_key=False, seed=7,
                        thin=2, root_move=True, root_turn=True)
    pmx = link.selected_model()["path"]
    roots0, c0 = read_now(link, pmx, "before")
    check("前: 全ての親は 0F だけ", roots0 in ([0], []), f"{roots0}")

    r1 = runner.generate(s, log, link=link, previous=None)
    roots1, c1 = read_now(link, pmx, "gen1")
    check("生成: 全ての親に載った（記録）", r1.get("root_written"), "")
    check("生成: MMD の全ての親に 0F より後ろのキー", any(f > 0 for f in roots1), f"{roots1}")
    check("生成: センターの横の移動が小さい", c1 < 5.0, f"センターの横 最大 {c1:.1f}")
    out1 = pipeline.tracks_of(MMDSkeleton(pmx), vmd.read(r1["output"]))
    check("生成: 書いた全ての親のキーが MMD に入った", [k.frame for k in out1.get(ROOT, [])] == roots1,
          f"書いた {[k.frame for k in out1.get(ROOT, [])]}")

    r2 = runner.generate(s, log, link=link, previous=r1)
    roots2, c2 = read_now(link, pmx, "gen2")
    check("作り直し: また全ての親に載った", r2.get("root_written") and any(f > 0 for f in roots2), f"{roots2}")
    check("作り直し: センターの横の移動が小さい", c2 < 5.0, f"センターの横 最大 {c2:.1f}")

    runner.undo(r2["backup"], log, link=link, model=pmx)
    roots3, c3 = read_now(link, pmx, "undo")
    check("元に戻す: 全ての親は 0F だけ", roots3 == roots0, f"{roots3}")
    print("---")
    print("全部 OK" if all(results) else f"NG {results.count(False)} 件")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
