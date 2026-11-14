"""11-14: 外からの操作の口（mmd_ainakawari/control.py）を確かめる。MMD も Kimodo も使わない。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_control_1114.py

相手は mmd-mcp の本物の部品（mmd_mcp.ainakawari.call）。口は試し用の名前で開く（動いている窓の口とぶつからない）。
1. 依頼 → 設定（settings_from）: 窓の App._settings と同じ決まりか・断る時の code
2. 依頼の記録（Jobs・commit・finish・public）
3. 口: 本物のパイプで 1 往復・断りの code がそのまま届く・JSON でない物・大きすぎる物・黙ったままの相手の後も次の客に答える・続けて 30 回
4. tk が取りに来ない時は ui_busy で断り、後から tk が来ても実行しない／取った後に答えが遅い時は ui_timeout
5. handle: protocol 違い・知らない項目・知らない op・相手が見つからない・生成／中断／元に戻すが窓の関数に届く・窓の中の例外は internal
"""
import json
import os
import queue
import sys
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
INSTANCE = f"check{os.getpid()}"
os.environ["AINAKAWARI_INSTANCE"] = INSTANCE   # mmd_mcp.ainakawari が、試し用の口の名前を引く

import pywintypes  # noqa: E402
import win32file  # noqa: E402
import win32pipe  # noqa: E402

from mmd_mcp import ainakawari as client  # noqa: E402
from mmd_ainakawari import control, thin  # noqa: E402
from mmd_ainakawari.app import DEFAULTS  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("OK " if ok else "NG ") + name + (f"（{detail}）" if detail else ""), flush=True)


def refused(fn):
    try:
        fn()
    except control.Refused as e:
        return e.code
    return None


# ---------------- 1. 依頼 → 設定 ----------------
check("決まった既定値は、窓の最初の設定と同じ", control.REMOTE_DEFAULTS == {k: DEFAULTS[k] for k in control.REMOTE_DEFAULTS}
      and not set(control.REMOTE_DEFAULTS) & set(control.MACHINE_KEYS)
      and set(control.REMOTE_DEFAULTS) | set(control.MACHINE_KEYS) == set(DEFAULTS) - {"tab", "mode", "range_mode", "length", "prompt"})
# 窓で試した作風の設定（seed・効き・全ての親に載せるなど）と、この PC に合わせた設定（Llama・間引き）
cfg = dict(DEFAULTS, steps=40, seed=7, cfg_text=8.0, cfg_key=5.0, post_processing=False, stop_at_last_key=False, smooth_stop=False,
           key_stop=True, wrist_lerp=True, root_move=True, root_turn=True, use_llama=False, thin=3, thin_nakawari=1)
keys = lambda: [10, 20, 55]   # noqa: E731


def make(req, selected=keys, kimodo=True, mb=True):
    return control.settings_from(req, cfg, selected, kimodo_ready=kimodo, motionbricks_ready=mb)


s, summary = make({"prompt": "A person walks."})
check("既定は Kimodo・埋める・選んだキーの間", (s.engine, s.use_keys, s.range_start, s.range_end, s.length, s.extend) ==
      ("kimodo", True, 10, 55, None, None), str(summary))
check("省いた項目: 作風の物は窓の設定を引き継がず、決まった既定値", (s.steps, s.seed, s.cfg_text, s.cfg_key, s.post_processing,
      s.stop_at_last_key, s.smooth_stop, s.key_stop, s.wrist_lerp, s.root_move, s.root_turn) ==
      (100, -1, 2.0, 2.0, True, True, True, False, False, False, False), str(summary))
check("省いた項目: この PC に合わせた物（Llama・間引き）は窓の設定", (s.use_llama, s.thin) == (False, 3))
check("status に返す既定値も同じ", control.defaults_for(cfg) == {**control.REMOTE_DEFAULTS, "use_llama": False, "thin": 3, "thin_nakawari": 1})
s, _ = make({"prompt": "x", "steps": 20, "seed": -1, "use_llama": True, "thin": 0, "root_move": False, "cfg_text": 3,
             "stop_at_last_key": False, "smooth_stop": False})
check("付けた項目はそれを使う", (s.steps, s.seed, s.use_llama, s.thin, s.root_move, s.cfg_text, s.stop_at_last_key, s.smooth_stop) ==
      (20, -1, True, 0, False, 3.0, False, False))
s, _ = make({"prompt": "x", "range": {"start": 30, "end": 90}})
check("範囲をフレームで指定", (s.range_start, s.range_end) == (30, 90))
s, _ = make({"prompt": "x", "range": "all", "mode": "fresh", "length": 120})
check("プロンプトだけで作る（全部・長さ）", (s.range_start, s.length, s.use_keys, s.use_center, s.stop_at_last_key) ==
      (None, 120, False, False, False))
s, _ = make({"prompt": "x", "mode": "fresh", "length": 120})
check("プロンプトだけで作る・範囲がある時は長さを使わない", (s.range_start, s.range_end, s.length) == (10, 55, None))
s, _ = make({"prompt": "x", "mode": "extend", "length": 45})
check("続きを足す", (s.extend, s.length, s.range_end) == (45, None, 55))
s, _ = make({"prompt": "x", "mode": "center"})
check("センターに合わせて作る", (s.use_center, s.use_keys) == (True, False))
s, summary = make({"engine": "motionbricks", "prompt": "ignored", "mode": "fresh"})
check("中割りはプロンプト・やりたいことを使わない", (s.engine, s.prompt, s.thin, summary["mode"]) == ("motionbricks", "", 1, "fill"))
s, _ = make({"prompt": "x"}, mb=False)
check("MotionBricks が無ければ、なめらかに止まるは使わない", s.smooth_stop is False)

cases = [
    ("プロンプトが無い", {}, {}, "bad_request"),
    ("プロンプトが空", {"prompt": "  "}, {}, "bad_request"),
    ("知らない engine", {"prompt": "x", "engine": "sora"}, {}, "bad_request"),
    ("知らない mode", {"prompt": "x", "mode": "dance"}, {}, "bad_request"),
    ("steps が文字", {"prompt": "x", "steps": "20"}, {}, "bad_request"),
    ("steps が true", {"prompt": "x", "steps": True}, {}, "bad_request"),
    ("use_llama が 1", {"prompt": "x", "use_llama": 1}, {}, "bad_request"),
    ("thin が範囲の外", {"prompt": "x", "thin": len(thin.LEVELS)}, {}, "bad_request"),
    ("範囲が逆", {"prompt": "x", "range": {"start": 50, "end": 50}}, {}, "bad_request"),
    ("範囲の形が違う", {"prompt": "x", "range": [1, 2]}, {}, "bad_request"),
    ("範囲の項目が足りない", {"prompt": "x", "range": {"start": 1}}, {}, "bad_request"),
    ("続きを足すのに長さが無い", {"prompt": "x", "mode": "extend"}, {}, "length_required"),
    ("全部でプロンプトだけなのに長さが無い", {"prompt": "x", "mode": "fresh", "range": "all"}, {}, "length_required"),
    ("キーを 1 つしか選んでいない", {"prompt": "x"}, {"selected": lambda: [10]}, "range_required"),
    ("選んだキーを読めない（None）", {"prompt": "x"}, {"selected": lambda: None}, "range_required"),
    ("選んだキーを読めない（例外）", {"prompt": "x"}, {"selected": lambda: 1 / 0}, "keys_unreadable"),
    ("Kimodo が入っていない", {"prompt": "x"}, {"kimodo": False}, "not_set_up"),
    ("MotionBricks が入っていない", {"engine": "motionbricks"}, {"mb": False}, "not_set_up"),
]
for name, req, kw, code in cases:
    got = refused(lambda: make(req, **kw))
    check(f"断る: {name} → {code}", got == code, f"実際 {got}")

# ---------------- 2. 依頼の記録 ----------------
jobs = control.Jobs()
a = jobs.new("generate", 111, {"prompt": "x"})
b = jobs.new("undo", 222)
c = jobs.new("generate", 111)
check("番号は重ならない・一番新しい依頼を引ける", len({a["id"], b["id"], c["id"]}) == 3 and jobs.latest(111) is c
      and jobs.latest(222) is b and jobs.latest(333) is None and jobs.get(a["id"]) is a)
control.commit(a)
check("書き戻しが始まると committing", (a["state"], a["committed"]) == ("committing", True))


control.finish(a, "done", "できました", {"job": object(), "span": {"range": [10, 55]}, "model": "m.pmx", "output": "o.vmd",
                                      "backup": "b.vmd", "root_written": True})
p = control.public(a)
check("終わった依頼の中身（JSON にできる）", p["state"] == "done" and p["result"] == {
    "span": {"range": [10, 55]}, "model": "m.pmx", "output": "o.vmd", "backup": "b.vmd", "root_written": True}
      and p["error"] is None and json.dumps(p), str(p["result"]))
control.finish(c, "failed", "失敗: 何か")
check("失敗は理由が error に入る", control.public(c)["error"] == "失敗: 何か" and control.public(c)["result"] is None)
for _ in range(control.JOBS_KEPT + 5):
    jobs.new("generate", 1)
check("古い記録は捨てる", jobs.get(a["id"]) is None and len(jobs._jobs) == control.JOBS_KEPT)


# ---------------- 3〜5. 口 ----------------
class FakeApp:
    lang = "ja"

    def __init__(self, hub, hwnd):
        self.hub, self.mmd = hub, type("Host", (), {"hwnd": hwnd, "kind": "mmd"})()
        self.calls = []

    def remote_state(self):
        return {"busy": False, "host": {"hwnd": self.mmd.hwnd}}

    def remote_generate(self, req):
        self.calls.append(("generate", req.get("prompt")))
        if req.get("prompt") == "boom":
            raise ZeroDivisionError("中で落ちた")
        if req.get("prompt") == "busy":
            raise control.Refused("busy", "途中です", running_job="abc")
        return self.hub.jobs.new("generate", self.mmd.hwnd, {"prompt": req.get("prompt")})

    def remote_cancel(self, job_id=None):
        self.calls.append(("cancel", job_id))
        return self.hub.jobs.latest(self.mmd.hwnd)

    def remote_undo(self):
        self.calls.append(("undo", None))
        return self.hub.jobs.new("undo", self.mmd.hwnd)


class FakeHub:
    def __init__(self):
        self.jobs = control.Jobs()
        self.apps = {}

    def control_app(self, hwnd):
        if hwnd != 4242:
            raise control.Refused("host_not_found", "見つかりません")
        return self.apps.setdefault(hwnd, FakeApp(self, hwnd))


hub = FakeHub()
slots = queue.Queue()
ui_on = threading.Event()
ui_on.set()
ui_delay = [0.0]


def ui():   # tk のスレッドの代わり（Hub._poll と同じ受け方）
    while True:
        slot = slots.get()
        if slot is None:
            return
        ui_on.wait()
        if slot.take():
            time.sleep(ui_delay[0])
            slot.answer(control.handle(hub, slot.request))


threading.Thread(target=ui, daemon=True).start()
server = control.Server(control.pipe_name(INSTANCE), slots.put, take_wait=0.6, reply_wait=0.8)
server.start()
check("口の名前が mmd-mcp の引く名前と同じ", server.name == client.pipe_name(), server.name)


def code_of(fn):
    try:
        fn()
    except client.AINakawariError as e:
        return e.code
    return None


r = client.call({"op": "hello"})
check("hello の 1 往復", r["ok"] and r["protocol"] == control.PROTOCOL and r["name"] == "AINakawari", str(r))
r = client.call({"op": "status", "hwnd": 4242})
check("status（依頼が無い時は job が null）", r["ok"] and r["job"] is None and r["busy"] is False and r["version"])
r = client.call({"op": "generate", "hwnd": 4242, "prompt": "A person walks."})
job_id = r["job"]["id"]
check("generate は番号をすぐ返す", r["job"]["state"] == "running" and hub.apps[4242].calls[-1] == ("generate", "A person walks."))
r = client.call({"op": "status", "hwnd": 4242, "job_id": job_id})
check("status を番号で引く", r["job"]["id"] == job_id and r["job"]["request"] == {"prompt": "A person walks."})
check("知らない番号 → unknown_job", code_of(lambda: client.call({"op": "status", "hwnd": 4242, "job_id": "nope"})) == "unknown_job")
check("ほかの MMD の番号 → unknown_job", (hub.jobs.new("generate", 9) and None) or code_of(
    lambda: client.call({"op": "status", "hwnd": 4242, "job_id": hub.jobs.latest(9)["id"]})) == "unknown_job")
r = client.call({"op": "cancel", "hwnd": 4242, "job_id": job_id})
check("cancel が窓に届く", hub.apps[4242].calls[-1] == ("cancel", job_id) and r["job"]["id"] == job_id)
r = client.call({"op": "undo", "hwnd": 4242})
check("undo が窓に届く", hub.apps[4242].calls[-1] == ("undo", None) and r["job"]["kind"] == "undo")
try:
    client.call({"op": "generate", "hwnd": 4242, "prompt": "busy"})
    extra = None
except client.AINakawariError as e:
    extra = (e.code, e.reply.get("running_job"))
check("窓が断った code と添え物がそのまま届く", extra == ("busy", "abc"), str(extra))
check("窓の中の例外 → internal（口は落ちない）", code_of(lambda: client.call({"op": "generate", "hwnd": 4242, "prompt": "boom"})) == "internal")
check("相手が見つからない → host_not_found", code_of(lambda: client.call({"op": "status", "hwnd": 1})) == "host_not_found")
check("hwnd が文字 → bad_request", code_of(lambda: client.call({"op": "status", "hwnd": "4242"})) == "bad_request")
check("知らない op → bad_request", code_of(lambda: client.call({"op": "dance", "hwnd": 4242})) == "bad_request")
check("知らない項目 → bad_request", code_of(lambda: client.call({"op": "status", "hwnd": 4242, "promt": "x"})) == "bad_request")
check("protocol 違い → protocol_mismatch", code_of(lambda: client.call({"op": "hello", "protocol": 99})) == "protocol_mismatch")


def raw(payload, read=True):
    """部品を通さずに口へ生の字を送る（None なら何も送らずに閉じる）。"""
    h = win32file.CreateFile(server.name, win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None, win32file.OPEN_EXISTING, 0, None)
    try:
        win32pipe.SetNamedPipeHandleState(h, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        if payload is None:
            return None
        win32file.WriteFile(h, payload)
        return json.loads(win32file.ReadFile(h, control.MAX_BYTES)[1].decode("utf-8")) if read else None
    finally:
        h.Close()


check("JSON でない物 → bad_request", raw(b"\xff\xfenot json").get("code") == "bad_request")
check("JSON だがオブジェクトでない → bad_request", raw(b"[1, 2]").get("code") == "bad_request")
try:
    raw(b"x" * (control.MAX_BYTES + 100))
    big = "返事が来た"
except pywintypes.error as e:
    big = f"切られた（{e.winerror}）"
check("大きすぎる 1 通は切る", big.startswith("切られた"), big)
raw(None)
t0 = time.time()
r = client.call({"op": "hello"})
check("何も送らずに閉じた相手の後も、次の客に答える", r["ok"], f"{time.time() - t0:.2f} 秒")
h = win32file.CreateFile(server.name, win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None, win32file.OPEN_EXISTING, 0, None)
t0 = time.time()
r = client.call({"op": "hello"}, timeout=10)   # 黙ったままつないでいる相手がいても、期限で切って次へ
h.Close()
check("黙ったままの相手がいても、次の客に答える", r["ok"] and time.time() - t0 < control.READ_WAIT + 2, f"{time.time() - t0:.2f} 秒")
t0 = time.time()
ok = all(client.call({"op": "hello"})["ok"] for _ in range(30))
check("続けて 30 回", ok, f"{time.time() - t0:.2f} 秒")
got = []
threads = [threading.Thread(target=lambda: got.append(client.call({"op": "status", "hwnd": 4242})["ok"])) for _ in range(8)]
[t.start() for t in threads]
[t.join() for t in threads]
check("同時に 8 つ", got == [True] * 8, str(got))

# 4. tk が取りに来ない・答えが遅い
before = len(hub.apps[4242].calls)
ui_on.clear()
t0 = time.time()
got = code_of(lambda: client.call({"op": "generate", "hwnd": 4242, "prompt": "late"}))
waited = time.time() - t0
ui_on.set()
time.sleep(0.5)
check("tk が取りに来ない → ui_busy で断る", got == "ui_busy" and waited < 2, f"{got}・{waited:.2f} 秒")
check("諦めた依頼を、後から tk が実行しない", len(hub.apps[4242].calls) == before, str(hub.apps[4242].calls[before:]))
ui_delay[0] = 1.5
got = code_of(lambda: client.call({"op": "status", "hwnd": 4242}))
ui_delay[0] = 0.0
time.sleep(1.0)
check("取った後に答えが遅い → ui_timeout", got == "ui_timeout", str(got))
check("遅れの後も、次の客に答える", client.call({"op": "hello"})["ok"])

# 口を閉じる・同じ名前の 2 つ目は作れない
try:
    second = control.Server(server.name, slots.put)
    second.start()
    dup = "作れた"
    second.stop()
except pywintypes.error as e:
    dup = f"断られた（{e.winerror}）"
check("同じ名前の口は 2 つ作れない", dup.startswith("断られた"), dup)
server.stop()
slots.put(None)
check("口を閉じた後 → not_running（窓の目印も無い）", code_of(lambda: client.call({"op": "hello"})) == "not_running")

print("---")
print(f"{sum(results)}/{len(results)} OK")
sys.exit(0 if all(results) else 1)
