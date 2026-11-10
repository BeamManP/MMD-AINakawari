"""11-11 動作報告: AIナカワリ から読み込む時だけ「不足しているボーン／モーフはありません。」の窓が出て、読み込めているのに失敗にしていた件を、
作り物の MMD で確かめる（窓の Python で回す。MMD も Kimodo も呼ばない）。

    work\\release\\stage\\MMD-AINakawari\\python\\python.exe -X utf8 tests\\check_notice_1111.py

どの段で窓が出るかは未特定なので、範囲選択・キーを消す・読み込むの各段で、お知らせの窓（ボタン 1 つ）が出た場合を回す。
窓を閉じるところ（_dismiss_notices・_still_open）と、MMD の中身で確かめるところ（_keys_cleared・_loaded_after_error）は作り物に差し替える。
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from mmd_ainakawari import applog, mmd_link, vmd  # noqa: E402

TMP = tempfile.mkdtemp(prefix="ainakawari_notice_")
PMX = os.path.join(TMP, "model.pmx")
results = []
logged = []
applog.write = logged.append

NOTICE = {"hwnd": 999, "title": "", "controls": [
    {"class": "Static", "text": "不足しているボーン／モーフはありません。"}, {"class": "Static", "text": "スタティック"},
    {"class": "Button", "text": "OK", "hwnd": 1000}]}

motion = vmd.Motion(model_name="初音ミク", bones=[vmd.BoneKey("センター", f, np.zeros(3), np.array([0, 0, 0, 1.0])) for f in (0, 30)])
out = os.path.join(TMP, "kimodo.vmd")
backup = os.path.join(TMP, "original.vmd")
vmd.write(out, motion)
vmd.write(backup, motion)


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'OK ' if ok else 'NG '} {name}" + (f" … {detail}" if detail else ""))


def notice(**k):
    return {"status": "dialog_requires_action", "dialogs": [NOTICE], **k}


def run(select=None, delete=None, load=None, cleared=True, loaded=True, still_open=False):
    """select・delete・load: 段ごとに返す物の並び（足りなければ completed）。log と、投げた例外の文を返す。"""
    select, delete, load = list(select or []), list(delete or []), list(load or [])
    log = []
    link = mmd_link.MMDLink(hwnd=1)
    link.state = lambda: {"model_selected": True, "model": "model"}
    link.selected_model = lambda: {"path": PMX, "name": "model"}
    link.current_frame = lambda: 0
    link._dismiss_notices = lambda r, timeout=3.0: (log.append("dismiss"), ["不足しているボーン／モーフはありません。", "スタティック"])[1]
    link._still_open = lambda dialogs: still_open
    link._keys_cleared = lambda track, wait=5.0: (log.append(("cleared?", track)), cleared)[1]
    link._loaded_after_error = lambda path, wait=10.0: (log.append(("loaded?", os.path.basename(path))), loaded)[1]
    mmd_link.playback.get = lambda hwnd=None: {"playing": False}
    mmd_link.scene.set_frame = lambda *a, **k: None

    def select_range(start, end, track, hwnd=None):
        log.append(("select", track))
        return select.pop(0) if select else {"status": "completed"}

    def perform(actions, hwnd=None):
        log.append("delete")
        return delete.pop(0) if delete else {"status": "completed"}

    def load_file(kind, path, hwnd=None):
        log.append(("load", os.path.basename(path)))
        return load.pop(0) if load else {"status": "completed"}
    mmd_link.timeline.select_range = select_range
    mmd_link.edit_actions.perform = perform
    mmd_link.files.load_file = load_file
    logged.clear()
    try:
        link.load_motion(out, 0, model=PMX, restore=backup)
        return log, ""
    except RuntimeError as e:
        return log, str(e)


# A. 報告の場面（と見ている物）: 読み込んだ後にお知らせの窓。中身は入っている → 成功、バックアップは読まない
log, err = run(load=[notice(path_submitted=True)])
check("A. 読み込みの後のお知らせの窓は閉じて、中身が入っていれば成功", not err and ("load", "original.vmd") not in log, f"{log} {err}")
check("A. 窓を見た段とその中身をログに残す", any("モーションを読み込む時" in l and "不足しているボーン" in l for l in logged), str(logged[:1]))

# B. お知らせの窓を閉じても、中身が入っていない → バックアップで戻して、段の名前つきで知らせる
log, err = run(load=[notice(path_submitted=True), {"status": "completed"}], loaded=False)
check("B. 中身が入っていなければ、バックアップで戻して知らせる", ("load", "original.vmd") in log and "戻しました" in err, err)
check("B. エラーの文に、窓が出た段が入る", "モーションを読み込む時" in err, err)

# C. ボーンのキーを消す時にお知らせの窓。消えていれば先へ進んで読み込む
log, err = run(delete=[notice()])
check("C. キーを消す時のお知らせの窓は閉じて、消えていれば読み込みへ進む",
      not err and ("cleared?", "全ボーンﾌﾚｰﾑ") in log and ("load", "kimodo.vmd") in log, f"{log} {err}")

# D. 範囲選択の時にお知らせの窓。閉じて、消す操作へ進む
log, err = run(select=[notice()])
check("D. 範囲選択の時のお知らせの窓は閉じて、消す操作へ進む", not err and log.count("delete") == 2, f"{log} {err}")

# E. 閉じない窓（ボタンが 2 つなど）が読み込みの時に出たら、確かめずに戻しへ（押さずに止める）
log, err = run(load=[notice(path_submitted=True), {"status": "completed"}], still_open=True)
check("E. 閉じない窓なら、中身を確かめずにバックアップで戻す",
      not any(isinstance(x, tuple) and x[0] == "loaded?" for x in log) and ("load", "original.vmd") in log, f"{log} {err}")

# F. ボーンの範囲選択で閉じない窓 → キーを消さずに止まる
log, err = run(select=[notice()], still_open=True)
check("F. 範囲選択で閉じない窓なら、キーを消さずに止まる", "delete" not in log and "消していません" in err, f"{log} {err}")

# G. キーを消す操作を送った後で止まったら（消えていない）、戻しを通す
log, err = run(delete=[notice()], cleared=False)
check("G. 消す操作の後で止まったら、バックアップで戻す", ("load", "original.vmd") in log and "キーを消す時" in err, f"{log} {err}")

print("---")
print(f"{sum(results)}/{len(results)} 通った")
sys.exit(0 if all(results) else 1)
