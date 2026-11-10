"""11-10: 回線が細い・不安定な所でもセットアップが通るようにした変更を確かめる。窓の Python で回す（ネットは使わない）。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_setup_net_1110.py

1. 外のプロセスに渡す環境: uv と huggingface_hub の時間切れを長くする・同時に落とす数を減らす。使う人が決めていればそちら
2. 通信の失敗の見分け: uv の実物の文（つながらない相手・引けない名前）は通信の失敗・ふつうの失敗は違う
3. Setup.call: 通信の失敗は待ってやり直す・済めば通る／やり直しても駄目なら、案内つきの失敗／ふつうの失敗はやり直さない／中止はすぐ出る
4. 進み具合の 1 行: 黙っている手順でも、かかった時間と、ここまでに使った量が出る
5. Setup.download（手元の小さなサーバーから）: 途中で切れても続きから落とし直して、照らして置く／切れ続けたら案内つきの失敗／無い物（404）はやり直さない
6. 中途半端な場所にかけ直しても直る: 済んだ印があっても中身が欠けていればやり直す（Setup.intact）・そろっていれば点検だけで終わる
"""
import hashlib
import http.server
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from mmd_ainakawari.installer import steps  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("OK " if ok else "NG ") + name + (f"（{detail}）" if detail else ""), flush=True)


tmp = tempfile.mkdtemp(prefix="ainakawari_net_")
logs, shown = [], []
setup = steps.Setup(os.path.join(tmp, "dest"), log=logs.append, progress=shown.append, with_text=False)
os.makedirs(setup.dest)
steps.NETWORK_WAIT = 0.3   # テストでは待たない

# 1. 環境
for key in ("UV_HTTP_TIMEOUT", "UV_HTTP_RETRIES", "UV_CONCURRENT_DOWNLOADS", "HF_HUB_DOWNLOAD_TIMEOUT"):
    os.environ.pop(key, None)
env = setup.env()
check("uv の時間切れを長くする（既定は 30 秒）", int(env["UV_HTTP_TIMEOUT"]) >= 300 and int(env["UV_HTTP_RETRIES"]) >= 5, env["UV_HTTP_TIMEOUT"])
check("同時に落とす数を減らす（既定は 50）", int(env["UV_CONCURRENT_DOWNLOADS"]) <= 8, env["UV_CONCURRENT_DOWNLOADS"])
check("huggingface_hub の時間切れも長くする（既定は 10 秒）", int(env["HF_HUB_DOWNLOAD_TIMEOUT"]) >= 60)
os.environ["UV_HTTP_TIMEOUT"] = "900"
check("使う人が決めた値はそのまま", setup.env()["UV_HTTP_TIMEOUT"] == "900")
del os.environ["UV_HTTP_TIMEOUT"]

# 2. 見分け（uv 0.9.26 が実際に出した文。11-10）
REAL = {
    "つながらない相手": "error: Failed to fetch: `http://10.255.255.1/simple/six/`\n  Caused by: error sending request for url "
                        "(http://10.255.255.1/simple/six/)\n  Caused by: operation timed out",
    "引けない名前": "error: Failed to fetch: `https://nonexistent.invalid/simple/six/`\n  Caused by: error sending request for url\n"
                    "  Caused by: client error (Connect)\n  Caused by: dns error\n  Caused by: そのようなホストは不明です。 (os error 11001)",
    "huggingface_hub": "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='huggingface.co', port=443): Read timed out.",
}
for name, text in REAL.items():
    check(f"通信の失敗と見る: {name}", bool(steps.NETWORK_RE.search(text)))
OTHER = {
    "ハッシュが合わない": "error: Hash mismatch for `torch==2.11.0`\n  Expected: sha256:aaa\n  Computed: sha256:bbb",
    "Python の例外": "Traceback (most recent call last):\n  File \"x.py\", line 3\nRuntimeError: No CUDA GPUs are available",
    "空きが無い": "error: Failed to install: torch\n  Caused by: failed to write to file: ディスクに十分な空き領域がありません。 (os error 112)",
    "消せない": "error: Failed to create virtual environment\n  Caused by: failed to remove directory: アクセスが拒否されました。 (os error 5)",
}
for name, text in OTHER.items():
    check(f"通信の失敗と見ない: {name}", not steps.NETWORK_RE.search(text))

# 3. call のやり直し
counter = os.path.join(tmp, "count.txt")
FLAKY = ("import os, sys; p = sys.argv[1]; n = int(open(p).read()) if os.path.exists(p) else 0; open(p, 'w').write(str(n + 1));"
         "print('Downloading torch (2.5GiB)');"
         "sys.exit(0) if n >= int(sys.argv[2]) else (print('error: Failed to fetch: x\\n  Caused by: operation timed out'), sys.exit(2))")


def count():
    return int(open(counter).read()) if os.path.exists(counter) else 0


def outcome(fn):
    try:
        fn()
        return "ok", ""
    except steps.Cancelled:
        return "cancelled", ""
    except steps.Failed as e:
        return "failed", str(e)


kind, _ = outcome(lambda: setup.call([sys.executable, "-c", FLAKY, counter, "2"], "部品を入れる", retries=2))
check("通信の失敗は待ってやり直し、3 回目で通る", kind == "ok" and count() == 3 and sum("もう一度試します" in line for line in logs) == 2, f"{kind}・{count()} 回")
os.remove(counter)
logs.clear()
kind, text = outcome(lambda: setup.call([sys.executable, "-c", FLAKY, counter, "9"], "部品を入れる", retries=2))
check("やり直しても駄目なら、案内つきの失敗", kind == "failed" and count() == 3 and text.startswith(steps.NETWORK_HINT) and "operation timed out" in text, text[:60])
os.remove(counter)
kind, text = outcome(lambda: setup.call([sys.executable, "-c", FLAKY, counter, "9"], "部品を入れる"))
check("やり直しを頼んでいない手順は 1 回で失敗（通信の案内は付く）", kind == "failed" and count() == 1 and text.startswith(steps.NETWORK_HINT))
os.remove(counter)
PLAIN = ("import os, sys; p = sys.argv[1]; n = int(open(p).read()) if os.path.exists(p) else 0; open(p, 'w').write(str(n + 1));"
         "print('RuntimeError: boom'); sys.exit(1)")
kind, text = outcome(lambda: setup.call([sys.executable, "-c", PLAIN, counter], "部品を入れる", retries=2))
check("ふつうの失敗はやり直さない・通信の案内も付けない", kind == "failed" and count() == 1 and steps.NETWORK_HINT not in text and "boom" in text)
os.remove(counter)
threading.Timer(0.5, setup.cancel).start()
steps.NETWORK_WAIT = 30
t0 = time.time()
kind, _ = outcome(lambda: setup.call([sys.executable, "-c", FLAKY, counter, "9"], "部品を入れる", retries=2))
check("やり直しを待っている間の中止は、すぐ出る", kind == "cancelled" and time.time() - t0 < 5, f"{kind}・{time.time() - t0:.1f} 秒")
steps.NETWORK_WAIT = 0.3
setup._stop.clear()

# 4. 進み具合の 1 行（7 秒黙って、入れる場所に 300MB 書く手順）
shown.clear()
QUIET = "import sys, time; f = open(sys.argv[1], 'wb'); [(f.write(b'x' * 50_000_000), f.flush(), time.sleep(1)) for _ in range(6)]; f.close(); time.sleep(1)"
setup.call([sys.executable, "-c", QUIET, os.path.join(setup.dest, "big.bin")], "Kimodo の部品を入れる")
ticks = [line for line in shown if line.startswith("Kimodo の部品を入れる…")]
check("黙っている手順でも、時間が何度も出る", len(ticks) >= 2 and "分" in ticks[-1] and "秒" in ticks[-1], f"{len(ticks)} 回・最後「{ticks[-1] if ticks else ''}」")
check("ここまでに使った量が出る", any("ここまでに約 0." in line and "GB" in line for line in ticks), ticks[-1] if ticks else "")
os.remove(os.path.join(setup.dest, "big.bin"))
shown.clear()
UV_LINES = ("import time; p = lambda s: print(s, flush=True);"
            "p('Downloading torch (2.5GiB)'); p('Downloading numpy (12.0MiB)'); time.sleep(3); p(' Downloaded numpy'); time.sleep(4);"
            "p(' Downloaded torch'); time.sleep(3)")
setup.call([sys.executable, "-c", UV_LINES], "Kimodo の部品を入れる")
check("落としている物を、時間の後ろに出す", any("落としている物: torch（2.5GiB）・numpy（12.0MiB）" in line and "秒" in line for line in shown),
      next((line for line in shown if "落としている物" in line), ""))
later = [line for line in shown if "0 分 06 秒" in line or "0 分 05 秒" in line]
check("先に終わった小さい物は消えて、まだ落としている大きい物だけ残る", any("落としている物: torch（2.5GiB）" in line and "numpy" not in line for line in later),
      later[-1] if later else "")
check("全部落とし終わったら、落としている物は出さない", "落としている物" not in shown[-1], shown[-1])

# 5. 自前のダウンロード（手元のサーバー。何回目まで途中で切るかを決められる）
DATA = os.urandom(3_000_000)
DIGEST = hashlib.sha256(DATA).hexdigest()
state = {"cut": 0, "requests": []}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/file.bin":
            self.send_error(404)
            return
        start = int(self.headers["Range"].split("=")[1].rstrip("-")) if self.headers.get("Range") else 0
        state["requests"].append(start)
        body = DATA[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if state["cut"] > 0:   # 3 分の 1 だけ送って、接続を切る
            state["cut"] -= 1
            self.wfile.write(body[: len(body) // 3])
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f"http://127.0.0.1:{server.server_address[1]}/file.bin"
try:
    logs.clear()
    state.update(cut=2, requests=[])
    target = os.path.join(setup.dest, "downloads", "file.bin")
    kind, text = outcome(lambda: setup.download(url, target, "モデル", digest=DIGEST, size=len(DATA)))
    check("途中で 2 回切れても、続きから落とし直して置く", kind == "ok" and os.path.isfile(target) and hashlib.sha256(open(target, "rb").read()).hexdigest() == DIGEST
          and len(state["requests"]) == 3 and state["requests"][0] == 0 < state["requests"][1] < state["requests"][2],
          f"{kind}・頼んだ位置 {state['requests']}・{text[:60]}")
    check("落とし直す時に、続きの位置を知らせる", sum("続き（" in line for line in logs) == 2)
    os.remove(target)
    state.update(cut=99, requests=[])
    steps.DOWNLOAD_RETRIES = 3
    kind, text = outcome(lambda: setup.download(url, target, "モデル", digest=DIGEST, size=len(DATA)))
    check("切れ続けたら、案内つきの失敗（途中までは残す）", kind == "failed" and text.startswith(steps.NETWORK_HINT) and len(state["requests"]) == 4
          and os.path.isfile(target + ".part"), f"{kind}・{len(state['requests'])} 回")
    os.remove(target + ".part")
    state.update(cut=0, requests=[])
    kind, text = outcome(lambda: setup.download(url.replace("file.bin", "none.bin"), target, "モデル"))
    check("無い物（404）はやり直さない", kind == "failed" and steps.NETWORK_HINT not in text, text[:50])
finally:
    server.shutdown()

# 6. 済んだ印があっても、中身が欠けていればやり直す（中途半端な場所にかけ直しても直る）
k, m = setup.kimodo, setup.mb
check("何も無い場所は、どの物も「欠けている」", not any(setup.intact(key) for key in ("kimodo_src", "kimodo_env", "skeleton", "kimodo_model", "kimodo_ort",
                                                                                "mb_src", "mb_models", "mb_env", "mb_ort", "text_gguf", "llamacpp")))
check("物を置かない段は、いつも「そろっている」", setup.intact("kimodo_test") and setup.intact("mb_test") and setup.intact("text_remove"))
os.makedirs(os.path.join(k, "repo", "kimodo"))
open(os.path.join(k, "repo", "kimodo", "__init__.py"), "w").close()
check("本体のファイルがあれば「そろっている」", setup.intact("kimodo_src"))
for path, (_digest, size) in steps.pins.MOTIONBRICKS_LFS.items():
    full = os.path.join(m, *path.split("/"))
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as f:
        f.truncate(size)   # 中身は空のまま、大きさだけ合わせる（ディスクは使わない）
check("モデルは、全部が正しい大きさであれば「そろっている」", setup.intact("mb_models"))
short = os.path.join(m, *next(iter(steps.pins.MOTIONBRICKS_LFS)).split("/"))
with open(short, "r+b") as f:
    f.truncate(1000)
check("途中までしか無いモデルは「欠けている」", not setup.intact("mb_models"))
venv = os.path.join(k, ".venv", "Scripts")
os.makedirs(venv)
check("Python が無い環境は「欠けている」", not setup.intact("kimodo_env"))
shutil.copyfile(sys.executable, os.path.join(venv, "python.exe"))
check("読み込めない部品がある環境は「欠けている」", not setup._imports(sys.executable, "import no_such_module_ainakawari"))
check("読み込める環境は「そろっている」", setup._imports(sys.executable, "import json, os"))

# run の流れ: 作り物の段で（A・B は同じ組。B は A の後ろ）
ran_steps, broken = [], set()
fake = steps.Setup(os.path.join(tmp, "dest2"), log=logs.append, progress=shown.append, with_text=False)
os.makedirs(fake.dest)
fake.steps = lambda eol="lf": [("a", "g1", "A を入れる（約 1GB）", "v1", 0, lambda: ran_steps.append("a")),
                               ("b", "g1", "B を入れる", "v1", 0, lambda: ran_steps.append("b")),
                               ("c", "g2", "C を入れる", "v1", 0, lambda: ran_steps.append("c"))]
fake.intact = lambda key: key not in broken
fake.register = lambda: None
real_checks = steps.check_vc_runtime, steps.motion_correction_info, steps.find_uv
steps.check_vc_runtime = steps.motion_correction_info = lambda: None
steps.find_uv = lambda: "uv"
try:
    fake.run()
    check("初めては全部の段を回す", ran_steps == ["a", "b", "c"])
    ran_steps.clear()
    logs.clear()
    fake.run()
    check("全部そろっていれば何も回さず、「欠けている物はありませんでした」", ran_steps == [] and any("欠けている物はありませんでした" in line for line in logs))
    broken.add("a")
    logs.clear()
    fake.run()
    check("欠けた段と、その後ろの同じ組の段だけやり直す（別の組は飛ばす）", ran_steps == ["a", "b"]
          and any("中身が欠けているので、やり直します" in line and "A を入れる" in line for line in logs), str(ran_steps))
    broken.clear()
    ran_steps.clear()
    fake.run()
    check("直った後は、また何も回さない", ran_steps == [])
finally:
    steps.check_vc_runtime, steps.motion_correction_info, steps.find_uv = real_checks

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} OK")
sys.exit(0 if all(results) else 1)
