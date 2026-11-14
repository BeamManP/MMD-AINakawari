"""11-14: 外からの操作の口を足した時に書き換えた、窓の「終わった時の処理」を確かめる。本物の窓の部品（app.App）を使う。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\live_control_window_1114.py [MMD の窓]

MMD（モデルは要らない）が 1 つ開いていること。MMD のキー・場面は触らない（生成はしない。右下のパネルにも書かない）。
窓のボタンから動かした時と、外から頼まれた時（app.remote がある時）の違いを見る:
1. 窓から動かして失敗 → 知らせの窓が出る（今までどおり）／成功・中断 → 出ない
2. 外から頼まれて失敗 → 知らせの窓は出ず、依頼の記録が failed になり理由が入る
3. 書き戻しの合図で committing、終わりで done（busy が下りるのと同じ時）
4. 生成の仕事（_work）が窓へ渡す結果の形: 成功・中断・失敗
5. 外からの頼みを断る時の code: 動いていない時の中断・元に戻せる物が無い・途中の時
6. 外からの依頼の途中で窓を片付けると、記録は failed になる
"""
import os
import sys
import tkinter as tk

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from mmd_ainakawari import app as app_module, control, hosts, panel, resident  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("OK " if ok else "NG ") + name + (f"（{detail}）" if detail else ""), flush=True)


host = hosts.find(int(sys.argv[1])) if len(sys.argv) > 1 else hosts.front()
if host is None:
    sys.exit("MMD が開いていません")
panel.Panel.find = lambda self: None   # 本物の MMD の右下のパネルには書かない（動いている窓の表示を乱さない）
boxes = []
app_module.messagebox.showerror = lambda *a, **k: boxes.append(a[1] if len(a) > 1 else a)


class Hub:
    jobs = control.Jobs()
    forgotten = []

    def forget(self, app):
        self.forgotten.append(app)


root = tk.Tk()
root.withdraw()
hub = Hub()
app = app_module.App(tk.Toplevel(root), hub, host)
hwnd = host.hwnd


def tick(*events):
    app.busy = True
    for event in events:
        app.q.put(event)
    with app_module.i18n.use(app.lang):
        app._tick_body()


# 1. 窓から動かした時
tick(("done", ("failed", "失敗: 試し", None)))
check("窓から動かして失敗 → 知らせの窓が出る", boxes == ["失敗: 試し"] and not app.busy and app.status.get() == "失敗: 試し", str(boxes))
tick(("done", ("done", "できました", {"backup": "b.vmd"})))
tick(("done", ("cancelled", "中断しました", None)))
check("窓から動かして成功・中断 → 知らせの窓は出ない", len(boxes) == 1 and app.status.get() == "中断しました" and not app.busy)

# 2・3. 外から頼まれた時
job = hub.jobs.new("generate", hwnd, {"prompt": "x"})
app.remote = job
app.cancellable = True
tick(("log", "生成中の 1 行"), ("commit", None))
check("書き戻しの合図で committing・ログが記録に入る", job["state"] == "committing" and job["committed"] and app.busy
      and not app.cancellable and list(job["log"]) == ["生成中の 1 行"], str(control.public(job)))
tick(("done", ("failed", "失敗: 外から", None)))
check("外から頼まれて失敗 → 知らせの窓は出ず、記録に理由が入る", len(boxes) == 1 and job["state"] == "failed"
      and job["error"] == "失敗: 外から" and app.remote is None and not app.busy, f"窓 {len(boxes)}・{job['state']}")
job = hub.jobs.new("generate", hwnd)
app.remote = job
tick(("commit", None), ("done", ("done", "できました", {"backup": "b.vmd", "output": "o.vmd", "span": {"range": [0, 60]}, "model": "m.pmx"})))
check("外から頼まれて成功 → done と結果", job["state"] == "done" and job["result"]["output"] == "o.vmd" and job["committed"]
      and app.remote is None and len(boxes) == 1)
tick(("done", ("failed", "失敗: 次は窓から", None)))
check("外からの依頼が終わった後、窓から動かした失敗はまた知らせの窓が出る", len(boxes) == 2)

# 4. 生成の仕事が窓へ渡す形
kept = app.last_backup, app.last_run


def worked(fn):
    with app_module.i18n.use(app.lang):
        app._work(fn, "できた")
    out = []
    while not app.q.empty():
        out.append(app.q.get())
    return out


def fails(log):
    raise RuntimeError("壊れた")


def cancelled(log):
    raise resident.Cancelled()


out = worked(lambda log: {"backup": "new.vmd", "span": 1})
check("成功 → done と結果", out == [("done", ("done", "できた", {"backup": "new.vmd", "span": 1}))] and app.last_backup == "new.vmd", str(out))
app.last_backup, app.last_run = kept
out = worked(cancelled)
check("中断 → cancelled", out[-1][0] == "done" and out[-1][1][0] == "cancelled" and out[-1][1][2] is None and out[0][0] == "log", str(out))
out = worked(fails)
check("失敗 → failed と理由", out[-1] == ("done", ("failed", "失敗: 壊れた", None)) and out[-2] == ("log", "失敗: 壊れた"), str(out))
app.last_backup, app.last_run = kept


# 5. 断る時の code
def refused(fn):
    try:
        fn()
    except control.Refused as e:
        return e.code
    return None


app.busy = False
check("動いていない時の中断 → not_running", refused(app.remote_cancel) == "not_running")
app.last_backup = None
check("元に戻せる物が無い → nothing_to_undo", refused(app.remote_undo) == "nothing_to_undo")
app.last_backup = kept[0]
app.busy = True
check("途中の時の生成・元に戻す → busy", refused(lambda: app.remote_generate({"prompt": "x"})) == "busy" and refused(app.remote_undo) == "busy")
app.cancellable = False
check("書き戻しに入った後の中断 → not_cancellable", refused(app.remote_cancel) == "not_cancellable")
app.cancellable = True
check("ほかの番号を付けた中断 → not_running", refused(lambda: app.remote_cancel("ほかの番号")) == "not_running")   # i18n: skip
app.remote = hub.jobs.new("generate", hwnd)
got = app.remote_cancel(app.remote["id"])
check("中断を頼むと印が立つ", app.cancel.is_set() and got["cancel_requested"] and got is app.remote)
app.cancel.clear()
state = app.remote_state()
check("様子（status）の形", state["busy"] and state["running_job"] == app.remote["id"] and state["host"]["hwnd"] == hwnd
      and set(state["ready"]) == {"gpu", "gpu_note", "kimodo", "motionbricks", "free_prompt"} and "seed" in state["defaults"]
      and state["model"] is None and not state["undo_available"], str({k: state[k] for k in ("busy", "running_job", "ready")}))

# 6. 途中で窓を片付ける
job = app.remote
app.close()
check("外からの依頼の途中で窓を片付けると failed", job["state"] == "failed" and job["error"] and hub.forgotten == [app], job["error"])
root.destroy()

print("---")
print(f"{sum(results)}/{len(results)} OK")
sys.exit(0 if all(results) else 1)
