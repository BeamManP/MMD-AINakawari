"""11-11: 一時ファイル（生成ごとの VMD）の置き場の設定（paths.cache_dir）を確かめる。窓の Python で回す。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_cache_dir_1111.py

本物の work/paths.json は触らない（PATHS_FILE を一時フォルダに向ける）。
1. 決めていなければ work
2. 決めると、そのフォルダ（無ければ作る）。kimodo などほかの設定は残る
3. 既定に戻すと work。書けない所は OSError で、設定は変わらない
4. runner の控え・結果・「元に戻す」の控えが、置き場の方に書かれる（ソースで確かめる）
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mmd_ainakawari import paths  # noqa: E402

tmp = tempfile.mkdtemp(prefix="ainakawari_cache_")
paths.PATHS_FILE = os.path.join(tmp, "paths.json")
json.dump({"kimodo": "F:\\kimodo"}, open(paths.PATHS_FILE, "w", encoding="utf-8"))

assert paths.cache_dir() == paths.WORK_DIR, paths.cache_dir()
print("1. 既定は work: OK")

target = os.path.join(tmp, "新しい 置き場", "vmd")
paths.save_cache_dir(target)
assert paths.cache_dir() == os.path.abspath(target) and os.path.isdir(target)
assert paths.load()["kimodo"] == "F:\\kimodo"
assert os.listdir(target) == [], os.listdir(target)   # 書けるかの試しのファイルは残さない
print("2. 決めた所に作る・ほかの設定は残る:", paths.cache_dir())

paths.save_cache_dir(None)
assert paths.cache_dir() == paths.WORK_DIR and paths.CACHE_KEY not in paths.load()
blocker = os.path.join(tmp, "file")
open(blocker, "w").close()
try:
    paths.save_cache_dir(os.path.join(blocker, "x"))   # ファイルの下にはフォルダを作れない
    raise AssertionError("書けない所なのに通った")
except OSError:
    pass
assert paths.CACHE_KEY not in paths.load()
print("3. 既定に戻す・書けない所は断る: OK")

src = open(os.path.join(os.path.dirname(paths.__file__), "runner.py"), encoding="utf-8").read()
for name in ("original_", "kimodo_", "before_undo_"):
    line = next(l for l in src.splitlines() if f'f"{name}' in l)
    assert "WORK_DIR" not in line and ("cache" in line), line
print("4. runner の 3 種類の VMD は置き場に書く: OK")

# ---- 片付け（11-11 マスター）: 書き戻しの直前に前の記録の 2 つを消す・起動時に古い物を消す ----
import time  # noqa: E402
from mmd_ainakawari import runner  # noqa: E402

work = os.path.join(tmp, "work")
cache = os.path.join(tmp, "cache")
os.makedirs(work)
paths.WORK_DIR = runner.WORK_DIR = work
runner.LAST_RUN = os.path.join(work, "last_run.json")
paths.save_cache_dir(cache)


class Link:
    def __init__(self, key):
        self.key = key


def vmd_file(folder, name, age_hours=0.0):
    p = os.path.join(folder, name)
    open(p, "wb").close()
    t = time.time() - age_hours * 3600
    os.utime(p, (t, t))
    return p


a = Link("100-1")
o1, k1 = vmd_file(cache, "original_20261111_100000_100.vmd"), vmd_file(cache, "kimodo_20261111_100000_100.vmd")
assert runner._save_last_run(a, o1, k1, None) == []
o2, k2 = vmd_file(cache, "original_20261111_100100_100.vmd"), vmd_file(cache, "kimodo_20261111_100100_100.vmd")
gone = runner._save_last_run(a, o2, k2, None)
assert sorted(gone) == sorted([o1, k1]), gone
assert runner._remove_cache_files(gone) == 2 and not os.path.exists(o1) and not os.path.exists(k1)
assert runner.load_last_run(a)["backup"] == o2
print("5. 2 回目の生成で、同じ MMD の前の控えと結果だけ消す: OK")

b = Link("200-1")   # ほかの MMD が同じファイルを指していたら消さない（作り物の場面）
runner._save_last_run(b, o2, k2, None)
assert runner._save_last_run(a, vmd_file(cache, "original_20261111_100200_100.vmd"),
                             vmd_file(cache, "kimodo_20261111_100200_100.vmd"), None) == []
print("6. ほかの記録が指している物は消さない: OK")

# 起動時の掃除
c = Link("mmm300-1")   # 閉じた MMM の、8 日前の記録
oc, kc = vmd_file(cache, "original_20261103_100000_mmm300.vmd", 8 * 24), vmd_file(cache, "kimodo_20261103_100000_mmm300.vmd", 8 * 24)
runner._save_last_run(c, oc, kc, None)
orphan_old = vmd_file(cache, "original_20261110_090000_100.vmd", 30)      # 中断した回（記録なし・30 時間前）
undo_old = vmd_file(cache, "before_undo_20261110_090000_100.vmd", 30)
orphan_new = vmd_file(cache, "original_20261111_110000_100.vmd", 1)       # 中断したばかり（1 時間前）→ 残す
old_work = vmd_file(work, "kimodo_20261101_090000_100.vmd", 200)          # 置き場を変える前の work の物
hand = vmd_file(cache, "check_after.vmd", 200)                            # 手で置いた物 → 名前が違うので残す
hand2 = vmd_file(cache, "kimodo_slalom.vmd", 200)
hand3 = vmd_file(cache, "kimodo_20261111_check_thin_new.vmd", 200)
no_pid = vmd_file(work, "kimodo_20261103_090000.vmd", 200)                # 11-04 より前の、番号の無い名前
assert runner.sweep_cache() == 6
for p in (oc, kc, orphan_old, undo_old, old_work, no_pid):
    assert not os.path.exists(p), p
for p in (orphan_new, hand, hand2, hand3, o2, k2):
    assert os.path.exists(p), p
runs = json.load(open(runner.LAST_RUN, encoding="utf-8"))
assert set(runs) == {"100-1", "200-1"}, runs.keys()
assert runner.sweep_cache() == 0
print("7. 起動時の掃除: 7 日より古い記録を外し、記録に無い 1 日より古い物（work も）を消す・手で置いた物は残す: OK")
print("全部 OK")
