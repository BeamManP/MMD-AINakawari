"""VMD（MMD のモーション）のボーンのキーの読み書き。

表情・カメラ・照明・影・表示/IK の部分は中身を解かずに tail としてそのまま通す。
MMD には今のキーを全部消してから読み込むので、書き戻しでは元のものを全部残す必要がある。
"""
import struct
from dataclasses import dataclass, field

import numpy as np

HEADER = b"Vocaloid Motion Data 0002"

# 補間は全部直線（x1=y1=20, x2=y2=107）。64 バイトは 16 バイトの行を 1 つずつずらした 4 行（MMD の並び）
_ROW = [20] * 8 + [107] * 8
LINEAR_INTERP = bytes(sum(([*_ROW[k:], *([0] * k)] for k in range(4)), []))


@dataclass
class BoneKey:
    name: str
    frame: int
    pos: np.ndarray            # 移動（MMD 単位）
    rot: np.ndarray            # 回転の四元数 x, y, z, w（親から見たローカル）
    interp: bytes = LINEAR_INTERP
    raw: bytes = b""           # 読んだ時の名前のバイト列。15 バイトで切れて文字の途中で終わる名前を、そのまま書き戻すため


@dataclass
class Motion:
    model_name: str = ""
    bones: list = field(default_factory=list)
    tail: bytes = b""          # ボーンのキーより後ろ（表情・カメラ・照明・影・表示/IK）。空なら全部 0 件で書く

    def tracks(self):
        """ボーン名 → フレーム順のキーの一覧。"""
        out = {}
        for k in self.bones:
            out.setdefault(k.name, []).append(k)
        for v in out.values():
            v.sort(key=lambda k: k.frame)
        return out

    def key_frames(self, names=None):
        return sorted({k.frame for k in self.bones if names is None or k.name in names})


def _name(raw):
    return raw.split(b"\0", 1)[0].decode("cp932", errors="replace")


def vmd_name(name):
    """PMX のボーン名を、VMD に入る形（cp932 で 15 バイトまで。MMD と同じく文字の途中でも切る）にして読んだ時の名前。"""
    return _name(name.encode("cp932", errors="replace")[:15])


def read(path):
    data = open(path, "rb").read()
    if not data.startswith(HEADER):
        raise ValueError(f"VMD ではありません: {path}")
    m = Motion(model_name=_name(data[30:50]))
    off = 50
    count, = struct.unpack_from("<I", data, off)
    off += 4
    for _ in range(count):
        raw = data[off:off + 15].split(b"\0", 1)[0]
        frame, = struct.unpack_from("<I", data, off + 15)
        px, py, pz, rx, ry, rz, rw = struct.unpack_from("<7f", data, off + 19)
        interp = data[off + 47:off + 111]
        m.bones.append(BoneKey(_name(raw), frame, np.array([px, py, pz]), np.array([rx, ry, rz, rw]), interp, raw))
        off += 111
    m.tail = data[off:]
    return m


def write(path, motion):
    out = bytearray(HEADER.ljust(30, b"\0"))
    out += motion.model_name.encode("cp932")[:20].ljust(20, b"\0")
    out += struct.pack("<I", len(motion.bones))
    for k in motion.bones:
        # 読んだキーは元のバイト列のまま。こちらで作った名前は MMD と同じく 15 バイトで切る
        name = k.raw if k.raw and _name(k.raw) == k.name else k.name.encode("cp932", errors="replace")[:15]
        out += name.ljust(15, b"\0")
        out += struct.pack("<I7f", k.frame, *map(float, k.pos), *map(float, k.rot))
        out += k.interp if len(k.interp) == 64 else LINEAR_INTERP
    out += motion.tail if motion.tail else struct.pack("<5I", 0, 0, 0, 0, 0)  # 表情・カメラ・照明・影・表示/IK
    open(path, "wb").write(bytes(out))
