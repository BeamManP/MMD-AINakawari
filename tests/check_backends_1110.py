"""11-10: 計算の方式（cuda・directml・cpu）を足した変更を確かめる。窓の Python で回す。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_backends_1110.py [--real]

1. paths.backend: 書いていなければ cuda・書いた方式を読む・環境変数が先・知らない方式は NotSetUp・場所の欄（abspath）と混ざらない
2. セットアップの段: ONNX Runtime を入れる段が、試しの生成のすぐ前にある（環境を作り直すと入れ直す並び）
3. 試す順: NVIDIA の GPU が見える時だけ cuda から・環境変数で決め打ち
4. try_backends: 失敗したら次へ・通った方式を覚える・全部だめなら最後の失敗・中止はそのまま出る
5. register: セットアップの場所の印から方式を写す・印の無い場所（0.2.x）は cuda
6. GPU の診断: directml・cpu・まだ決まっていなくて NVIDIA が無い時に「使えない」と言わない。CUDA なのに NVIDIA が無い時は止める
7. 常駐に方式が渡る（pipeline.kimodo_env）
8. --real の時: 本物の Kimodo・MotionBricks で（MMD は使わない）
   a. MotionBricks: directml・cpu の結果が cuda と見分けがつかない（回転の差 0.5 度未満）。directml と cpu は同じ（0.05 度未満）
   b. Kimodo: directml で作れて、キーに合う。2 回目は ONNX を書き出し直さない
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from mmd_ainakawari import gpu, paths, pipeline  # noqa: E402
from mmd_ainakawari.installer import steps  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("OK " if ok else "NG ") + name + (f"（{detail}）" if detail else ""), flush=True)


def raises(kind, fn):
    try:
        fn()
    except kind:
        return True
    except Exception:
        return False
    return False


REAL_PATHS = None
try:
    REAL_PATHS = paths.load()
except paths.NotSetUp:
    pass
tmp = tempfile.mkdtemp(prefix="ainakawari_backends_")
real_file, real_work = paths.PATHS_FILE, paths.WORK_DIR
env_before = os.environ.pop(paths.BACKEND_ENV, None)
try:
    # 1. paths.backend
    paths.WORK_DIR, paths.PATHS_FILE = tmp, os.path.join(tmp, "paths.json")
    check("書いていなければ cuda", paths.backend("kimodo") == "cuda" and paths.backend("motionbricks") == "cuda")
    paths.save_backend("kimodo", "directml")
    check("書いた方式を読む（もう片方はそのまま）", paths.backend("kimodo") == "directml" and paths.backend("motionbricks") == "cuda")
    paths.save(kimodo=os.path.join(tmp, "k"))
    data = json.load(open(paths.PATHS_FILE, encoding="utf-8"))
    check("場所を書いても方式は残る・方式は場所の形にならない", data.get("kimodo_backend") == "directml" and os.path.isabs(data["kimodo"]), str(data))
    os.environ[paths.BACKEND_ENV] = "cpu"
    check("環境変数が先", paths.backend("kimodo") == "cpu")
    os.environ[paths.BACKEND_ENV] = "vulkan"
    check("知らない方式は NotSetUp", raises(paths.NotSetUp, lambda: paths.backend("kimodo")))
    del os.environ[paths.BACKEND_ENV]
    check("知らない方式は書けない", raises(ValueError, lambda: paths.save_backend("kimodo", "vulkan")))
    check("paths.save に場所でない物は渡せない", raises(ValueError, lambda: paths.save(kimodo_backend="cpu")))

    # 2. セットアップの段
    dest = os.path.join(tmp, "dest")
    logs = []
    setup = steps.Setup(dest, log=logs.append, with_text=False)   # 入れる場所は一時フォルダの中（外には何も作らない）
    keys = [k for k, *_ in setup.steps()]
    check("ONNX Runtime の段が試しの生成のすぐ前（Kimodo）", keys.index("kimodo_ort") + 1 == keys.index("kimodo_test") > keys.index("kimodo_env"), str(keys))
    check("ONNX Runtime の段が試しの生成のすぐ前（MotionBricks）", keys.index("mb_ort") + 1 == keys.index("mb_test") > keys.index("mb_env"))
    check("部品表がある", os.path.isfile(steps.ORT_KIMODO) and os.path.isfile(steps.ORT_MOTIONBRICKS))
    for name, path in (("Kimodo", steps.ORT_KIMODO), ("MotionBricks", steps.ORT_MOTIONBRICKS)):
        text = open(path, encoding="utf-8").read()
        pins = [line for line in text.splitlines() if line and not line.startswith((" ", "#"))]
        check(f"部品表は版とハッシュつき（{name}）", all("==" in p for p in pins) and text.count("--hash=sha256:") >= len(pins)
              and any(p.startswith("onnxruntime-directml==") for p in pins) and any(p.startswith("onnx==") for p in pins), f"{len(pins)} 個")

    # 3. 試す順
    which = shutil.which
    try:
        steps.shutil.which = lambda name: "nvidia-smi.exe" if name == "nvidia-smi" else which(name)
        check("NVIDIA の GPU が見える時は cuda から", setup.backends_to_try() == ["cuda", "directml", "cpu"])
        steps.shutil.which = lambda name: None if name == "nvidia-smi" else which(name)
        check("見えない時は directml から", setup.backends_to_try() == ["directml", "cpu"])
    finally:
        steps.shutil.which = which
    os.environ[steps.BACKEND_ORDER_ENV] = "cpu, directml"
    check("環境変数で決め打ち", setup.backends_to_try() == ["cpu", "directml"])
    os.environ[steps.BACKEND_ORDER_ENV] = "cuda,opencl"
    check("知らない方式の決め打ちは止める", raises(steps.Failed, setup.backends_to_try))
    os.environ[steps.BACKEND_ORDER_ENV] = "cuda,directml,cpu"

    # 4. try_backends
    tried = []

    def attempt(backend, fail=("cuda",)):
        tried.append(backend)
        if backend in fail:
            raise steps.Failed(f"{backend} はだめ")

    got = setup.try_backends("kimodo", "Kimodo", attempt)
    check("失敗したら次へ・通った方式を返して覚える", got == "directml" and tried == ["cuda", "directml"]
          and setup.found == {steps.BACKEND_STATE["kimodo"]: "directml"}, f"{tried} {setup.found}")
    check("失敗の理由をログに残す", any("cuda はだめ" in line for line in logs))
    tried.clear()
    check("全部だめなら最後の失敗", raises(steps.Failed, lambda: setup.try_backends("motionbricks", "MotionBricks",
                                                                         lambda b: attempt(b, ("cuda", "directml", "cpu"))))
          and tried == ["cuda", "directml", "cpu"] and steps.BACKEND_STATE["motionbricks"] not in setup.found)

    def cancelled(_backend):
        raise steps.Cancelled()
    check("中止はそのまま出る（次の方式を試さない）", raises(steps.Cancelled, lambda: setup.try_backends("kimodo", "Kimodo", cancelled)))
    del os.environ[steps.BACKEND_ORDER_ENV]

    # 5. register
    os.makedirs(dest)
    for folder in (setup.kimodo, setup.mb):
        os.makedirs(os.path.join(folder, ".venv", "Scripts"))
        open(os.path.join(folder, ".venv", "Scripts", "python.exe"), "w").close()
    setup.save_state({steps.BACKEND_STATE["kimodo"]: "directml", steps.BACKEND_STATE["motionbricks"]: "cpu"})
    setup.register()
    check("register が場所の印から方式を写す", paths.backend("kimodo") == "directml" and paths.backend("motionbricks") == "cpu"
          and paths.kimodo_dir() == setup.kimodo)
    setup.save_state({"mb_test": "x"})   # 0.2.x までにセットアップした場所
    setup.register()
    check("印の無い場所は cuda", paths.backend("kimodo") == "cuda" and paths.backend("motionbricks") == "cuda")

    # 6. GPU の診断
    adapters = gpu._adapters()
    check("Windows が知っている GPU を読める", isinstance(adapters, list) and all(isinstance(n, str) and v >= 0 for n, v in adapters), str(adapters))
    real_gpu, real_adapters = gpu._gpu, gpu._adapters
    try:
        gpu._gpu = lambda: None   # NVIDIA の GPU が無い PC
        gpu._adapters = lambda: [("AMD Radeon RX 7800 XT", 16.0)]
        paths.save_backend("kimodo", "directml")
        d = gpu.diagnose()
        check("directml: 使える・GPU の名前が出る", d.usable and d.ok and d.gpu.startswith("AMD") and d.backend == "directml" and "DirectML" in d.note, d.note)
        paths.save_backend("kimodo", "cpu")
        d = gpu.diagnose()
        check("cpu: 使える・時間がかかると言う", d.usable and d.backend == "cpu" and "時間がかかります" in d.note, d.note)
        paths.save_backend("kimodo", "cuda")
        d = gpu.diagnose()
        check("cuda なのに NVIDIA が無い: 止めて、セットアップへ案内する", not d.usable and "セットアップ" in d.note, d.note)
        os.remove(paths.PATHS_FILE)   # まだセットアップしていない
        d = gpu.diagnose()
        check("まだ決まっていなくて NVIDIA が無い: 止めない", d.usable and d.gpu.startswith("AMD") and "DirectML" in d.note, d.note)
        gpu._adapters = lambda: []
        d = gpu.diagnose()
        check("GPU が何も無い: 止めない（GPU なしで作る）", d.usable and d.backend == "cpu", d.note)
        gpu._adapters = lambda: [("Intel(R) UHD Graphics 770", 0.0)]
        check("VRAM が分からない GPU は VRAM を書かない", "VRAM" not in gpu.diagnose().summary(), gpu.diagnose().summary())
    finally:
        gpu._gpu, gpu._adapters = real_gpu, real_adapters

    # 6b. GPU を替えたら、試しの生成（方式の選び直し）だけやり直しになる
    try:
        gpu._adapters = lambda: [("NVIDIA GeForce RTX 3090", 24.0)]
        tag_a = steps.gpu_tag()
        versions_a = {k: v for k, _g, _t, v, _gb, _fn in setup.steps()}
        gpu._adapters = lambda: [("AMD Radeon RX 7800 XT", 16.0)]
        tag_b = steps.gpu_tag()
        versions_b = {k: v for k, _g, _t, v, _gb, _fn in setup.steps()}
        changed = sorted(k for k in versions_a if versions_a[k] != versions_b[k])
        check("GPU を替えると、試しの生成の段だけ版が変わる", tag_a != tag_b and changed == ["kimodo_test", "mb_test"], f"{tag_a} → {tag_b}・{changed}")
        gpu._adapters = lambda: []
        check("GPU を読めない時の印は決まった字", steps.gpu_tag() == "unknown")
    finally:
        gpu._adapters = real_adapters

    # 7. 常駐に渡す
    setup.register()
    paths.save_backend("kimodo", "directml")
    env = pipeline.kimodo_env()
    check("常駐の Kimodo に方式と ONNX の置き場が渡る", env.get("AINAKAWARI_BACKEND") == "directml"
          and env.get("AINAKAWARI_ORT_CACHE") == os.path.join(setup.kimodo, "ort_cache"), env.get("AINAKAWARI_ORT_CACHE", ""))
finally:
    paths.PATHS_FILE, paths.WORK_DIR = real_file, real_work
    os.environ.pop(steps.BACKEND_ORDER_ENV, None)
    os.environ.pop(paths.BACKEND_ENV, None)
    if env_before is not None:
        os.environ[paths.BACKEND_ENV] = env_before


def run(python, script, args, cwd, **extra):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", **extra)
    out = subprocess.run([python, os.path.join(HERE, "tools", script), *args], cwd=cwd, env=env, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.returncode, out.stdout + out.stderr


def angles(a, b):
    """2 つの結果の、関節の回転の差（度）の最大。"""
    qa = np.array(a["local_rot"]).reshape(a["num_frames"], -1, 4)
    qb = np.array(b["local_rot"]).reshape(b["num_frames"], -1, 4)
    return float(np.degrees(2 * np.arccos(np.abs((qa * qb).sum(-1)).clip(0, 1))).max())


if "--real" in sys.argv:
    if not REAL_PATHS or not paths.motionbricks_dir():
        check("--real: Kimodo と MotionBricks の場所が決まっている", False)
    else:
        soma = json.load(open(paths.soma_json(), encoding="utf-8"))
        pose = {"root": soma["neutral_joints"][soma["root_idx"]], "local_rot": [0.0, 0.0, 0.0, 1.0] * len(soma["names"])}
        bent = dict(pose, local_rot=list(pose["local_rot"]))
        elbow = soma["names"].index("LeftForeArm") * 4
        bent["local_rot"][elbow:elbow + 4] = [0.0, 0.5, 0.0, 0.8660254]   # ひじを 60 度曲げる
        req = os.path.join(tmp, "mb_request.json")
        json.dump({"skeleton": paths.soma_json(), "context": [pose] * 4,
                   "targets": [{"poses": [bent], "frames": 30, "num_poses_to_use": 1}, {"poses": [pose], "frames": 24, "num_poses_to_use": 1}]},
                  open(req, "w", encoding="utf-8"))
        got = {}
        for backend in ("cuda", "directml", "cpu"):
            out = os.path.join(tmp, f"mb_{backend}.json")
            rc, text = run(paths.motionbricks_python(), "mb_gen.py", [req, out], paths.motionbricks_dir(), AINAKAWARI_BACKEND=backend)
            ok = rc == 0 and os.path.isfile(out)
            check(f"--real MotionBricks {backend}: 作れる", ok, "" if ok else text[-300:])
            if ok:
                got[backend] = json.load(open(out, encoding="utf-8"))
        # cuda（TensorRT）は速さのために精度を落とした掛け算（TF32）を使うので、ONNX Runtime とは 0.03〜0.11 度ずれる（11-10 に測った）。
        # 目で分かる差（1 度〜）より十分小さい 0.5 度を上限にする。ONNX Runtime どうし（directml と cpu）はもっと厳しく見る
        for backend in ("directml", "cpu"):
            if "cuda" in got and backend in got:
                diff = angles(got["cuda"], got[backend])
                check(f"--real MotionBricks {backend}: cuda と見分けがつかない", got[backend]["num_frames"] == got["cuda"]["num_frames"] and diff < 0.5,
                      f"回転の差 最大 {diff:.4f} 度")
        if "directml" in got and "cpu" in got:
            diff = angles(got["directml"], got["cpu"])
            check("--real MotionBricks: directml と cpu は同じ", diff < 0.05, f"回転の差 最大 {diff:.4f} 度")

        key = {"frame": 0, "root": pose["root"], "local_rot": pose["local_rot"]}
        key2 = {"frame": 40, "root": pose["root"], "local_rot": bent["local_rot"]}
        kreq = os.path.join(tmp, "kimodo_request.json")
        json.dump({"prompt": "A person walks forward.", "num_frames": 41, "seed": 3, "keys": [key, key2], "text_cache_only": True},
                  open(kreq, "w", encoding="utf-8"))
        cache = os.path.join(tmp, "ort_cache")
        base = dict(HF_HUB_CACHE=paths.kimodo_hf_cache(), LOCAL_CACHE="true", HF_HUB_OFFLINE="1", AINAKAWARI_ORT_CACHE=cache,
                    AINAKAWARI_BACKEND="directml")
        for turn in (1, 2):
            out = os.path.join(tmp, f"kimodo_{turn}.json")
            rc, text = run(paths.kimodo_python(), "kimodo_gen.py", [kreq, out], paths.kimodo_dir(), **base)
            ok = rc == 0 and os.path.isfile(out)
            check(f"--real Kimodo directml（{turn} 回目）: 作れる", ok, "" if ok else text[-400:])
            if ok:
                res = json.load(open(out, encoding="utf-8"))
                check(f"--real Kimodo directml（{turn} 回目）: キーに合う", max(res["key_max_error_m"]) < 0.01, str(res["key_max_error_m"]))
                check(f"--real Kimodo directml（{turn} 回目）: ONNX は{'書き出す' if turn == 1 else '書き出し直さない'}",
                      ("onnx exported" in text) == (turn == 1))

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{sum(results)}/{len(results)} OK")
sys.exit(0 if all(results) else 1)
