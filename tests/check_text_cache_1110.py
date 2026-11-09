"""11-10: Llama（プロンプトの読み取り）なしでも、サンプルの文なら作れるようにした変更を確かめる。窓の Python で回す。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_text_cache_1110.py [--real]

1. 文の整え方（text_keys.sanitize_text）が Kimodo の kimodo/sanitize.py と同じか（サンプルと崩れた文で）
2. 同梱の読み取り結果（mmd_ainakawari/text_cache）が、サンプルの全部と窓の最初の文の分だけそろっているか・形が (1, 4096) の float32 か
3. text_keys.missing: サンプル・空の文は無くてよい／知らない文は無い
4. Llama なしの時、生成の前（pipeline.run_kimodo）に知らない文で止まり、サンプルなら常駐へ頼む
5. セットアップの段: 入れる時だけ Llama の 2 段・外すと出ない・前に入れた物があれば「消す」段・選んだ方を覚える
6. 窓の文の欄（widgets.PromptRows）: 打てなくしても、サンプルは入る・後から足した行も打てない
7. --real の時: 本物の Kimodo で
   a. 常駐はサンプルの文と空の文では llama-server を起こさない・知らない文が来た時だけ起こす（結果は手元にためる）
   b. Llama が無い（場所のファイルが無い）時、サンプルの文は作れ、知らない文は案内付きで止まる（1 回だけの生成で）
"""
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from mmd_ainakawari import paths, pipeline, resident, samples, text_keys  # noqa: E402
from mmd_ainakawari.installer import steps  # noqa: E402

KIMODO_SANITIZE = r"F:\kimodo\repo\kimodo\sanitize.py"
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("OK " if ok else "NG ") + name + (f"（{detail}）" if detail else ""), flush=True)


# 1. 整え方
spec = importlib.util.spec_from_file_location("kimodo_sanitize", KIMODO_SANITIZE)
ks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ks)
odd = [" A person is    walking.", "someone go forward", "jump", "jumping!", "jumping)", "-go", "blocasdji  -----", "",
       "a person walks. then runs", "A person waves (happily)", "  ...  ", "a person jumps!! and lands?", "Ａ person 歩く"]
texts = text_keys.bundled_texts() + odd
diff = [t for t in texts if ks.sanitize_text(t) != text_keys.sanitize_text(t)]
check("文の整え方が Kimodo と同じ", not diff, f"{len(texts)} 文・違い {diff[:3]}")

# 2. 同梱の結果
want = {text_keys.key(text_keys.sanitize_text(t)) + ".npy" for t in text_keys.bundled_texts()}
have = {n for n in os.listdir(text_keys.BUNDLED_DIR) if n.endswith(".npy")}
check("同梱の結果がサンプルと最初の文の分だけある", want == have,
      f"要る {len(want)}・ある {len(have)}・足りない {len(want - have)}・余り {len(have - want)}")
bad = []
for n in have:
    a = np.load(os.path.join(text_keys.BUNDLED_DIR, n))
    if a.shape != (1, text_keys.DIM) or a.dtype != np.float32 or not np.isfinite(a).all() or not a.any():
        bad.append((n, a.shape, a.dtype))
check("同梱の結果の形が (1, 4096) の float32", not bad, str(bad[:2]))
first = samples.load()[0][1][0][1]
check("サンプルは同梱の場所から引ける", text_keys.find(first) and text_keys.find(first).startswith(text_keys.BUNDLED_DIR), first)

# 3. missing
nonce = f"A person hops in a circle {random.randint(100000, 999999)} times."
check("サンプル・空の文は「無い」に入らない", text_keys.missing([first, "", "  ", "a person walks forward"]) == [],
      "小文字で始めた文も整えれば同じ鍵")
check("知らない文は「無い」に入る", text_keys.missing([first, nonce, nonce]) == [nonce])

# 4. 生成の前に止める
orig_has, orig_call = paths.has_text_encoder, resident.call
calls = []
resident.call = lambda server, req, log=None: (calls.append(req) or ({"num_frames": 1}, "ok"))
pipeline.kimodo_server = lambda: None
paths.has_text_encoder = lambda: False
job = type("Job", (), {})()
work = tempfile.mkdtemp(prefix="ainakawari_text_")
try:
    job.request = {"segments": [{"prompt": first, "frames": 30}, {"prompt": nonce, "frames": 30}]}
    try:
        pipeline.run_kimodo(job, work)
        check("Llama なし・知らない文は止まる", False, "止まらなかった")
    except ValueError as e:
        check("Llama なし・知らない文は止まる", nonce in str(e) and not calls, str(e)[:60])
    job.request = {"segments": [{"prompt": first, "frames": 30}, {"prompt": "", "frames": 30}]}
    pipeline.run_kimodo(job, work)
    check("Llama なし・サンプルと空の文は常駐へ頼む", len(calls) == 1)
    paths.has_text_encoder = lambda: True
    job.request = {"segments": [{"prompt": nonce, "frames": 30}]}
    pipeline.run_kimodo(job, work)
    check("Llama ありなら知らない文も頼む", len(calls) == 2 and calls[-1]["text_cache_only"] is False)
    try:
        pipeline.run_kimodo(job, work, use_llama=False)
        check("「Llama を使う」を外すと知らない文は止まる", False, "止まらなかった")
    except ValueError as e:
        check("「Llama を使う」を外すと知らない文は止まる", "詳細の窓" in str(e) and len(calls) == 2, str(e)[:50])
    job.request = {"segments": [{"prompt": first, "frames": 30}]}
    pipeline.run_kimodo(job, work, use_llama=False)
    check("「Llama を使う」を外すとサンプルは頼み、常駐へ「読み取り結果だけ」と伝える",
          len(calls) == 3 and calls[-1]["text_cache_only"] is True)
finally:
    paths.has_text_encoder, resident.call = orig_has, orig_call
    import importlib
    importlib.reload(pipeline)

# 5. セットアップの段
dest = tempfile.mkdtemp(prefix="ainakawari_setup_")
keys = lambda s: [k for k, *_r in s.steps()]   # noqa: E731
s = steps.Setup(dest)
check("印の無い場所は Llama を入れる", s.with_text and {"text_gguf", "llamacpp"} <= set(keys(s)))
s = steps.Setup(dest, with_text=False)
check("外すと Llama の段が出ない", not {"text_gguf", "llamacpp", "text_remove"} & set(keys(s)), str(keys(s)))
os.makedirs(os.path.join(dest, "kimodo", "llamacpp"))
check("前に入れた物があると「消す」段が出る", "text_remove" in keys(steps.Setup(dest, with_text=False)))
check("試しの生成の版が入れる・入れないで変わる",
      dict((k, v) for k, _g, _t, v, *_r in steps.Setup(dest, with_text=False).steps())["kimodo_test"]
      != dict((k, v) for k, _g, _t, v, *_r in steps.Setup(dest, with_text=True).steps())["kimodo_test"])
s = steps.Setup(dest, with_text=False)
s.save_state({steps.WITH_TEXT: False})
check("選んだ方を覚える", steps.Setup(dest).with_text is False)
s.text_remove()
check("「消す」段で Llama のフォルダが消える", not os.path.isdir(os.path.join(dest, "kimodo", "llamacpp")))
check("消した後は「消す」段が出ない", "text_remove" not in keys(steps.Setup(dest, with_text=False)))
kind, pending = steps.Setup(dest, with_text=True).status()
check("後から入れると Llama の段が残りに入る", {"text_gguf", "llamacpp"} <= {k for k, _t, _g in pending}, kind)

# 6. 窓の文の欄
import tkinter as tk  # noqa: E402

from mmd_ainakawari.widgets import PromptRows  # noqa: E402

root = tk.Tk()
root.withdraw()
rows = PromptRows(root)
rows.load("A person walks forward.\n45: A person runs forward.")
rows.set_readonly(True)
rows.add_at(90)
states = [str(r["entry"].cget("state")) for r in rows.rows]
check("打てなくすると、足した行も含めて全部 readonly", states == ["readonly"] * 3, str(states))
rows.current = rows.rows[1]
rows.set_current("A person jumps up.")
check("打てなくてもサンプルは入る", rows.text().splitlines()[1] == "45: A person jumps up.", rows.text())
rows.set_readonly(False)
check("戻すと打てる", all(str(r["entry"].cget("state")) == "normal" for r in rows.rows))
root.destroy()


# 7. 本物
def llama_pids():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq llama-server.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, encoding="mbcs", errors="replace").stdout
    return [line.split(",")[1].strip('"') for line in out.splitlines() if line.startswith('"llama-server')]


if "--real" in sys.argv:
    server = pipeline.kimodo_server()
    resident.stop(pipeline.KIMODO_NAME, pipeline.KIMODO_PORT, wait=10)
    time.sleep(1)
    before = llama_pids()
    req = lambda prompt: {"prompt": prompt, "num_frames": 30, "steps": 10, "seed": 0}   # noqa: E731
    t = time.monotonic()
    _result, line = resident.call(server, req(first), log=lambda _l: None)
    check("常駐: サンプルの文は llama-server を起こさない", llama_pids() == before, f"{time.monotonic() - t:.1f} 秒・{line[:40]}")
    _result, line = resident.call(server, {**req(""), "segments": [{"prompt": "", "frames": 30}]}, log=lambda _l: None)
    check("常駐: 空の文も起こさない", llama_pids() == before, line[:40])
    t = time.monotonic()
    _result, line = resident.call(server, req(nonce), log=lambda _l: None)
    check("常駐: 知らない文の時だけ起こす", len(llama_pids()) > len(before), f"{time.monotonic() - t:.1f} 秒")
    check("常駐: 読み取った文は手元にためる", text_keys.find(nonce) and text_keys.find(nonce).startswith(text_keys.WORK_DIR))
    # 「Llama を使う」を外した時（11-10 マスター）
    t = time.monotonic()
    reply = resident.notify(pipeline.KIMODO_NAME, pipeline.KIMODO_PORT, {"release_text": True})
    time.sleep(1)
    check("常駐: 外すと llama-server だけ止まる", reply and reply.get("result") is True and llama_pids() == before,
          f"{time.monotonic() - t:.1f} 秒・{reply and reply.get('line')}")
    other = f"A person claps {random.randint(100000, 999999)} times."
    try:
        resident.call(server, {**req(other), "text_cache_only": True}, log=lambda _l: None)
        check("常駐: 外している間は知らない文で Llama を起こさず止まる", False, "止まらなかった")
    except RuntimeError as e:
        check("常駐: 外している間は知らない文で Llama を起こさず止まる", "外している" in str(e) and llama_pids() == before)
    _result, line = resident.call(server, {**req(first), "text_cache_only": True}, log=lambda _l: None)
    check("常駐: 外している間もサンプルは作れる（Kimodo は残っていて速い）", line.startswith("ok") and llama_pids() == before, line[:40])
    resident.stop(pipeline.KIMODO_NAME, pipeline.KIMODO_PORT, wait=10)

    # Llama が無い時（1 回だけの生成。場所のファイルを無い所にする）
    env = dict(pipeline.kimodo_env(), AINAKAWARI_LLAMA_SERVER=os.path.join(work, "none", "llama-server.exe"),
               AINAKAWARI_TEXT_GGUF=os.path.join(work, "none", "x.gguf"), LOCAL_CACHE="true", HF_HUB_OFFLINE="1")
    script = os.path.join(HERE, "tools", "kimodo_gen.py")
    for name, prompt, want_ok in (("サンプルの文は作れる", first, True),
                                  ("知らない文は案内付きで止まる", f"A person waves {random.randint(100000, 999999)} times.", False)):
        rq, out = os.path.join(work, "req.json"), os.path.join(work, "out.json")
        json.dump(req(prompt), open(rq, "w", encoding="utf-8"))
        if os.path.exists(out):
            os.remove(out)
        p = subprocess.run([paths.kimodo_python(), script, rq, out], env=env, cwd=paths.kimodo_dir(),
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if want_ok:
            check(f"Llama なし: {name}", p.returncode == 0 and os.path.exists(out), p.stdout.strip()[-60:] or p.stderr[-200:])
        else:
            check(f"Llama なし: {name}", p.returncode != 0 and "サンプルから選ぶ" in p.stderr and llama_pids() == before,
                  p.stderr.strip().splitlines()[-1][:80] if p.stderr.strip() else "")

print(f"\n{sum(results)}/{len(results)}", flush=True)
sys.exit(0 if all(results) else 1)
