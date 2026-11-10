"""生成したキーの間引き（11-09 マスター「後から手で直しにくいので、キーを減らしたい」）。

生成した骨は、範囲の中に毎フレーム・直線の補間でキーが入る（pipeline.build_motion）。ここで、MMD の補間曲線（ベジェ）で
表せる所のキーを落とす。落とすのは生成したキーだけで、マスターが打ったキー・範囲の端・範囲の外のキーは必ず残す。

1. 全身で同じフレームにそろえる: 生成した骨の全部が、骨ごとの許容差（移動・回転）で曲線に乗るまでフレームを進め、
   乗らなくなった所にキーのフレームを置く（後から手で直す時に、キーが全身で同じ列に並ぶ）
2. 骨ごとに要る物だけ残す: 1 のフレームの中から、その骨で曲線に乗らない所だけ残す（動いていない骨は打たない）
3. 全身の姿勢で確かめる: 間引く前と後を、モデル全体で姿勢計算（付与込み）して、手・頭・IK のボーンなどの位置のずれを測る。
   骨ごとのずれは親子で積み重なる（11-09 試作で、骨ごとに 0.5° でも手首が 0.9cm ずれた）ので、超えたフレームは
   その位置を動かす骨（親・付与の元・IK）にキーを足し戻して、収まるまで繰り返す。IK は解かず、IK で動く手足は
   IK のボーン（足ＩＫなど）の位置で見る（Thinner.run）

曲線の当てはめ: 移動の X・Y・Z は軸ごとの値、回転は前後のキーの間の大円の上の割合を 0〜1 の進み具合にして、
制御点 (x1, y1, x2, y2)（0〜127）を探す。x1・x2 は格子で振り、y1・y2 は最小二乗。最後に MMD と同じ補間（mmd_skel.sample の式）で
全フレームを確かめる。MMD の回転の補間は大円の上だけなので、大円から外れる回転の途中はキーを残す。
"""
import time

import numpy as np

from . import quat as Q
from . import vmd
from .mmd_skel import curve_points

MOVE_TOLERANCE = 0.05    # 骨ごとの移動のずれ（MMD の単位）。範囲の外を保つ時（pipeline.SPLIT_MOVE_TOLERANCE）と同じ
ANGLE_TOLERANCE = 0.5    # 骨ごとの回転のずれ（度）。同じく SPLIT_ANGLE_TOLERANCE と同じ
WORLD_TOLERANCE = 0.06   # 全身の姿勢での、手足・頭などの位置のずれ（MMD の単位。約 0.5cm）
# 窓のスライダの段（名前, 許容差の倍率）。0 は間引かない
LEVELS = [("しない", 0.0), ("細かく", 0.5), ("ふつう", 1.0), ("粗く", 2.0), ("とても粗く", 4.0)]
DEFAULT_LEVEL = 2
LOOKAHEAD = 4            # 曲線に乗らなかった後も、何フレーム先まで試すか（当てはめは格子なので、1 つ先で乗ることがある）
MAX_ROUNDS = 6           # 全身の確かめで足し戻す回数。超えたら、ずれた所の骨は間引く前のキーに戻す
WATCH_EXTRA = ("左つま先", "右つま先")   # 全身の確かめで見る骨（対応する骨に足して）

_GRID = np.arange(0, 128, 8) / 127.0
_LINEAR = (20, 20, 107, 107)
_T_CACHE = {}


def level_name(level):
    return LEVELS[max(0, min(len(LEVELS) - 1, int(level)))][0]


def _t_table(n):
    """長さ n フレームの区間の中の点（u = k/n）での、格子の (x1, x2) ごとのベジェの t。形 (格子, 格子, n-1)。"""
    if n not in _T_CACHE:
        u = np.arange(1, n) / n
        x1, x2 = _GRID[:, None, None], _GRID[None, :, None]
        lo = np.zeros((len(_GRID), len(_GRID), n - 1))
        hi = np.ones_like(lo)
        for _ in range(16):   # x(t) = u となる t を二分法で（x(t) は単調増加）
            t = (lo + hi) / 2
            s = 1 - t
            less = 3 * s * s * t * x1 + 3 * s * t * t * x2 + t ** 3 < u
            lo, hi = np.where(less, t, lo), np.where(less, hi, t)
        _T_CACHE[n] = (lo + hi) / 2
    return _T_CACHE[n]


def _fit_curve(y, span, tol):
    """中の点の進み具合 y（u = k/n の順）に乗る曲線の制御点（0〜127）。ずれは y × span（値の単位）で tol まで。無ければ None。"""
    n = len(y) + 1
    if span * np.abs(y - np.arange(1, n) / n).max() <= tol:
        return _LINEAR
    if y.min() < -tol / span or y.max() > 1 + tol / span:   # 端の値を越える（行き過ぎて戻る）動きは、曲線では表せない
        return None
    T = _t_table(n)
    s = 1 - T
    A, B, C = 3 * s * s * T, 3 * s * T * T, T ** 3
    r = y - C
    aa, bb, ab = (A * A).sum(-1), (B * B).sum(-1), (A * B).sum(-1)
    ar, br = (A * r).sum(-1), (B * r).sum(-1)
    det = aa * bb - ab * ab
    det = np.where(np.abs(det) < 1e-12, 1e-12, det)
    y1 = np.round(np.clip((bb * ar - ab * br) / det, 0, 1) * 127) / 127
    y2 = np.round(np.clip((aa * br - ab * ar) / det, 0, 1) * 127) / 127
    err = np.abs(A * y1[..., None] + B * y2[..., None] + C - y).max(-1) * span
    i, j = np.unravel_index(np.argmin(err), err.shape)
    if err[i, j] > tol:
        return None
    return (int(round(_GRID[i] * 127)), int(round(y1[i, j] * 127)), int(round(_GRID[j] * 127)), int(round(y2[i, j] * 127)))


def fit_segment(keys, move_tol, angle_tol):
    """keys: 区間の両端を含む毎フレームのキー。中を落としても全部が許容差に収まる、後ろのキーの 64 バイトの補間。無ければ None。"""
    a, b, mids = keys[0], keys[-1], keys[1:-1]
    curves = []
    for ch in range(3):
        d = b.pos[ch] - a.pos[ch]
        vals = np.array([k.pos[ch] for k in mids])
        if abs(d) < 1e-9:
            if np.abs(vals - a.pos[ch]).max() > move_tol:
                return None
            curves.append(_LINEAR)
            continue
        c = _fit_curve((vals - a.pos[ch]) / d, abs(d), move_tol)
        if c is None:
            return None
        curves.append(c)
    qa, qb = a.rot / np.linalg.norm(a.rot), b.rot / np.linalg.norm(b.rot)
    if np.dot(qa, qb) < 0:   # MMD（quat.slerp）は近い方を回る
        qb = -qb
    M = np.array([k.rot for k in mids], float)
    M /= np.linalg.norm(M, axis=1, keepdims=True)
    theta = np.degrees(2 * np.arccos(np.clip(np.dot(qa, qb), -1, 1)))
    if theta < 1e-4:
        if _angles(M, qa[None, :]).max() > angle_tol:
            return None
        curves.append(_LINEAR)
    else:
        e2 = qb - np.dot(qa, qb) * qa
        e2 /= np.linalg.norm(e2)
        c1, c2 = M @ qa, M @ e2   # 大円（qa・e2 の面）の上の角度と、面からの外れ
        flip = (c1 < 0) & (c1 * c1 + c2 * c2 > 0.5)   # 四元数の裏表
        c1, c2 = np.where(flip, -c1, c1), np.where(flip, -c2, c2)
        off = np.sqrt(np.clip(1 - c1 * c1 - c2 * c2, 0, 1))
        if np.degrees(2 * np.arcsin(off)).max() > angle_tol:
            return None
        c = _fit_curve(np.degrees(2 * np.arctan2(c2, c1)) / theta, theta, angle_tol * 0.8)   # 大円からの外れの分を残す
        if c is None:
            return None
        curves.append(c)
    row = [curves[ch][r] for r in range(4) for ch in range(4)]
    data = bytearray(sum(([*row[k:], *([0] * k)] for k in range(4)), []))
    data[2], data[3] = b.interp[2], b.interp[3]   # 物理演算の印（mmd_skel.curve_points）は後ろのキーの物のまま
    # MMD と同じ補間（mmd_skel.sample と同じ式）で、全フレームを確かめる。丸めた制御点で外れることがあるので
    n = b.frame - a.frame
    u = np.array([k.frame - a.frame for k in mids]) / n
    w = [_bezier_weights(curves[ch], u) for ch in range(4)]
    pos = a.pos[None, :] + (b.pos - a.pos)[None, :] * np.stack(w[:3], axis=1)
    if np.abs(pos - np.array([k.pos for k in mids])).max() > move_tol:
        return None
    if _angles(_slerps(a.rot, b.rot, w[3]), M).max() > angle_tol:
        return None
    return bytes(data)


def _angles(A, B):
    """四元数の並び A・B（どちらか 1 行でもよい）の行ごとの角度（度）。_angle と同じ式。"""
    A = A / np.linalg.norm(A, axis=-1, keepdims=True)
    B = B / np.linalg.norm(B, axis=-1, keepdims=True)
    half = np.minimum(np.linalg.norm(A - B, axis=-1), np.linalg.norm(A + B, axis=-1)) / 2
    return np.degrees(4 * np.arcsin(np.minimum(1.0, half)))


def _slerps(a, b, t):
    """quat.slerp(a, b, t) を t（配列）まとめて。"""
    d = np.dot(a, b)
    if d < 0:
        b, d = -b, -d
    t = t[:, None]
    if d > 0.9995:
        out = a[None, :] + t * (b - a)[None, :]
        return out / np.linalg.norm(out, axis=1, keepdims=True)
    th = np.arccos(d)
    return (np.sin((1 - t) * th) * a[None, :] + np.sin(t * th) * b[None, :]) / np.sin(th)


def _bezier_weights(curve, u):
    """mmd_skel.bezier_weight を、間の割合 u（配列）まとめて。curve は 0〜127 の (x1, y1, x2, y2)。"""
    x1, y1, x2, y2 = (v / 127.0 for v in curve)
    if x1 == y1 and x2 == y2:
        return u.copy()
    lo, hi = np.zeros_like(u), np.ones_like(u)
    for _ in range(32):
        t = (lo + hi) / 2
        s = 1 - t
        less = 3 * s * s * t * x1 + 3 * s * t * t * x2 + t ** 3 < u
        lo, hi = np.where(less, t, lo), np.where(less, hi, t)
    t = (lo + hi) / 2
    s = 1 - t
    return 3 * s * s * t * y1 + 3 * s * t * t * y2 + t ** 3


class _Track:
    """生成した骨 1 本（VMD の名前でまとめる）。frames → キー、落としてよいフレーム。"""

    def __init__(self, name, keys, gen_ids):
        self.name = name
        self.at = {}
        for k in keys:
            self.at[k.frame] = k   # 同じフレームが 2 つあれば後ろの物（merge は作らない）
        self.droppable = {k.frame for k in keys if id(k) in gen_ids}
        self.req = set()        # 全身の確かめで足し戻したフレーム
        self.kept = None        # 残すフレーム（昇順）
        self.interp = {}        # 残すキーの、書き換えた補間 {フレーム: 64 バイト}


class Thinner:
    def __init__(self, skel, rt, level):
        self.skel, self.rt = skel, rt
        self.scale = LEVELS[level][1]
        self.move_tol = MOVE_TOLERANCE * self.scale
        self.angle_tol = ANGLE_TOLERANCE * self.scale
        self.world_tol = WORLD_TOLERANCE * self.scale
        self._fits = {}

    def _fit(self, tr, i, j):
        key = (tr.name, i, j)
        if key not in self._fits:
            if any(f not in tr.droppable for f in range(i + 1, j)) or i not in tr.at or j not in tr.at:
                self._fits[key] = None
            else:
                self._fits[key] = fit_segment([tr.at[f] for f in range(i, j + 1)], self.move_tol, self.angle_tol)
        return self._fits[key]

    # ---------------- 1. 全身でそろえるフレーム ----------------

    def _aligned(self, tracks, lo, hi):
        """lo〜hi（両端は残すキー）の間で、全身でキーを置くフレーム（両端を含む昇順）。"""
        used = [tr for tr in tracks if any(lo < f < hi for f in tr.droppable)]
        out, i = [lo], lo
        while i < hi:
            best, j, misses = i + 1, i + 2, 0
            while j <= hi and misses <= LOOKAHEAD:
                if all(self._fit(tr, i, j) is not None for tr in used):
                    best, misses = j, 0
                else:
                    misses += 1
                j += 1
            out.append(best)
            i = best
        return out

    # ---------------- 2. 骨ごとに要る物だけ ----------------

    def _thin_track(self, tr, aligned):
        """tr の残すフレームを決める。候補はそろえたフレームと足し戻したフレーム、残すのは落とせないキーと足し戻したフレーム。"""
        lo, hi = min(tr.at), max(tr.at)
        cand = sorted({f for f in aligned if f in tr.at} | tr.req | {f for f in tr.at if f not in tr.droppable} | {lo, hi})
        must = (set(tr.at) - tr.droppable) | tr.req | {lo, hi}
        kept, interp, i = [cand[0]], {}, 0
        while i < len(cand) - 1:
            best, best_interp, misses = i + 1, None, 0
            j = i + 1
            while j < len(cand):
                if j > i + 1 or cand[j] - cand[i] > 1:
                    got = self._fit(tr, cand[i], cand[j])
                    if got is None:
                        misses += 1
                        if misses > LOOKAHEAD:
                            break
                    else:
                        best, best_interp, misses = j, got, 0
                if cand[j] in must:
                    break
                j += 1
            if best == i + 1 and best_interp is None and cand[best] - cand[i] > 1:
                # 隣の候補までも曲線に乗らない（足し戻したフレームが候補の間にある時など）: 間のキーを全部残す
                kept += [f for f in range(cand[i] + 1, cand[best]) if f in tr.at]
            if best_interp is not None:
                interp[cand[best]] = best_interp
            kept.append(cand[best])
            i = best
        tr.kept, tr.interp = kept, interp

    # ---------------- 3. 全身の姿勢で確かめる ----------------

    def _influencers(self, name):
        """PMX のボーン name の位置を動かす骨（自分と祖先・付与の元・その骨を鎖に含む IK とその祖先）の名前。"""
        sk = self.skel
        out, todo = set(), [sk.i(name)]
        while todo:
            i = todo.pop()
            if i in out or i < 0:
                continue
            out.add(i)
            todo.append(sk.parent[i])
            b = sk.bones[i]
            if b["inherit"] and b["flags"] & 0x300:
                todo.append(b["inherit"][0])
        for i, b in enumerate(sk.bones):
            if b["ik"] and any(l["bone_index"] in out for l in b["ik"]["links"]):
                j = i
                while j >= 0 and j not in out:
                    out.add(j)
                    j = sk.parent[j]
        return {sk.names[i] for i in out}

    def _poser(self, watch_i):
        """見る骨の位置を全フレームまとめて計算する関数 (tracks, frames) → 配列 (フレーム, 見る骨, 3)。
        mmd_skel.MMDSkeleton.pose と同じ式（付与込み）を、IK は解かずに、見る骨に効く骨（祖先と付与の元）だけで計算する
        （1 フレームずつ pose を呼ぶと 1 回 6ms で、300F の確かめが 10 秒かかった。11-09）。"""
        sk = self.skel
        need, todo = set(), list(watch_i)
        while todo:
            i = todo.pop()
            if i < 0 or i in need:
                continue
            need.add(i)
            todo.append(sk.parent[i])
            b = sk.bones[i]
            if b["inherit"] and b["flags"] & 0x300:
                todo.append(b["inherit"][0])
        order = [i for i in sk.order if i in need]

        def pose(tracks, frames):
            T = len(frames)
            ident = np.tile(Q.IDENTITY, (T, 1))
            zero = np.zeros((T, 3))
            anim_r, anim_t = {}, {}
            for i in order:
                keys = tracks.get(sk.names[i])
                if keys:
                    anim_t[i], r = _sample_all(keys, frames)
                    anim_r[i] = r / np.linalg.norm(r, axis=1, keepdims=True)
                else:
                    anim_t[i], anim_r[i] = np.zeros((T, 3)), ident
            app_r, G, P = {}, {}, {}
            for i in order:
                b = sk.bones[i]
                app, app_t = ident, 0.0
                if b["inherit"]:
                    a, ratio = b["inherit"]
                    if b["flags"] & 0x100:
                        app = _scale_angles(_mul(app_r.get(a, ident), anim_r[a]), ratio)
                    if b["flags"] & 0x200:
                        app_t = anim_t[a] * ratio
                app_r[i] = app
                local = _mul(app, anim_r[i])
                p = sk.parent[i]
                offset = sk.rest[i] - (sk.rest[p] if p >= 0 else 0) + anim_t[i] + app_t
                if p >= 0:
                    # 親が子より後に回るモデルがある（親の変形階層が高い・親が物理後。計算の順は sk.order）。その時の親は、
                    # mmd_skel.pose と同じく、まだ計算していない値（回転なし・原点）を使う（11-11 issue #1「レミリア・S」で
                    # KeyError: 146 になり、生成のたびに間引きで止まっていた）
                    gp, pp = G.get(p, ident), P.get(p, zero)
                    g = _mul(gp, local)
                    G[i] = g / np.linalg.norm(g, axis=1, keepdims=True)
                    P[i] = pp + Q.rotate(gp.T, offset.T).T
                else:
                    G[i], P[i] = local, offset
            return np.stack([P[i] for i in watch_i], axis=1)
        return pose

    def run(self, merged, generated):
        """merged: 生成を差し込んだモーション（pipeline.merge）。generated: 差し込んだ生成のキー（pipeline.build_motion）。"""
        t0 = time.time()
        gen_ids = {id(k) for k in generated.bones}
        names = {vmd.vmd_name(k.name) for k in generated.bones}
        grouped, others = {}, []
        for k in merged.bones:
            vn = vmd.vmd_name(k.name)
            (grouped.setdefault(vn, []) if vn in names else others).append(k)
        tracks = [_Track(n, ks, gen_ids) for n, ks in sorted(grouped.items())]
        # 生成したフレームの続き（間に生成でないフレームを挟まない所）ごとに、両端は落とさないキー
        gen_frames = sorted(set().union(*(tr.droppable for tr in tracks))) if tracks else []
        spans, s = [], None
        for f in gen_frames:
            if s is None or f != prev + 1:
                if s is not None:
                    spans.append((s, prev))
                s = f
            prev = f
        if s is not None:
            spans.append((s, prev))
        aligned = []
        for a, b in spans:
            lo = a - 1 if all(a - 1 in tr.at for tr in tracks if a in tr.droppable) else a
            hi = b + 1 if all(b + 1 in tr.at for tr in tracks if b in tr.droppable) else b
            aligned += self._aligned(tracks, lo, hi)
        aligned = sorted(set(aligned))
        for tr in tracks:
            self._thin_track(tr, aligned)
        t_fit = time.time() - t0

        # 全身の確かめ（間引く前の姿勢は 1 回だけ計算する）。IK は解かずに骨を順にたどる（1 フレームの計算の 8 割が IK を解く時間。
        # 11-09 Tda ミクで 0.044 秒 → 300F の確かめが 2 分かかった）。IK で動く手足（鎖と届かせる先の骨）は、骨の回転でなく
        # IK のボーン（足ＩＫなど）の位置で見る。MMD では、そこは IK の目標の位置で決まり、骨のキーの回転は見た目に出ない
        # （脚の骨まで見ると、つま先を守るためにキーが 556 → 1673 個に増えていた。11-09）
        sk = self.skel
        by_ik = set()
        for n in self.rt.our_iks:
            ik = sk.bones[sk.i(n)]["ik"]
            by_ik |= {l["bone_index"] for l in ik["links"]} | {ik["target_index"]}
        watch = [n for n in dict.fromkeys(list(self.rt.mapped) + list(WATCH_EXTRA) + list(self.rt.our_iks))
                 if n in sk and sk.i(n) not in by_ik]
        watch_i = [sk.i(n) for n in watch]
        frames = sorted({f for a, b in spans for f in range(a, b + 1)})
        pose_all = self._poser(watch_i)
        dense = pose_all(_pmx_tracks(sk, merged), frames)
        influencers = {n: {vmd.vmd_name(m) for m in self._influencers(n)} for n in watch}
        by_name = {tr.name: tr for tr in tracks}
        worst, rounds = {}, 0
        while frames:
            d = np.linalg.norm(pose_all(_pmx_tracks(sk, self._motion(merged, others, tracks)), frames) - dense, axis=2)
            worst = {f: (float(d[k].max()), watch[int(d[k].argmax())]) for k, f in enumerate(frames)}
            bad = [(f, w) for f, (dd, w) in sorted(worst.items()) if dd > self.world_tol]
            if not bad:
                break
            rounds += 1
            before = {tr.name: list(tr.kept) for tr in tracks}
            for f, w in bad:
                for n in influencers[w]:
                    tr = by_name.get(n)
                    if tr is None or f in tr.kept or not tr.droppable:
                        continue
                    p = max((x for x in tr.kept if x < f), default=None)
                    q = min((x for x in tr.kept if x > f), default=None)
                    if p is None or q is None:
                        continue
                    # その骨のこの区間が、間引く前とどこもずれていなければ足さない（ずっと 0 のグルーブ・腰などは、手首の祖先でも
                    # 足しても直らない。11-10 本物の MMD の 30〜90F で、動かない骨に 5〜16 個ずつキーが残っていた）。
                    # そのフレームだけで見ると、足し戻す骨が減って収まるまでの回数が増え、上限で間引く前に戻す所が広がった
                    inner = [x for x in range(p + 1, q) if x in tr.at]
                    pos, rot = _sample_all([self._key(tr, x) for x in tr.kept], inner)
                    want_p = np.array([tr.at[x].pos for x in inner])
                    want_r = np.array([tr.at[x].rot for x in inner])
                    if np.abs(pos - want_p).max() < 1e-4 and _angles(rot, want_r).max() < 0.01:
                        continue
                    if rounds > MAX_ROUNDS:   # 収まらない: その骨のこの区間は間引く前のキーに戻す
                        tr.req |= {x for x in range(p + 1, q) if x in tr.at}
                        continue
                    a1 = max(x for x in aligned if x <= f)
                    a2 = min(x for x in aligned if x >= f)
                    if p < a1 or q > a2:   # そろえたフレームより長く間引いていた: そろえたフレームに戻す
                        tr.req |= {x for x in (a1, a2) if x in tr.at and p < x < q}
                    else:                  # そろえたフレームの間でもずれる: ずれたフレームにキーを打つ
                        tr.req.add(f)
            changed = False
            for tr in tracks:
                old = _segments(before[tr.name], tr.interp)
                self._thin_track(tr, aligned)
                changed |= old != _segments(tr.kept, tr.interp)
            if not changed:   # 足し戻せる所が無い（範囲の端など）。そのまま止める
                break
        out = self._motion(merged, others, tracks)
        worst_d, worst_w = max(worst.values(), default=(0.0, ""))
        info = {"before": len(merged.bones), "after": len(out.bones), "aligned": len(aligned), "rounds": rounds,
                "world_max": worst_d, "world_bone": worst_w, "seconds_fit": t_fit, "seconds": time.time() - t0}
        return out, info

    @staticmethod
    def _key(tr, f):
        k = tr.at[f]
        return vmd.BoneKey(k.name, k.frame, k.pos, k.rot, tr.interp[f], k.raw) if f in tr.interp else k

    def _motion(self, merged, others, tracks):
        bones = list(others) + [self._key(tr, f) for tr in tracks for f in tr.kept]
        return vmd.Motion(model_name=merged.model_name, bones=bones, tail=merged.tail, name_raw=merged.name_raw,
                          dropped=list(merged.dropped))


def _mul(a, b):
    """quat.mul を行ごとに（形 (フレーム, 4)）。"""
    return Q.mul(a.T, b.T).T


def _scale_angles(q, t):
    """quat.scale_angle を行ごとに。"""
    q = q / np.linalg.norm(q, axis=1, keepdims=True)
    q = np.where(q[:, 3:4] < 0, -q, q)
    angle = 2 * np.arccos(np.clip(q[:, 3], -1, 1))
    s = np.sqrt(np.maximum(1 - q[:, 3] ** 2, 0))
    axis = np.where(s[:, None] > 1e-9, q[:, :3] / np.where(s > 1e-9, s, 1)[:, None], np.array([1.0, 0, 0]))
    half = angle * t / 2
    return np.concatenate([axis * np.sin(half)[:, None], np.cos(half)[:, None]], axis=1)


def _sample_all(keys, frames):
    """mmd_skel.sample を、フレームの並び（昇順）まとめて。(移動 (フレーム, 3), 回転 (フレーム, 4))。"""
    F = np.asarray(frames)
    kf = np.array([k.frame for k in keys])
    pos = np.empty((len(F), 3))
    rot = np.empty((len(F), 4))
    idx = np.searchsorted(kf, F, side="right")   # そのフレーム以前のキーの数
    on_key = (idx > 0) & (kf[np.maximum(idx - 1, 0)] == F)
    if on_key.any():   # キーのフレームはキーの値（毎フレームのキーの時は、ほぼ全部がこれ）
        on = idx[on_key] - 1
        pos[on_key] = np.array([k.pos for k in keys])[on]
        rot[on_key] = np.array([k.rot for k in keys])[on]
    idx = np.where(on_key, -1, idx)
    for n in np.unique(idx):
        if n < 0:
            continue
        sel = idx == n
        if n == 0 or n == len(keys):   # 最初のキーより前・最後のキー以後は、そのキーの値
            k = keys[0] if n == 0 else keys[-1]
            pos[sel], rot[sel] = k.pos, k.rot
            continue
        a, b = keys[n - 1], keys[n]
        u = (F[sel] - a.frame) / (b.frame - a.frame)
        points = curve_points(b.interp)
        w = [_bezier_weights(tuple(points[ch + 4 * r] for r in range(4)), u) for ch in range(4)]
        pos[sel] = a.pos[None, :] + (b.pos - a.pos)[None, :] * np.stack(w[:3], axis=1)
        rot[sel] = _slerps(a.rot, b.rot, w[3])
    return pos, rot


def _segments(kept, interp):
    """残すフレームと書き換えた曲線から、区間 (前のフレーム, 後ろのフレーム, 曲線) の集合。"""
    return {(p, q, interp.get(q)) for p, q in zip(kept, kept[1:])}


def _pmx_tracks(skel, motion):
    out = {}
    for name, keys in motion.tracks().items():
        out.setdefault(skel.vmd_alias.get(name, name), []).extend(keys)
    for keys in out.values():
        keys.sort(key=lambda k: k.frame)
    return out


def thin_motion(merged, generated, skel, rt, level):
    """生成したキーを間引いたモーションと、その記録（info）。level は LEVELS の番号（0 なら間引かず info は None）。
    merged: 生成を差し込んだモーション（pipeline.merge）。generated: 差し込んだ生成のキー（pipeline.build_motion。merge が
    同じキーの物を入れるので、どれが生成したキーかを見分けるのに使う）。"""
    level = max(0, min(len(LEVELS) - 1, int(level)))
    if not LEVELS[level][1] or not generated.bones:
        return merged, None
    return Thinner(skel, rt, level).run(merged, generated)
