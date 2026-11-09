"""足が床に埋まったキーを知らせる（11-08 マスターと決めた案 B）を、作り物で確かめる。Kimodo は呼ばない（prepare まで）。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_sunk_key_1108.py

床は「一番低いキーの足」で決めるので、1 つだけ足ＩＫが床に埋まったキーがあると、間のフレームが全部沈む
（11-08、200F の左足ＩＫ Y -1.75 で、0〜180F の腰が 15cm ほど沈んだ）。決め方は変えず、job.sunk_keys で知らせる。
デモのキー（30F おき）の 120F だけ左足ＩＫを下げて、そのキーだけが出るか・ふつうのキーでは出ないかを見る。
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from mmd_ainakawari import pipeline, vmd  # noqa: E402

PMX = r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\UserFile\Model\Tda式初音ミクV4X_Ver1.00\Tda式初音ミクV4X_Ver1.00.pmx"
DEMO = os.path.join(HERE, "work", "demo", "demo_keys_20261106_023634.vmd")
for p in (PMX, DEMO):
    if not os.path.exists(p):
        sys.exit(f"確かめに使う物がありません: {p}")
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'OK ' if ok else 'NG '} {name}" + (f" … {detail}" if detail else ""))


P = "A person dances."
plain = pipeline.prepare(PMX, vmd.read(DEMO), P)
check("ふつうのキーでは知らせない", plain.sunk_keys == [], f"{plain.sunk_keys}")

# 足ＩＫだけ下げると脚が伸び切って 5cm ほどしか下がらないので、11-08 のキーと同じくセンターも一緒に下げる（左足が 14cm 床に埋まる）
sunk = vmd.read(DEMO)
for name in ("センター", "左足ＩＫ"):
    hit = [k for k in sunk.bones if k.name == name and k.frame == 120]
    if not hit:
        sys.exit(f"デモのキーに 120F の{name}がありません")
    hit[0].pos = hit[0].pos + [0.0, -1.75, 0.0]
job = pipeline.prepare(PMX, sunk, P)
frames = [f for f, _ in job.sunk_keys]
check("埋めたキー（120F）だけを知らせる", frames == [120], f"{[(f, round(d * 100, 1)) for f, d in job.sunk_keys]}")
check("低さはほかのキーとの差（10cm 以上）", job.sunk_keys and job.sunk_keys[0][1] >= 0.10)
check("床の決め方は変えない（一番低い足が床）", job.ground_lift > plain.ground_lift + 0.10,
      f"{plain.ground_lift * 100:.1f} → {job.ground_lift * 100:.1f}cm")

# 範囲を作り直す時: 範囲の外の文脈のフレームで中央値が引っ張られないか（11-08、0〜200F で 15cm が 7cm と出た）
inside = pipeline.prepare(PMX, sunk, P, frame_range=(60, 120))
check("範囲の端が埋まったキーなら知らせる", 120 in [f for f, _ in inside.sunk_keys],
      f"{[(f, round(d * 100, 1)) for f, d in inside.sunk_keys]}")
d120 = dict(inside.sunk_keys).get(120, 0.0)
check("範囲の時も低さは全部の時と同じくらい", abs(d120 - job.sunk_keys[0][1]) < 0.02,
      f"{d120 * 100:.1f} / {job.sunk_keys[0][1] * 100:.1f}cm")
outside = pipeline.prepare(PMX, sunk, P, frame_range=(150, 240))
check("埋まったキーが範囲の外なら知らせない", outside.sunk_keys == [], f"{outside.sunk_keys}")

print(f"\n{sum(results)}/{len(results)} OK")
sys.exit(0 if all(results) else 1)
