"""Kimodo の橋渡し（Kimodo の Python で動かす）。依頼（プロンプト・コマ数・キー）→ SOMA 30 関節の結果。

    F:\\kimodo\\.venv\\Scripts\\python.exe tools\\kimodo_gen.py 依頼.json 結果.json     1 回だけ（毎回モデルを読み込む）
    F:\\kimodo\\.venv\\Scripts\\python.exe tools\\kimodo_gen.py --serve 9553             常駐

座標はすべて Kimodo の座標（Y が上・+Z が前・+X が体の左・メートル）。
回転は標準 T ポーズ基準のローカル回転（四元数 x,y,z,w を関節順に平らに並べる）。
元は F:\\kimodo\\tools\\unity_gen.py（Unity の KimodoLink 用に書いたもの）。11-04 にここへ移し、常駐できるようにした。
1 回の生成は 3 秒ほどだが、torch と Kimodo のモデルの読み込みに 25 秒かかっていた。

文の読み取り（LLM2Vec・Llama-3-8B）は、GGUF Q8_0 を llama.cpp の llama-server（CPU・メインメモリ約 7.6GB）で行う（tools/gguf_text.py）。
場所は環境変数で渡す: AINAKAWARI_LLAMA_SERVER（llama-server.exe）・AINAKAWARI_TEXT_GGUF（.gguf）・AINAKAWARI_LOG_DIR（記録）。
11-07 までは低負荷（bf16 の Llama を CPU・約 15GB）と高速（GPU のサーバー・VRAM 約 16.8GB）の 2 つのモードがあったが、
GGUF で読み取りが 1 文 0.5 秒ほどになり、高速モードの意味が無くなったのでまとめた。
読み取り結果は同梱（サンプルの文）と work/text_cache/gguf から先に引き、どちらにも無い文が来た時だけ llama-server を起こす
（tools/gguf_text.py の CachedText・11-10）。Llama を入れていない（セットアップで外した）時は、無い文でエラーにする。
AINAKAWARI_TEXT_NO_CACHE=1 の時は読み取り結果を使わず必ず Llama で読む（セットアップの試し）。
"""
import json
import os
import sys
import threading
import time
import traceback

import numpy as np
from scipy.spatial.transform import Rotation

J = 30
HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HOME not in sys.path:   # mmd_ainakawari.text_keys（読み取り結果の置き場と鍵）を読むため
    sys.path.insert(0, HOME)


class RootYConstraintSet:
    """腰の高さだけを合わせる制約（Kimodo の標準には無いので自前）。

    モデルの条件（smooth_root_pos の y）には入るが、Kimodo の後処理は知らない種類を読み飛ばすので、最後の合わせ込みは掛からない。
    """

    name = "root-y"

    def __init__(self, skeleton, frame_indices, root_y_pos):
        self.skeleton = skeleton
        self.frame_indices = frame_indices
        self.root_y_pos = root_y_pos

    def update_constraints(self, data_dict, index_dict):
        data_dict["root_y_pos"].append(self.root_y_pos)
        index_dict["root_y_pos"].append(self.frame_indices)

    def crop_move(self, start, end):
        mask = (self.frame_indices >= start) & (self.frame_indices < end)
        return RootYConstraintSet(self.skeleton, self.frame_indices[mask] - start, self.root_y_pos[mask])

    def to(self, device=None, dtype=None):
        if device is not None:
            self.root_y_pos = self.root_y_pos.to(device)
            self.frame_indices = self.frame_indices.to(device)
        if dtype is not None:
            self.root_y_pos = self.root_y_pos.to(dtype)
        return self


_GUARDED = {}


def _skip_when_empty(c):
    """区間ごとのプロンプトで切り出した制約が 0 フレームになっても落ちないようにする。

    Kimodo は区間ごとに constraint.crop_move で制約を切り出すが、空のまま条件を書くと reshape で落ちる。
    元の種類を引き継いだ子クラスに差し替えるので、後処理の isinstance の判定はそのまま効く。
    """
    base = type(c)
    if base.__name__.startswith("SkipEmpty"):
        return c
    if base not in _GUARDED:
        def update_constraints(self, data_dict, index_dict, _base=base):
            if len(self.frame_indices) == 0:
                return
            _base.update_constraints(self, data_dict, index_dict)

        def crop_move(self, start, end, _base=base):
            return _skip_when_empty(_base.crop_move(self, start, end))

        _GUARDED[base] = type("SkipEmpty" + base.__name__, (base,), {"update_constraints": update_constraints, "crop_move": crop_move})
    c.__class__ = _GUARDED[base]
    return c


MODEL = "kimodo-soma-rp"
# 計算の方式（mmd_ainakawari/paths.py の説明。無ければ cuda）。load() が見る
BACKEND = os.environ.get("AINAKAWARI_BACKEND") or "cuda"
if BACKEND not in ("cuda", "directml", "cpu"):
    raise SystemExit(f"AINAKAWARI_BACKEND={BACKEND!r} は cuda / directml / cpu のどれかにしてください")
AUTHKEY = b"AINakawari.resident.v1"   # mmd_ainakawari/resident.py と同じ
WORK = os.path.join(HOME, "work")
IDLE_SECONDS = 5 * 60                # 常駐で、これだけ頼まれなければ終わる（作り直しを続ける間は速く、手を止めたら約 8GB を空ける。11-08 マスター）


def start_llama():
    """文の読み取り（tools/gguf_text.py の LlamaServerEncoder）を起こす。読み取り結果の無い文が来た時に 1 回だけ呼ばれる。
    場所は環境変数から。Llama を入れていなければ（ファイルが無ければ）NoTextEncoder。"""
    from gguf_text import LlamaServerEncoder, NoTextEncoder

    server, gguf = os.environ.get("AINAKAWARI_LLAMA_SERVER"), os.environ.get("AINAKAWARI_TEXT_GGUF")
    if not (server and gguf and os.path.isfile(server) and os.path.isfile(gguf)):
        raise NoTextEncoder("このプロンプトは読み取り結果がありません。プロンプトの読み取り（Llama 3）を入れていないので、"
                            "「サンプルから選ぶ」の文を使ってください（自由に書くには、セットアップで入れてください）")
    log = os.path.join(os.environ.get("AINAKAWARI_LOG_DIR") or WORK, "llama_server.log")
    enc = LlamaServerEncoder(server, gguf, log)
    print(f"text encoder ready (llama-server port={enc.port} load={enc.seconds_load:.1f}s)", flush=True)
    return enc


def load(name=MODEL):
    """Kimodo のモデルを読む。文の読み取りは CachedText（llama-server はまだ起こさない）。

    計算の方式（BACKEND）が cuda なら今までどおり GPU の PyTorch。directml なら CPU で読んでから、重い 2 つの Transformer だけを
    ONNX Runtime の DirectML に差し替える（tools/kimodo_ort.py。書き出した ONNX は AINAKAWARI_ORT_CACHE か <今の場所>\\ort_cache）。
    cpu は PyTorch の CPU のまま（67 フレームで約 40 秒・300 フレームで 2〜4 分。11-10・i7-12700F）。
    """
    from gguf_text import CachedText
    from kimodo import load_model

    use_cache = os.environ.get("AINAKAWARI_TEXT_NO_CACHE") != "1"
    device = "cuda" if BACKEND == "cuda" else "cpu"
    model = load_model(name, device=device, text_encoder=CachedText(start_llama, device=device, use_cache=use_cache))
    if model.skeleton.nbjoints != J:
        raise RuntimeError(f"skeleton has {model.skeleton.nbjoints} joints, expected {J}")
    if BACKEND == "directml":
        import kimodo_ort
        kimodo_ort.install(model, "directml", os.environ.get("AINAKAWARI_ORT_CACHE") or os.path.join(os.getcwd(), "ort_cache"),
                           log=lambda line: print(line, flush=True))
    return model


def generate(model, req, t_load=0.0):
    """依頼 → (結果, 1 行のまとめ)。"""
    import torch
    from kimodo.constraints import load_constraints_lst
    from kimodo.tools import seed_everything

    if req.get("model", MODEL) != MODEL:
        raise ValueError(f"モデル {req['model']} には対応していません（{MODEL} だけ）")
    # 窓の「プロンプトの読み取り（Llama 3）を使う」を外した時: 読み取り結果のある文だけで作り、起きている llama-server は止める
    encoder = model.text_encoder
    if hasattr(encoder, "allow_llama"):
        encoder.allow_llama = not req.get("text_cache_only")
        if req.get("text_cache_only") and encoder.release():
            print("text encoder released (text_cache_only)", flush=True)
    skel30 = model.skeleton
    num_frames = int(req["num_frames"])
    keys = req.get("keys", [])
    root_keys = req.get("root_keys", [])  # 腰の XZ だけ合わせるキー（MMD の全ての親だけのキー）
    for f in [int(k["frame"]) for k in keys + root_keys]:
        if not 0 <= f < num_frames:
            raise ValueError(f"key frame {f} is outside 0..{num_frames - 1}")
    specs = []
    if keys:
        frames = [int(k["frame"]) for k in keys]
        rot = np.array([k["local_rot"] for k in keys], dtype=np.float64).reshape(len(keys), J, 4)
        rotvec = Rotation.from_quat(rot.reshape(-1, 4)).as_rotvec().reshape(len(keys), J, 3)
        root = np.array([k["root"] for k in keys], dtype=np.float64).reshape(len(keys), 3)
        specs.append({
            "type": "fullbody",
            "frame_indices": frames,
            "local_joints_rot": rotvec.tolist(),
            "root_positions": root.tolist(),
        })
    if root_keys:
        spec = {
            "type": "root2d",
            "frame_indices": [int(k["frame"]) for k in root_keys],
            "smooth_root_2d": [[float(v) for v in k["xz"]] for k in root_keys],
        }
        if all("heading" in k for k in root_keys):  # 向きも合わせる（[cos, sin]・正面 +Z が 0）
            spec["global_root_heading"] = [[float(np.cos(k["heading"])), float(np.sin(k["heading"]))] for k in root_keys]
        specs.append(spec)
    # 手足の目印（MMD の IK の目標だけにキーがあるフレーム）: そのフレームの姿勢から、指定した手足の位置と向きだけを合わせる。
    # Kimodo の仕組み上、腰の位置・高さ・向きも一緒に合う（手足の位置は腰から見た値で表すため）。体の他の部分は自由
    ee_keys = req.get("ee_keys", [])
    for joint, ctype in (("LeftHand", "left-hand"), ("RightHand", "right-hand"), ("LeftFoot", "left-foot"), ("RightFoot", "right-foot")):
        ks = [k for k in ee_keys if joint in k["joints"]]
        if not ks:
            continue
        rot = np.array([k["local_rot"] for k in ks], dtype=np.float64).reshape(len(ks), J, 4)
        specs.append({
            "type": ctype,
            "frame_indices": [int(k["frame"]) for k in ks],
            "local_joints_rot": Rotation.from_quat(rot.reshape(-1, 4)).as_rotvec().reshape(len(ks), J, 3).tolist(),
            "root_positions": [[float(v) for v in k["root"]] for k in ks],
        })
    for f in [int(k["frame"]) for k in ee_keys]:
        if not 0 <= f < num_frames:
            raise ValueError(f"key frame {f} is outside 0..{num_frames - 1}")
    constraints = load_constraints_lst(specs, skel30) if specs else []
    # 腰の高さのキー（MMD のセンターの上下。リズムを残すため毎フレーム渡す）
    root_y_keys = req.get("root_y_keys", [])
    if root_y_keys:
        dev = skel30.neutral_joints.device
        constraints.append(RootYConstraintSet(
            skel30,
            torch.tensor([int(k["frame"]) for k in root_y_keys]),
            torch.tensor([float(k["y"]) for k in root_y_keys], device=dev),
        ))
    constraints = [_skip_when_empty(c) for c in constraints]

    if req.get("seed") is not None and int(req["seed"]) >= 0:  # 「毎回変える」は -1
        seed_everything(int(req["seed"]))

    # 区間ごとのプロンプト（multi_prompt）: [{"prompt", "frames"}, …]。区間の長さの合計が全体の長さ。無ければ全体に 1 つ
    segments = req.get("segments") or [{"prompt": req["prompt"], "frames": num_frames}]
    if sum(int(s["frames"]) for s in segments) != num_frames:
        raise ValueError(f"segments add up to {sum(int(s['frames']) for s in segments)} frames, expected {num_frames}")
    t1 = time.time()
    out = model(
        [s["prompt"] for s in segments],
        [int(s["frames"]) for s in segments],
        constraint_lst=constraints,
        num_denoising_steps=int(req.get("steps", 100)),
        cfg_weight=[float(v) for v in req.get("cfg_weight", [2.0, 2.0])],  # [テキストの効き, キーの効き]（Kimodo の既定は 2, 2）
        num_samples=1,
        multi_prompt=True,
        post_processing=bool(req.get("post_processing", True)),
        return_numpy=True,
    )
    t_gen = time.time() - t1

    local = out["local_rot_mats"]  # (1, T, 77, 3, 3)
    local = np.asarray(local)[0]
    local30 = skel30.from_SOMASkeleton77(torch.from_numpy(local)).numpy()  # (T, 30, 3, 3)
    T = local30.shape[0]
    quat = Rotation.from_matrix(local30.reshape(-1, 3, 3)).as_quat().reshape(T, J * 4)
    root = np.asarray(out["root_positions"])[0]  # (T, 3)

    # キーのフレームで生成結果がどれだけずれたか（30 関節で FK した関節位置の最大誤差 m）。
    # 77 関節の posed_joints と比べると、指を曲げた手と伸ばした手の差（約 6cm）が乗るので使わない
    key_err, ee_err = [], []
    if keys or ee_keys:
        dev = skel30.neutral_joints.device
        _, gen_pos, _ = skel30.fk(torch.from_numpy(local30).float().to(dev), torch.from_numpy(root).float().to(dev))
        for c in constraints:
            if c.name == "fullbody":
                target = c.global_joints_positions.detach().float()  # (K, 30, 3)
                idx = c.frame_indices.long()
                key_err = (gen_pos[idx] - target.to(dev)).norm(dim=-1).max(dim=-1).values.cpu().tolist()
            elif c.name in ("left-hand", "right-hand", "left-foot", "right-foot"):
                j = skel30.bone_index[c.joint_names[0]]
                idx = c.frame_indices.long()
                d = (gen_pos[idx, j] - c.global_joints_positions[:, j].detach().float().to(dev)).norm(dim=-1)
                ee_err += d.cpu().tolist()
    # 腰の XZ だけのキー: 生成した腰の XZ との差（m）。Kimodo の制約は「なめらかにした腰」なので、腰そのものとは少しずれる
    root_key_err = [float(np.linalg.norm(root[int(k["frame"])][[0, 2]] - np.array(k["xz"]))) for k in root_keys]
    root_y_err = [float(abs(root[int(k["frame"])][1] - k["y"])) for k in root_y_keys]
    # 向きも合わせたキー: 生成した腰の向きとの差（度）。腰の回転を +Z に当てた向きで測る
    root_heading_err = []
    for k in root_keys:
        if "heading" in k:
            fwd = local30[int(k["frame"]), 0] @ np.array([0.0, 0.0, 1.0])
            d = np.arctan2(fwd[0], fwd[2]) - k["heading"]
            root_heading_err.append(float(abs(np.degrees(np.arctan2(np.sin(d), np.cos(d))))))

    result = {
        "fps": float(model.fps),
        "num_frames": int(T),
        "names": list(skel30.bone_order_names),
        "root": root.reshape(-1).tolist(),
        "local_rot": quat.reshape(-1).tolist(),
        "key_max_error_m": key_err,
        "root_key_error_m": root_key_err,
        "root_heading_error_deg": root_heading_err,
        "root_y_error_m": root_y_err,
        "ee_error_m": ee_err,
        "seconds_load": round(t_load, 2),
        "seconds_generate": round(t_gen, 2),
    }
    line = (f"ok frames={T} load={t_load:.1f}s gen={t_gen:.1f}s key_err={[round(e, 4) for e in key_err]}"
            f" root_key_err={[round(e, 3) for e in root_key_err]} heading_err_deg={[round(e) for e in root_heading_err]}"
            + (f" root_y_err max={max(root_y_err):.3f} mean={sum(root_y_err) / len(root_y_err):.3f}" if root_y_err else "")
            + (f" ee_err max={max(ee_err):.3f}" if ee_err else ""))
    return result, line


def _code_mtime():
    """このファイルと文の読み取りの部品の、新しい方の更新時刻。"""
    here = os.path.dirname(os.path.abspath(__file__))
    files = ([os.path.join(here, f) for f in ("kimodo_gen.py", "gguf_text.py", "kimodo_ort.py")]
             + [os.path.join(HOME, "mmd_ainakawari", "text_keys.py")])
    return max(os.path.getmtime(f) for f in files)


def serve(port):
    """モデルを読み込んだまま、127.0.0.1:port で依頼を待つ。1 つずつ順に作る。IDLE_SECONDS 頼まれなければ終わる。

    {"shutdown": True} を頼まれたら終わる。文の読み取りの llama-server は子なので、一緒に終わる（tools/gguf_text.py のジョブ）。
    """
    from multiprocessing import AuthenticationError
    from multiprocessing.connection import Listener

    # このファイルが書き換わったら、古いコードのまま作らずに終わる（resident.py が立ち上げ直す）。読み込む前に取る
    # （読み込みの途中で書き換わった時も気づけるように。11-04 Codex のレビュー）
    born = _code_mtime()
    os.environ["LOCAL_CACHE"] = "true"   # 読み込みのたびに Hugging Face へ問い合わせない（モデルは入れてある）
    listener = Listener(("127.0.0.1", port), authkey=AUTHKEY)   # 口がふさがっていれば（もう常駐がいれば）ここで落ちる
    t0 = time.time()
    model = load()
    print(f"ready port={port} load={time.time() - t0:.1f}s backend={BACKEND}", flush=True)
    last = [time.time()]

    def watch():
        while True:
            time.sleep(30)
            if time.time() - last[0] > IDLE_SECONDS:
                print("idle exit", flush=True)
                os._exit(0)
    threading.Thread(target=watch, daemon=True).start()
    while True:
        try:
            conn = listener.accept()
        except (OSError, EOFError, AuthenticationError):   # 合言葉を確かめる前に切られた・合言葉の違う相手。常駐は続ける
            continue
        last[0] = time.time() + 24 * 3600   # 作っている間は終わらない
        try:
            req = conn.recv()
            if req.get("shutdown"):
                conn.send({"ok": True, "result": None, "line": "shutdown"})
                conn.close()
                print("shutdown", flush=True)
                os._exit(0)
            if _code_mtime() != born:
                conn.send({"ok": False, "stale": True})
                conn.close()
                print("stale exit", flush=True)
                os._exit(0)
            if req.get("release_text"):   # 窓で「Llama を使う」を外した: llama-server だけ止める（Kimodo は残す）
                released = model.text_encoder.release()
                line = f"text encoder {'released' if released else 'was not running'}"
                conn.send({"ok": True, "result": released, "line": line})
                print(line, flush=True)
                continue
            result, line = generate(model, req)
            conn.send({"ok": True, "result": result, "line": line})
            print(line, flush=True)
        except Exception:
            text = traceback.format_exc()
            print(text, flush=True)
            try:
                conn.send({"ok": False, "error": text})
            except OSError:
                pass
        finally:
            conn.close()
            last[0] = time.time()


def main():
    if sys.argv[1] == "--serve":
        serve(int(sys.argv[2]))
        return
    req = json.load(open(sys.argv[1], encoding="utf-8"))
    t0 = time.time()
    model = load(req.get("model", MODEL))
    result, line = generate(model, req, t_load=time.time() - t0)
    json.dump(result, open(sys.argv[2], "w", encoding="utf-8"))
    print(f"{line} backend={BACKEND}")


if __name__ == "__main__":
    main()
