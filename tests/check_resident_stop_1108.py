"""11-08: MMD が全部閉じたら常駐を終わらせる（resident.stop・app._stop_residents）を確かめる。窓の Python で回す。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_resident_stop_1108.py [--real]

1. 偽の常駐（口 9561）: いれば終わらせて True・いなければすぐ False・生成中で答えなければ wait 秒であきらめて False
2. --real の時: 本物の Kimodo の常駐（llama-server 込み）を立て、app._stop_residents() で llama-server ごと消えるか
"""
import os
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Listener

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
from mmd_ainakawari import resident

PORT = 9561
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("OK " if ok else "NG ") + name + (f"（{detail}）" if detail else ""), flush=True)


def fake(accept):
    """偽の常駐。accept=False なら口だけ開けて受け取らない（生成の途中のつもり）。受け取った依頼を返す箱と、閉じる関数。"""
    box = {}
    listener = Listener(("127.0.0.1", PORT), authkey=resident.AUTHKEY)

    def run():
        if not accept:
            return
        conn = listener.accept()
        box["req"] = conn.recv()
        conn.send({"ok": True, "result": None, "line": "shutdown"})
        conn.close()
    threading.Thread(target=run, daemon=True).start()
    return box, listener.close


# 1-a いる
box, close = fake(True)
t = time.monotonic()
ok = resident.stop("偽", PORT, wait=3)
time.sleep(0.2)
check("いる常駐を終わらせる", ok and box.get("req") == {"shutdown": True}, f"{time.monotonic() - t:.1f} 秒・依頼 {box.get('req')}")
close()

# 1-b いない
t = time.monotonic()
ok = resident.stop("偽", PORT, wait=3)
# Windows の localhost は、口が閉じていると接続の拒否に約 2 秒かかる。wait より短く返れば、窓の終わりを待たせない
check("いなければ wait より早く False", ok is False and time.monotonic() - t < 2.8, f"{time.monotonic() - t:.1f} 秒")

# 1-c 答えない（生成の途中）
box, close = fake(False)
t = time.monotonic()
ok = resident.stop("偽", PORT, wait=2)
took = time.monotonic() - t
check("答えなければ wait 秒であきらめる", ok is False and 1.5 < took < 4, f"{took:.1f} 秒")
close()


def llama_pids():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, encoding="mbcs", errors="replace").stdout
    return [line.split(",")[1].strip('"') for line in out.splitlines() if line.startswith('"llama-server')]


if "--real" in sys.argv:
    from mmd_ainakawari import app, pipeline
    server = pipeline.kimodo_server()
    t = time.monotonic()
    conn = resident._ready(server, log=print)
    conn.close()
    print(f"  Kimodo の常駐を立てました（{time.monotonic() - t:.1f} 秒）・llama-server {llama_pids()}", flush=True)
    check("立てた後に llama-server がいる", bool(llama_pids()))
    t = time.monotonic()
    app._stop_residents()
    took = time.monotonic() - t
    gone = None
    for _ in range(30):
        if not llama_pids():
            gone = time.monotonic() - t
            break
        time.sleep(0.5)
    check("窓の終わりの処理で llama-server が消える", gone is not None, f"止める {took:.1f} 秒・消えるまで {gone and round(gone, 1)} 秒")
    check("口 9553 が空く", resident._connect(server) is None)

print(f"\n{sum(results)}/{len(results)}", flush=True)
sys.exit(0 if all(results) else 1)
