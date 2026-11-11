"""MMD のメモリから、選択中のモデルのモーション（体・表情のキー、表示と IK のオン・オフ）を読む。書き出しのダイアログの代わり。

形は MMDPlugin 0.41 のヘッダ（mmd_plugin.h の MMDModelData）による。mmd-mcp と同じく検証済みの MMD 9.32 x64 の実行ファイルでだけ読む。
キーはボーン（表情）ごとに「前・次」の番号でつながった鎖で、配列の先頭の ボーン数（表情数）個がそれぞれの 0F のキー。
11-04: 書き出しのダイアログと照合で 2.7 秒かかっていた所が 0.03 秒になる。MMD には何も書かない。
"""
import struct

import numpy as np

from mmd_mcp import bone_state
from mmd_mcp.windows import list_windows

from . import vmd
from .i18n import _

# MMDModelData の中の位置（バイト）。ヘッダの static_assert（name_jp 8896・keyframe_editor_toplevel_rows 10104・bone_count 12560）から数えた
BONE_KEYFRAMES = 10128
MORPH_KEYFRAMES = 10136
CONFIG_KEYFRAMES = 10144
MORPH_COUNT = 12556
IK_COUNT = 12564
BONE_KEY_SIZE = 60     # フレーム・前・次・補間 x1/y1/x2/y2 × 4・位置 3・回転 4・選択の印
MORPH_KEY_SIZE = 20    # フレーム・前・次・値・選択（4 バイトにそろえる）
CONFIG_KEY_SIZE = 40   # フレーム・前・次・表示・（そろえ）・IK のオン・オフの配列への場所・不明 2・外部親の配列への場所
MAX_KEYS = 2_000_000


def _chain(read_entry, head):
    """先頭の番号から「次」をたどった中身の一覧。

    同じ番号に戻る・番号が負・MAX_KEYS を超える時は、メモリが読み方と違う（MMD の版違い・編集の途中）ので止める。
    そのまま返すと、壊れた控えで「元に戻す」をすることになる（11-04 Codex のレビュー: ループで 200 万件を正常として返していた）。
    """
    out, seen, i = [], set(), head
    while True:
        if i < 0 or i in seen or len(out) >= MAX_KEYS:
            raise RuntimeError(_("MMD のキーの並びを読めませんでした（つながりが壊れています）。MMD の操作が終わってからもう一度押してください"))
        seen.add(i)
        e = read_entry(i)
        out.append(e)
        if e[2] == 0:
            return out
        i = e[2]


def interp_bytes(x1, y1, x2, y2):
    """メモリの補間（チャンネル X・Y・Z・回転ごとの x1・y1・x2・y2）→ VMD の 64 バイト。

    VMD は同じ 16 個（X・Y・Z・回転 × x1, y1, x2, y2 の順に並べたもの）を 1 つずつ左にずらして 4 行並べた形（mmd_skel.curve_points）。
    1 行目の 3・4 バイト目は MMD が物理演算のオン・オフの印に使い、書き出しでは 0・0 だった（11-04、734 個全部。物理演算はオン）。
    物理演算をオフにしたキーがメモリのどこに入るかは未確認（キーの最後の 4 バイトは選択の印だった）。
    """
    row = [x1[0], x1[1], x1[2], x1[3], y1[0], y1[1], y1[2], y1[3], x2[0], x2[1], x2[2], x2[3], y2[0], y2[1], y2[2], y2[3]]
    out = []
    for k in range(4):
        out += row[k:] + [0] * k
    out[2], out[3] = 0, 0
    return bytes(out)


class MotionReader:
    def __init__(self, hwnd):
        target = next((w for w in list_windows() if w.hwnd == hwnd), None)
        if target is None:
            raise RuntimeError(_("MMD が閉じられました"))
        self.m = bone_state.BoneMemory(target)

    def close(self):
        self.m.close()

    def _model(self):
        m = self.m
        main = m.pointer(m.base + bone_state.MAIN_POINTER_RVA)
        slot = m.integer(main + bone_state.SELECTED_MODEL)
        if not 0 <= slot < 255:
            raise RuntimeError(_("MMD でモデルが選ばれていません"))
        model = m.pointer(main + bone_state.MODEL_TABLE + slot * 8)
        if not model:
            raise RuntimeError(_("MMD でモデルが選ばれていません"))
        return model

    def bone_names(self, model, count):
        """ボーンの名前（cp932 のバイト列・20 バイトまで）。"""
        data = self.m.pointer(model + bone_state.BONE_POINTER)
        raw = self.m.read(data, count * bone_state.BONE_STRIDE)
        return [raw[i * bone_state.BONE_STRIDE:i * bone_state.BONE_STRIDE + 20].split(b"\0", 1)[0] for i in range(count)]

    def selected_frames(self):
        """タイムラインで選んでいるボーンのキーのフレーム（昇順・重なりなし）。どのボーンのキーでも数える。"""
        return self.scan()[0]

    def scan(self, with_names=False):
        """(選んでいるキーのフレーム（昇順・重なりなし）, 骨の名前（VMD の形）→ キーのフレームの昇順。with_names が False なら None)。

        キーの最後の 4 バイトが選択の印（11-04、90・120F のキーを選んで 734 個中 110 個が 1）。
        窓が 1 秒ごとに読むので、1024 件ずつまとめて読む（1 件ずつだとキーの多いモーションで窓が重くなる）。
        骨ごとのフレームは「続きを足す」で上書きされるキーを窓に出すのに使う（11-07 マスター）。
        """
        m = self.m
        model = self._model()
        count = m.integer(model + bone_state.BONE_COUNT)
        at = m.pointer(model + BONE_KEYFRAMES)
        block, cache = 1024, {}

        def entry(i):
            c = i // block
            if c not in cache:
                try:
                    cache[c] = m.read(at + c * block * BONE_KEY_SIZE, block * BONE_KEY_SIZE)
                except RuntimeError:   # まとめ読みが配列の確保の終わりをはみ出した。そこは 1 件ずつ読む
                    cache[c] = None
            if cache[c] is None:
                data, off = m.read(at + i * BONE_KEY_SIZE, BONE_KEY_SIZE), 0
            else:
                data, off = cache[c], (i % block) * BONE_KEY_SIZE
            return struct.unpack_from("<3i", data, off) + struct.unpack_from("<i", data, off + 56)

        chains = [_chain(entry, i) for i in range(count)]
        selected = sorted({e[0] for chain in chains for e in chain if e[3]})
        if not with_names:
            return selected, None
        frames = {}
        for raw, chain in zip(self.bone_names(model, count), chains):   # 同じ名前（先頭 15 バイト）の骨は 1 つにまとめる
            frames.setdefault(vmd._name(raw[:15]), set()).update(e[0] for e in chain)
        return selected, {n: sorted(f) for n, f in frames.items()}

    def read(self, morph_names, ik_names):
        """選択中のモデルのモーション。morph_names・ik_names は PMX の並び（read_pmx_names）。"""
        m = self.m
        model = self._model()
        count = m.integer(model + bone_state.BONE_COUNT)
        morphs = m.integer(model + MORPH_COUNT)
        iks = m.integer(model + IK_COUNT)
        if morphs != len(morph_names) or iks != len(ik_names):
            raise RuntimeError(_("MMD の表情 {morphs}・IK {iks} 個が、PMX の {pmx_morphs}・{pmx_iks} 個と合いません",
                                 morphs=morphs, iks=iks, pmx_morphs=len(morph_names), pmx_iks=len(ik_names)))
        names = self.bone_names(model, count)
        bones_at = m.pointer(model + BONE_KEYFRAMES)

        def bone_entry(i):
            b = m.read(bones_at + i * BONE_KEY_SIZE, BONE_KEY_SIZE)
            return struct.unpack_from("<3i", b) + (b[12:28], struct.unpack_from("<7f", b, 28))   # 最後の 4 バイトは選択の印

        motion = vmd.Motion(model_name=vmd._name(m.read(model + bone_state.MODEL_NAME_JA, 50).split(b"\0", 1)[0]))
        # VMD は骨を名前（先頭 15 バイト）でしか指せず、MMD は読み込む時に同じ名前のキーを全部前の方の骨に入れる。
        # 2 本目以降のキーを書くと前の方の骨のキーを上書きして壊すので外す（2 本目のキーはどのみち戻せない）。11-06 スコープドッグのセンター
        seen = set()
        for i, raw in enumerate(names):
            if raw[:15] in seen:
                if any(True for _ in _chain(bone_entry, i)):
                    motion.dropped.append(vmd._name(raw[:15]))
                continue
            seen.add(raw[:15])
            for f, _pre, _nxt, ip, v in _chain(bone_entry, i):
                interp = interp_bytes(ip[0:4], ip[4:8], ip[8:12], ip[12:16])
                motion.bones.append(vmd.BoneKey(vmd._name(raw[:15]), f, np.array(v[:3]), np.array(v[3:]), interp, raw[:15]))

        morphs_at = m.pointer(model + MORPH_KEYFRAMES)

        def morph_entry(i):
            b = m.read(morphs_at + i * MORPH_KEY_SIZE, MORPH_KEY_SIZE)
            return struct.unpack_from("<3if", b)

        tail = bytearray()
        rows = []
        for i, name in enumerate(morph_names):
            for f, _pre, _nxt, value in _chain(morph_entry, i):
                rows.append(name.encode("cp932", errors="replace")[:15].ljust(15, b"\0") + struct.pack("<If", f, value))
        tail += struct.pack("<I", len(rows)) + b"".join(rows)
        tail += struct.pack("<3I", 0, 0, 0)   # カメラ・照明・影

        config_at = m.pointer(model + CONFIG_KEYFRAMES)

        def config_entry(i):
            b = m.read(config_at + i * CONFIG_KEY_SIZE, CONFIG_KEY_SIZE)
            f, pre, nxt = struct.unpack_from("<3i", b)
            return f, pre, nxt, b[12], struct.unpack_from("<Q", b, 16)[0]

        rows = []
        for f, _pre, _nxt, visible, ik_at in _chain(config_entry, 0):
            flags = m.read(ik_at, len(ik_names)) if ik_names else b""
            row = struct.pack("<IBI", f, visible, len(ik_names))
            for name, on in zip(ik_names, flags):
                row += name.encode("cp932", errors="replace")[:20].ljust(20, b"\0") + bytes([on])
            rows.append(row)
        tail += struct.pack("<I", len(rows)) + b"".join(rows)
        motion.tail = bytes(tail)
        return motion


class _Reader:
    """PMX を頭から読み飛ばす（表情の名前まで）。mmd_mcp.pmx_geometry と同じ読み方。"""

    def __init__(self, data):
        self.data, self.off = data, 0

    def take(self, n):
        out = self.data[self.off:self.off + n]
        if len(out) != n:
            raise ValueError(_("PMX が途中で終わっています"))
        self.off += n
        return out

    def unpack(self, fmt):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))

    def count(self):
        return self.unpack("<i")[0]

    def text(self):
        return self.take(self.count()).decode(self.encoding)


def read_pmx_names(path):
    """PMX の (表情の名前の並び, IK のボーンの名前の並び)。MMD のメモリの表情・IK はこの並び。"""
    r = _Reader(open(path, "rb").read())
    if r.take(4) != b"PMX ":
        raise ValueError(_("PMX ではありません: {path}", path=path))
    r.take(4)   # 版（2.0・2.1）。表情の項目の大きさは 2.1 の種類まで下の item で扱う
    r.take(1)
    enc, uv, vs, ts, ms, bs, mos, rs = r.unpack("<8B")
    r.encoding = "utf-16-le" if enc == 0 else "utf-8"
    for __ in range(4):
        r.text()
    for __ in range(r.count()):   # 頂点
        r.take(32 + 16 * uv)
        skin, = r.unpack("<B")
        r.take({0: bs, 1: 2 * bs + 4, 2: 4 * bs + 16, 3: 2 * bs + 40, 4: 4 * bs + 16}[skin] + 4)
    r.take(r.count() * vs)        # 面
    for __ in range(r.count()):   # テクスチャ
        r.text()
    for __ in range(r.count()):   # 材質
        r.text()
        r.text()
        r.take(44 + 1 + 20 + 2 * ts + 1)
        shared, = r.unpack("<B")
        r.take(1 if shared else ts)
        r.text()
        r.take(4)
    iks = []
    for __ in range(r.count()):   # ボーン
        name = r.text()
        r.text()
        r.take(12 + bs + 4)
        flags, = r.unpack("<H")
        r.take(bs if flags & 1 else 12)
        if flags & 0x300:
            r.take(bs + 4)
        if flags & 0x400:
            r.take(12)
        if flags & 0x800:
            r.take(24)
        if flags & 0x2000:
            r.take(4)
        if flags & 0x20:
            iks.append(name)
            r.take(bs + 8)
            for __ in range(r.count()):
                r.take(bs)
                limited, = r.unpack("<B")
                if limited:
                    r.take(24)
    morphs = []
    item = {0: mos + 4, 1: vs + 12, 2: bs + 28, 3: vs + 16, 4: vs + 16, 5: vs + 16, 6: vs + 16, 7: vs + 16,
            8: ms + 113, 9: mos + 4, 10: rs + 25}
    for __ in range(r.count()):   # 表情
        morphs.append(r.text())
        r.text()
        r.take(1)
        kind, = r.unpack("<B")
        r.take(r.count() * item[kind])
    return morphs, iks
