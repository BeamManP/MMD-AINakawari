# Kimodo の SOMA 30 関節の骨格（名前・親・標準 T ポーズでの位置[m]）を JSON に書き出す。AIナカワリが Kimodo の動きを MMD の骨に直すのに使う。
# Kimodo の Python で回す:  F:\kimodo\.venv\Scripts\python.exe tools\export_skeleton.py F:\kimodo\tools\somaskel30.json
# （書き出す場所は mmd_ainakawari/pipeline.py の SOMA_JSON。11-02 に F:\kimodo\tools で作った物をここに入れた）
import json, sys
from kimodo.skeleton.registry import build_skeleton

skel = build_skeleton(30)
names = list(skel.bone_order_names)
parents = [int(p) for p in skel.joint_parents.cpu().numpy()]
neutral = skel.neutral_joints.cpu().numpy().tolist()
out = {"name": skel.name, "names": names, "parents": parents, "neutral_joints": neutral,
       "neutral_flat": [v for p in neutral for v in p], "root_idx": int(skel.root_idx)}
json.dump(out, open(sys.argv[1], "w"), indent=1)
for n, p, q in zip(names, parents, neutral):
    print(f"{n:22s} parent={names[p] if p >= 0 else '-':16s} pos={[round(v, 3) for v in q]}")
