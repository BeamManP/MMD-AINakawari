"""「センターに合わせて作る」（11-07 にやりたいことの 4 つ目にした）を、作り物で確かめる。Kimodo は呼ばない（prepare まで）。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_center_1107.py

キーのあるフレームも全身のポーズにせず、腰の目印だけにするか。範囲の端だけはポーズを守るか。埋めると同じ範囲か。
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


demo = vmd.read(DEMO)
P = "A person dances."
fill = pipeline.prepare(PMX, demo, P)
center = pipeline.prepare(PMX, demo, P, use_keys=False, use_center=True)
check("全部: 埋めると同じ範囲を作る", (center.first, center.num_frames) == (fill.first, fill.num_frames),
      f"{center.first}F から {center.num_frames} フレーム")
check("全部: キーのフレームを全身のポーズにしない", center.frames == [], f"{center.frames}")
keyed = [f for f in fill.frames]
check("全部: キーのフレームも腰の目印にする", set(keyed) <= set(center.root_frames), f"キー {keyed}")
check("全部: 毎フレームが腰の目印", len(center.root_frames) == center.num_frames, f"{len(center.root_frames)}")
check("止める目印は付けない", not center.stop_frames)

fill_r = pipeline.prepare(PMX, demo, P, frame_range=(30, 90))
center_r = pipeline.prepare(PMX, demo, P, frame_range=(30, 90), use_keys=False, use_center=True)
check("範囲: 埋めると同じ範囲を作る", (center_r.first, center_r.num_frames) == (fill_r.first, fill_r.num_frames))
check("範囲: ポーズを守るのは端（30・90F）と外側の文脈だけ", 60 not in center_r.frames and {30, 90} <= set(center_r.frames),
      f"{center_r.frames}")
check("範囲: 中のキー（60F）は腰の目印", 60 in center_r.root_frames)

print(f"---\n{sum(results)}/{len(results)} 通った")
sys.exit(0 if all(results) else 1)
