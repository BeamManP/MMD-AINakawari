"""開いている MikuMikuMoving（MMM 1.2.9.2）とのやり取り。MMDLink（mmd_link.py）と同じ口を持ち、runner.generate にそのまま渡せる。

MMM の中の橋渡しプラグイン（E:\\Projects\\MMM\\mmm-mcp の bridge・core。127.0.0.1:9560・1 行 1 JSON）に頼む。
MMD 版と違って、メモリを読んだり画面を操作したりしない。読むのも書くのも MMM のプラグインの口で、書き戻しは MMM の元に戻す（Ctrl+Z）に 1 段で載る。

扱うのはモーションレイヤの 0 番（名前の無い基本のレイヤ）のボーンのキーだけ。表情・表示/IK のキーは読まず、触らない。
MMM は全ボーンの 0 フレーム目に既定のキー（位置 0・回転なし・直線）を持つ。MMD も 0F のキーは全ボーンにあるので、そのまま渡す。
"""
import json
import os
import socket

import numpy as np

from . import vmd
from .mmd_memory import interp_bytes
from .mmd_skel import MMDSkeleton, curve_points

HOST, PORT = "127.0.0.1", 9560
LAST_FRAME = 1_000_000   # 「全部」の範囲の終わり（MMM のキーはこれより後ろに置けない想定）


class MMMError(RuntimeError):
    pass


def ask(cmd, timeout=120.0, **args):
    req = {"cmd": cmd, **{k: v for k, v in args.items() if v is not None}}
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout) as s:
            f = s.makefile("rw", encoding="utf-8", newline="\n")
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
            f.flush()
            line = f.readline()
    except OSError as e:
        raise MMMError("MMM につながりません。MMM が起動しているか、Plugins に MmmBridge.dll があるかを確かめてください"
                       f"（{HOST}:{PORT}・{e}）") from e
    if not line:
        raise MMMError("MMM から返事がありません（MMM が閉じた可能性があります）")
    res = json.loads(line)
    if not res.get("ok"):
        raise MMMError(f"MMM でできませんでした: {res.get('error')}")
    return res


def _interp_to_vmd(ip):
    """MMM の補間 {x|y|z|r: [ax, ay, bx, by]} → VMD の 64 バイト。"""
    ch = [ip[c] for c in "xyzr"]
    return interp_bytes([c[0] for c in ch], [c[1] for c in ch], [c[2] for c in ch], [c[3] for c in ch])


def _interp_from_vmd(raw):
    """VMD の 64 バイト → MMM の補間（物理演算の印の 2 バイトは curve_points が 2 行目から取り直す）。"""
    p = curve_points(raw)
    return {c: [int(p[i]), int(p[4 + i]), int(p[8 + i]), int(p[12 + i])] for i, c in enumerate("xyzr")}


def _same_keys(a, b, tol=1e-5):
    """MMM のキーの一覧 a と、書こうとしているキーの一覧 b が同じか（フレーム・位置・回転（符号違いも同じ）・補間）。"""
    if len(a) != len(b):
        return False
    for x, y in zip(sorted(a, key=lambda k: k["frame"]), b):
        if x["frame"] != y["frame"] or x["interp"] != y["interp"]:
            return False
        if np.abs(np.subtract(x["position"], y["position"])).max() > tol:
            return False
        q, r = np.asarray(x["quaternion"], float), np.asarray(y["quaternion"], float)
        if min(np.abs(q - r).max(), np.abs(q + r).max()) > tol:
            return False
    return True


class MMMLink:
    def __init__(self):
        self._skel = {}   # PMX の場所 → MMDSkeleton（VMD の名前 → PMX のボーン名の対応に使う）

    # ---------------- 読む ----------------

    def _active(self):
        models = ask("models")["models"]
        active = next((m for m in models if m["active"]), None)
        return active

    @property
    def key(self):
        """相手の見分け。MMM は 1 つだけ相手にする前提で、選択中のモデルの番号（MMM の中の ID）。"""
        m = self._active()
        return f"mmm{m['id'] if m else 0}-0"

    def state(self):
        m = self._active()
        return {"frame": self.current_frame(), "model": m["name"] if m else "", "model_selected": m is not None}

    def current_frame(self):
        return int(ask("marker")["frame"])

    def selected_model(self):
        """選択中のモデルの名前と、読み込んだ PMX の場所。モデルが無ければ None。zip の中のモデルには対応していない。"""
        m = self._active()
        if m is None:
            return None
        r = ask("model_file", model=m["index"])
        if r.get("file_in_archive"):
            raise MMMError(f"zip の中から読み込んだモデル（{r['file']} の {r['file_in_archive']}）には、まだ対応していません。"
                           "zip を展開して、PMX を MMM に読み込み直してください")
        return {"name": m["name"], "path": r["file"], "index": m["index"]}

    def check_model(self, model):
        selected = self.selected_model()
        if selected is None or os.path.normcase(os.path.abspath(selected["path"])) != os.path.normcase(os.path.abspath(model)):
            now = selected["name"] if selected else "モデル無し"
            raise MMMError(f"始めた時と違うモデル（{now}）が選ばれています。キーは書き換えていません。"
                           f"「{os.path.splitext(os.path.basename(model))[0]}」を選んでから、もう一度押してください")

    def selected_key_frames(self):
        """MMM で選択中のボーンのキーのフレーム（全ボーン・昇順・重なりは 1 つ）。「選んだキーの間」に使う。"""
        r = ask("keys", selected=True)
        return sorted({k["frame"] for b in r["bones"] for k in b["keys"]})

    def key_scan(self, with_names=False):
        r = ask("keys", selected=True)
        frames = sorted({k["frame"] for b in r["bones"] for k in b["keys"]})
        if not with_names:
            return frames, None
        allk = ask("keys")
        return frames, {vmd.vmd_name(b["bone"]): [k["frame"] for k in b["keys"]] for b in allk["bones"]}

    def read_motion(self, path):
        """選択中のモデルのボーンのキー（基本のレイヤ）を VMD にして path に書き、vmd.Motion を返す。表情・表示/IK は入れない。"""
        model = self.selected_model()
        if model is None:
            raise MMMError("MMM でモデルを選んでください")
        r = ask("keys", model=model["index"])
        skel = self._skeleton(model["path"])
        bones = []
        for b in r["bones"]:
            for k in b["keys"]:
                bones.append(vmd.BoneKey(vmd.vmd_name(b["bone"]), int(k["frame"]), np.array(k["position"], float),
                                         np.array(k["quaternion"], float), _interp_to_vmd(k["interp"])))
        motion = vmd.Motion(model_name=skel.model_name, bones=bones)
        vmd.write(path, motion)
        return motion

    def _skeleton(self, pmx):
        if pmx not in self._skel:
            self._skel[pmx] = MMDSkeleton(pmx)
        return self._skel[pmx]

    # ---------------- 書く ----------------

    def load_motion(self, path, frame=0, model=None, restore=None):
        """選択中のモデルのボーンのキーを、VMD の中身でまるごと置き換える（MMD 版の load_motion と同じ意味）。

        全ボーンを 1 回の頼みで差し替えるので、MMM の Ctrl+Z 1 回で全部戻る。VMD に無いボーンは 0F の既定のキーだけになる。
        表情・表示/IK のキーは触らない。frame は使わない（MMD は読み込むフレームの分ずれるが、こちらはフレームを直接書く）。
        """
        selected = self.selected_model()
        if selected is None:
            raise MMMError("MMM でモデルを選んでください")
        if model is not None:
            self.check_model(model)
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise MMMError(f"書き戻すファイルがありません。キーは書き換えていません: {path}")
        try:
            self._replace_all(selected, vmd.read(path), undo=True)
        except Exception as e:
            if restore is None:
                raise
            try:
                self._replace_all(selected, vmd.read(restore), undo=False)
            except Exception as e2:
                raise MMMError(f"MMM に書き戻せず（{e}）、控えも戻せませんでした（{e2}）。控え: {restore}") from e
            raise MMMError(f"MMM に書き戻せませんでした（{e}）。控えから戻しました") from e

    def _replace_all(self, selected, motion, undo):
        skel = self._skeleton(selected["path"])
        names = [b["name"] for b in ask("bones", model=selected["index"])["bones"]]
        tracks = {}
        for k in motion.bones:
            full = skel.vmd_alias.get(k.name)
            if full is None:
                continue   # モデルに無いボーンのキー（MMD も読み込みで捨てる）
            tracks.setdefault(full, {})[k.frame] = {
                "frame": int(k.frame), "position": [float(v) for v in k.pos], "quaternion": [float(v) for v in k.rot],
                "interp": _interp_from_vmd(k.interp)}
        # 今の MMM のキーと比べて、変わったボーンだけ送る（送ったボーンは全部の範囲を差し替えるので、変わらない所まで触らない）
        now = {b["bone"]: b["keys"] for b in ask("keys", model=selected["index"])["bones"]}
        bones = {}
        for n in dict.fromkeys(names):   # 同じ名前のボーンは前の方だけ（MMM の Bones[名前] も前の方を返す）
            keys = sorted(tracks.get(n, {}).values(), key=lambda x: x["frame"])
            if not keys:   # VMD に無いボーンは 0F の既定のキーだけにする（MMD の読み込み前に全部消すのと同じ）
                keys = [{"frame": 0, "position": [0.0, 0.0, 0.0], "quaternion": [0.0, 0.0, 0.0, 1.0],
                         "interp": {c: [20, 20, 107, 107] for c in "xyzr"}}]
            if not _same_keys(now.get(n, []), keys):
                bones[n] = keys
        if not bones:
            return {"removed": 0, "added": 0, "undo": False, "bones": 0}
        r = ask("replace_keys", model=selected["index"], range=[0, LAST_FRAME], bones=bones, undo=undo)
        r["bones"] = len(bones)
        return r

    def set_frame(self, frame):
        ask("set_marker", frame=int(frame))

    def return_to(self, frame):
        try:
            self.set_frame(frame)
        except Exception as e:
            return str(e)
        return None
