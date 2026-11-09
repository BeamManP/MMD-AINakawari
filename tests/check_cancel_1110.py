"""11-10: 生成の中断（「生成」が生成中は「中断」になる）を確かめる。窓の Python で回す。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_cancel_1110.py [--real]

1. 中断の印: cancellable の中だけで効く・外や別のスレッドには効かない・入れ子は戻る
2. acquire: 取れない間に中断されたら Cancelled・取れたら持ち主が放す
3. 常駐の作り物（合言葉つきの口）で:
   a. 答えを待っている間に中断すると、同じ接続で {"cancel": True} が届き、常駐の「やめた」の答えで Cancelled
   b. 中断を知らない古い橋渡し（最後まで作って結果を返す）でも、結果を捨てて Cancelled
   c. 中断しなければ、今までどおり結果が返る
4. --real の時: 本物の常駐で（MMD は使わない。口 9552・9553 を使う）
   a. Kimodo: 300 フレームの途中で中断 → 数秒で止まる・常駐は生きたまま・次の生成は読み込み直さずに作れる
   b. Kimodo: 常駐の読み込みの途中で中断 → すぐ戻る・常駐は読み込みを続け、次の生成で使える
   c. MotionBricks: たくさんの中割りの途中で中断 → 止まる・次の中割りは作れる
"""
import json
import os
import sys
import threading
import time
from multiprocessing.connection import Listener

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from mmd_ainakawari import paths, pipeline, resident, smooth_stop  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("OK " if ok else "NG ") + name + (f"（{detail}）" if detail else ""), flush=True)


def outcome(fn):
    """fn() を回して ("ok", 値) か ("cancelled", None) か ("error", 例外)。"""
    try:
        return "ok", fn()
    except resident.Cancelled:
        return "cancelled", None
    except Exception as e:
        return "error", e


# 1. 中断の印
event = threading.Event()
check("外では効かない", not resident.cancel_requested())
with resident.cancellable(event):
    check("立てる前は効かない", not resident.cancel_requested() and outcome(resident.check_cancel)[0] == "ok")
    event.set()
    check("立てると効く", resident.cancel_requested() and outcome(resident.check_cancel)[0] == "cancelled")
    seen = []
    t = threading.Thread(target=lambda: seen.append(resident.cancel_requested()))
    t.start()
    t.join()
    check("別のスレッドには効かない", seen == [False])
    with resident.cancellable(None):
        check("入れ子の None は「中断なし」", not resident.cancel_requested())
    check("入れ子を出ると戻る", resident.cancel_requested())
check("出ると効かない", not resident.cancel_requested())
check("Cancelled の文は「中断しました」", str(resident.Cancelled()) == "中断しました")

# 2. acquire
lock = threading.Lock()
lock.acquire()
event = threading.Event()
threading.Timer(0.5, event.set).start()
t0 = time.time()
with resident.cancellable(event):
    kind = outcome(lambda: resident.acquire(lock))[0]
check("取れない間に中断されたら Cancelled", kind == "cancelled" and 0.4 < time.time() - t0 < 2, f"{time.time() - t0:.1f} 秒")
lock.release()
with resident.cancellable(threading.Event()):
    resident.acquire(lock)
check("取れたら持っている", lock.locked())
lock.release()


# 3. 常駐の作り物
def fake_resident(port, mode, got):
    """1 回だけ頼まれる常駐。mode: "new"（中断を見てやめる）・"old"（中断を知らず、2 秒かけて作る）・"quick"（すぐ返す）。"""
    listener = Listener(("127.0.0.1", port), authkey=resident.AUTHKEY)

    def serve():
        conn = listener.accept()
        got["request"] = conn.recv()
        if mode == "quick":
            conn.send({"ok": True, "result": {"frames": 1}, "line": "ok"})
        elif mode == "new":
            deadline = time.time() + 10
            while time.time() < deadline:
                if conn.poll(0.05):
                    got["second"] = conn.recv()
                    conn.send({"ok": False, "cancelled": True})
                    break
            else:
                conn.send({"ok": True, "result": {"frames": 1}, "line": "too late"})
        else:
            time.sleep(2)
            conn.send({"ok": True, "result": {"frames": 1}, "line": "ok"})
        conn.close()
        listener.close()
    threading.Thread(target=serve, daemon=True).start()


for i, (mode, press, want) in enumerate((("new", True, "cancelled"), ("old", True, "cancelled"), ("quick", False, "ok"))):
    port = 9571 + i
    got = {}
    fake_resident(port, mode, got)
    server = resident.Server("作り物", port, "", "", "", {})
    event = threading.Event()
    if press:
        threading.Timer(0.5, event.set).start()
    t0 = time.time()
    with resident.cancellable(event):
        kind, value = outcome(lambda: resident.call(server, {"job": 1}, log=lambda _l: None))
    took = time.time() - t0
    if mode == "new":
        check("中断すると同じ接続で知らせが届き、常駐がやめたら Cancelled", kind == want and got.get("second") == {"cancel": True} and took < 2,
              f"{took:.1f} 秒・届いた物 {got.get('second')}")
    elif mode == "old":
        check("中断を知らない橋渡しでも、結果を捨てて Cancelled", kind == want, f"{took:.1f} 秒")
    else:
        check("中断しなければ結果が返る", kind == want and value == ({"frames": 1}, "ok"), str(value))


def kimodo_job(frames, seed=1):
    class Job:
        request = {"prompt": "A person walks forward.", "num_frames": frames, "steps": 100, "seed": seed,
                   "segments": [{"prompt": "A person walks forward.", "frames": frames}], "post_processing": True,
                   "keys": [], "root_keys": [], "root_y_keys": [], "ee_keys": [], "cfg_weight": [2.0, 2.0]}
    return Job()


def log_text(name):
    return open(os.path.join(resident.LOG_DIR, f"{name}_server.log"), encoding="utf-8", errors="replace").read()


if "--real" in sys.argv:
    work = os.path.join(HERE, "work", "check_cancel")
    lines = []
    # 4b. 読み込みの途中で中断（常駐がいない所から）
    resident.stop(pipeline.KIMODO_NAME, pipeline.KIMODO_PORT)
    time.sleep(1)
    event = threading.Event()
    threading.Timer(2.0, event.set).start()
    t0 = time.time()
    with resident.cancellable(event):
        kind, _ = outcome(lambda: pipeline.run_kimodo(kimodo_job(60), work, on_line=lines.append, use_llama=False))
    took = time.time() - t0
    check("--real Kimodo: 読み込みの途中で中断するとすぐ戻る", kind == "cancelled" and took < 5, f"{kind}・{took:.1f} 秒")
    t0 = time.time()
    kind, value = outcome(lambda: pipeline.run_kimodo(kimodo_job(60), work, on_line=lines.append, use_llama=False))
    check("--real Kimodo: 読み込みを続けていた常駐で、次の生成が作れる", kind == "ok" and value.get("num_frames") == 60
          and log_text(pipeline.KIMODO_NAME).count("ready port=") == 1, f"{kind}・{time.time() - t0:.1f} 秒")

    # 4a. 作っている途中で中断
    event = threading.Event()
    threading.Timer(1.5, event.set).start()
    t0 = time.time()
    with resident.cancellable(event):
        kind, _ = outcome(lambda: pipeline.run_kimodo(kimodo_job(300), work, on_line=lines.append, use_llama=False))
    took = time.time() - t0
    time.sleep(0.5)
    text = log_text(pipeline.KIMODO_NAME)
    check("--real Kimodo: 作っている途中で中断すると、数秒で止まる", kind == "cancelled" and took < 5, f"{kind}・{took:.1f} 秒")
    check("--real Kimodo: 常駐は「やめた」と記録して生きている", text.rstrip().endswith("cancelled") and text.count("ready port=") == 1,
          text.strip().splitlines()[-1][-60:])
    t0 = time.time()
    kind, value = outcome(lambda: pipeline.run_kimodo(kimodo_job(60), work, on_line=lines.append, use_llama=False))
    took = time.time() - t0
    check("--real Kimodo: 中断の後、読み込み直さずに作れる", kind == "ok" and value.get("num_frames") == 60
          and log_text(pipeline.KIMODO_NAME).count("ready port=") == 1 and took < 30, f"{kind}・{took:.1f} 秒")
    check("--real Kimodo: 中断しない生成の結果は今までどおり（キーなし・60 フレーム・回転 30 関節）",
          kind == "ok" and len(value["local_rot"]) == 60 * 30 * 4)
    resident.stop(pipeline.KIMODO_NAME, pipeline.KIMODO_PORT)

    # 4c. MotionBricks
    if not smooth_stop.available():
        check("--real MotionBricks が入っている", False)
    else:
        soma = json.load(open(paths.soma_json(), encoding="utf-8"))
        pose = {"root": soma["neutral_joints"][soma["root_idx"]], "local_rot": [0.0, 0.0, 0.0, 1.0] * len(soma["names"])}
        job = {"context": [pose] * 4, "targets": [{"poses": [pose], "frames": 30, "num_poses_to_use": 1}] * 6}
        mb_work = os.path.join(work, "mb")
        kind, value = outcome(lambda: smooth_stop._run({"skeleton": paths.soma_json(), "jobs": [job]}, mb_work, log=lines.append))
        check("--real MotionBricks: 中断しなければ作れる", kind == "ok" and value["results"][0]["num_frames"] == 181, kind)
        event = threading.Event()
        threading.Timer(1.0, event.set).start()
        t0 = time.time()
        with resident.cancellable(event):
            kind, _ = outcome(lambda: smooth_stop._run({"skeleton": paths.soma_json(), "jobs": [job] * 60}, mb_work, log=lines.append))
        took = time.time() - t0
        time.sleep(0.5)
        text = log_text("MotionBricks")
        check("--real MotionBricks: たくさんの中割りの途中で中断すると止まる", kind == "cancelled" and took < 5
              and text.rstrip().endswith("cancelled"), f"{kind}・{took:.1f} 秒")
        kind, value = outcome(lambda: smooth_stop._run({"skeleton": paths.soma_json(), "jobs": [job]}, mb_work, log=lines.append))
        check("--real MotionBricks: 中断の後、読み込み直さずに作れる", kind == "ok" and log_text("MotionBricks").count("ready port=") == 1, kind)
        resident.stop("MotionBricks", smooth_stop.MB_PORT)

print(f"\n{sum(results)}/{len(results)} OK")
sys.exit(0 if all(results) else 1)
