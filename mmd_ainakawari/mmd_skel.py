"""MMD のモデルの骨の姿勢計算（付与・IK 込み）。

MMD の骨は基準姿勢で全部回転 0（ワールドと同じ向き）。キーの回転は親から見たローカル回転で、
全体の回転 = 親の全体の回転 × 自分のローカル回転。位置は「親の位置 + 親の回転 × (基準での親からの差 + キーの移動)」。
単位は MMD の単位（およそ 8cm）、+X がモデルの左、+Y が上、モデルは −Z を向く。
"""
import numpy as np
from mmd_mcp.pmx_geometry import read_pmx_geometry

from . import quat as Q
from .vmd import vmd_name


class MMDSkeleton:
    def __init__(self, pmx_path):
        self.model_name, bones = read_pmx_geometry(open(pmx_path, "rb").read())
        self.bones = bones
        self.names = [b["name"] for b in bones]
        # 同じ名前の骨があれば前の方（MMD も VMD のキーを前の方に入れる）。11-06 スコープドッグはセンターが 2 本（体と、ライフルの持ち手）で、
        # 後ろのライフルの方を基準に体の位置を計算して、体が上に飛んでいた
        self.index = {}
        for i, n in enumerate(self.names):
            self.index.setdefault(n, i)
        # VMD の名前（15 バイトで切れたもの）→ PMX のボーン名。長い名前のボーンのキーを正しく当てるため
        self.vmd_alias = {}
        for n in self.names:
            self.vmd_alias.setdefault(vmd_name(n), n)
        self.parent = [b["parent"] for b in bones]
        self.rest = np.array([b["rest_position"] for b in bones], dtype=float)
        # 計算の順番: 物理後か → 変形階層 → 番号（MMD と同じ）
        self.order = sorted(range(len(bones)), key=lambda i: (bool(bones[i]["flags"] & 0x1000), bones[i]["layer"], i))
        self.rank = {i: r for r, i in enumerate(self.order)}
        self.children = [[] for _ in bones]
        for i in self.order:
            if self.parent[i] >= 0:
                self.children[self.parent[i]].append(i)

    def __contains__(self, name):
        return name in self.index

    def i(self, name):
        if name not in self.index:
            raise KeyError(f"モデルにボーン「{name}」がありません")
        return self.index[name]

    # ---------------- 姿勢 ----------------

    def pose(self, local_rot=None, local_pos=None, solve_ik=True, world_targets=None, skip_ik=()):
        """local_rot / local_pos: {ボーン名: 四元数 / 移動}。全体の回転 G と位置 P（どちらも配列）を返す。

        world_targets: {ボーン名: 全体の回転}。その骨は、計算の途中で親の実際の向き（間に挟まった骨・付与・IK 込み）を見て、
                       全体の回転がこの値になるようにキーの回転を決める。決めた値は self.anim_rot(名前) で読める。
        skip_ik: 解かない IK のボーン名（目標が届いている前提の IK を、書き戻しの計算中に動かさないため）。
        """
        n = len(self.bones)
        self._targets = {self.index[k]: Q.normalize(np.asarray(v, float)) for k, v in (world_targets or {}).items() if k in self.index}
        skip = {self.index[k] for k in skip_ik if k in self.index}
        self._anim_r = [Q.IDENTITY.copy() for _ in range(n)]
        self._anim_t = [np.zeros(3) for _ in range(n)]
        self._ik_r = [Q.IDENTITY.copy() for _ in range(n)]
        self._app_r = [Q.IDENTITY.copy() for _ in range(n)]
        self._app_t = [np.zeros(3) for _ in range(n)]
        for name, q in (local_rot or {}).items():
            if name in self.index:
                self._anim_r[self.index[name]] = Q.normalize(np.asarray(q, float))
        for name, t in (local_pos or {}).items():
            if name in self.index:
                self._anim_t[self.index[name]] = np.asarray(t, float)
        self.G = [Q.IDENTITY.copy() for _ in range(n)]
        self.P = [np.zeros(3) for _ in range(n)]
        for i in self.order:
            self._update_one(i)
            if solve_ik and self.bones[i]["ik"] and i not in skip:
                self._solve_ik(i)
        return np.array(self.G), np.array(self.P)

    def anim_rot(self, name):
        """直前の pose() での、その骨のキーの回転（world_targets で決めた値を含む）。"""
        return self._anim_r[self.i(name)].copy()

    def _local(self, i):
        return Q.mul(Q.mul(self._app_r[i], self._anim_r[i]), self._ik_r[i])

    def _update_one(self, i):
        b = self.bones[i]
        if b["inherit"]:
            a, ratio = b["inherit"]
            if b["flags"] & 0x100:
                self._app_r[i] = Q.scale_angle(self._local(a), ratio)
            if b["flags"] & 0x200:
                self._app_t[i] = self._anim_t[a] * ratio
        p = self.parent[i]
        if i in self._targets:
            # 全体の回転 = 親の全体 × 付与 × キー × IK なので、キー = 付与⁻¹ × 親⁻¹ × 欲しい全体 × IK⁻¹
            want_local = Q.mul(Q.inv(self.G[p]), self._targets[i]) if p >= 0 else self._targets[i]
            self._anim_r[i] = Q.normalize(Q.mul(Q.mul(Q.inv(self._app_r[i]), want_local), Q.inv(self._ik_r[i])))
        local = self._local(i)
        offset = self.rest[i] - (self.rest[p] if p >= 0 else 0) + self._anim_t[i] + self._app_t[i]
        if p >= 0:
            self.G[i] = Q.normalize(Q.mul(self.G[p], local))
            self.P[i] = self.P[p] + Q.rotate(self.G[p], offset)
        else:
            self.G[i] = local
            self.P[i] = offset

    def _update_subtree(self, i):
        self._update_one(i)
        for c in self.children[i]:
            self._update_subtree(c)

    def _solve_ik(self, ik_index):
        ik = self.bones[ik_index]["ik"]
        target = ik["target_index"]
        limit = ik["angle_limit_radians"]
        links = ik["links"]
        top = min((l["bone_index"] for l in links), key=lambda j: self.rank[j])
        for _ in range(max(1, ik["iterations"])):
            for link in links:
                j = link["bone_index"]
                inv_g = Q.inv(self.G[j])
                v1 = Q.rotate(inv_g, self.P[target] - self.P[j])
                v2 = Q.rotate(inv_g, self.P[ik_index] - self.P[j])
                if np.linalg.norm(v1) < 1e-9 or np.linalg.norm(v2) < 1e-9:
                    continue
                v1 /= np.linalg.norm(v1)
                v2 /= np.linalg.norm(v2)
                lo, hi = link["lower_radians"], link["upper_radians"]
                if link["limited"] and abs(lo[1]) < 1e-6 and abs(hi[1]) < 1e-6 and abs(lo[2]) < 1e-6 and abs(hi[2]) < 1e-6:
                    # 膝: X 軸だけ。X に垂直な面へ写して符号つきの角度を足し、範囲に収める
                    ang = np.arctan2(v1[1] * v2[2] - v1[2] * v2[1], v1[1] * v2[1] + v1[2] * v2[2])
                    ang = np.clip(ang, -limit, limit)
                    cur = Q.to_euler_xyz(Q.mul(self._anim_r[j], self._ik_r[j]))[0]
                    new = np.clip(cur + ang, min(lo[0], hi[0]), max(lo[0], hi[0]))
                    self._ik_r[j] = Q.mul(Q.inv(self._anim_r[j]), Q.from_axis_angle([1, 0, 0], new))
                else:
                    angle = np.arccos(np.clip(np.dot(v1, v2), -1, 1))
                    if angle < 1e-6:
                        continue
                    rot = Q.from_axis_angle(Q.cross(v1, v2), min(angle, limit))
                    self._ik_r[j] = Q.normalize(Q.mul(self._ik_r[j], rot))
                    if link["limited"]:
                        e = Q.to_euler_xyz(Q.mul(self._anim_r[j], self._ik_r[j]))
                        e = np.clip(e, np.minimum(lo, hi), np.maximum(lo, hi))
                        self._ik_r[j] = Q.mul(Q.inv(self._anim_r[j]), Q.from_euler_xyz(e))
                self._update_subtree(top)
            if np.linalg.norm(self.P[target] - self.P[ik_index]) < 1e-4:
                break

    def local_with_ik(self, name):
        """直前の pose() での、キー＋IK を合わせたローカル回転（付与は含まない）。"""
        j = self.i(name)
        return Q.mul(self._anim_r[j], self._ik_r[j])


def curve_points(interp):
    """64 バイトの補間から、X・Y・Z・回転 × (x1, y1, x2, y2) の 16 個の制御点。

    64 バイトは同じ 16 個を 1 つずつ左にずらして 4 行並べた形。MMD は 1 行目の 3・4 バイト目（Z と回転の x1）を
    物理演算のオン・オフの印に使う（11-04、全ての親のキーで 1 行目は 0・0、2 行目の写しは 64・20 だった）ので、そこだけ 2 行目から取る。
    """
    points = list(interp[:16])
    points[2], points[3] = interp[17], interp[18]
    return points


def bezier_weight(interp, channel, u):
    """VMD の補間曲線で、キーの間の割合 u（0〜1）を重みに直す。channel: 0=X 1=Y 2=Z 3=回転。

    曲線は (0,0)・(x1,y1)・(x2,y2)・(1,1) の 3 次ベジェ（制御点は 0〜127）。後ろのキーが持つ曲線で、その手前の区間を補間する。
    """
    points = curve_points(interp)
    x1, y1, x2, y2 = (points[channel + 4 * r] / 127.0 for r in range(4))
    if x1 == y1 and x2 == y2:
        return u   # 直線
    lo, hi = 0.0, 1.0
    for _ in range(32):   # x(t) = u となる t を二分法で探す（x(t) は単調増加）
        t = (lo + hi) / 2
        s = 1 - t
        if 3 * s * s * t * x1 + 3 * s * t * t * x2 + t ** 3 < u:
            lo = t
        else:
            hi = t
    t = (lo + hi) / 2
    s = 1 - t
    return 3 * s * s * t * y1 + 3 * s * t * t * y2 + t ** 3


def _split_curve(x1, y1, x2, y2, u):
    """(0,0)・(x1,y1)・(x2,y2)・(1,1) の曲線を x=u で 2 つに分け、それぞれを 0〜1 の箱に直した制御点 ((x1,y1,x2,y2), (…))。"""
    lo, hi = 0.0, 1.0
    for _ in range(40):
        t = (lo + hi) / 2
        s = 1 - t
        if 3 * s * s * t * x1 + 3 * s * t * t * x2 + t ** 3 < u:
            lo = t
        else:
            hi = t
    t = (lo + hi) / 2
    p0, p1, p2, p3 = np.array([0.0, 0.0]), np.array([x1, y1]), np.array([x2, y2]), np.array([1.0, 1.0])
    a, b, c = p0 + (p1 - p0) * t, p1 + (p2 - p1) * t, p2 + (p3 - p2) * t   # de Casteljau
    d, e = a + (b - a) * t, b + (c - b) * t
    m = d + (e - d) * t   # 分ける点
    out = []
    for q1, q2, origin, size in ((a, d, p0, m - p0), (e, c, m, p3 - m)):
        if size[0] <= 1e-9 or size[1] <= 1e-9:   # その側では値が変わらない（どんな曲線でも同じ）
            out.append((0.2, 0.2, 0.8, 0.8))
            continue
        n1, n2 = (q1 - origin) / size, (q2 - origin) / size
        out.append(tuple(float(np.clip(v, 0.0, 1.0)) for v in (n1[0], n1[1], n2[0], n2[1])))
    return out


def split_interp(interp, us):
    """1 つのキーの間の補間曲線を、間の割合 us（0〜1 の昇順）で分けた 64 バイトの補間の一覧（len(us)+1 個・前から順）。

    元のキーの間にキーを足す時に使う。足したキーにはその手前の部分、元の後ろのキーには最後の部分を持たせると、
    MMD が見せる動きは足す前と同じになる（回転は球面の補間なので、同じ大円の上の割合として分けられる）。
    物理演算の印（1 行目の 3・4 バイト目）は元のキーのものを写す。
    """
    points = curve_points(interp)
    curves = [tuple(points[ch + 4 * r] / 127.0 for r in range(4)) for ch in range(4)]
    pieces = [[None] * 4 for _ in range(len(us) + 1)]
    for ch, cur in enumerate(curves):
        done = 0.0
        for i, u in enumerate(us):
            left, cur = _split_curve(*cur, (u - done) / (1 - done)) if done < 1 else ((0.2, 0.2, 0.8, 0.8), cur)
            pieces[i][ch] = left
            done = u
        pieces[-1][ch] = cur
    out = []
    for piece in pieces:
        row = [int(round(piece[ch][r] * 127)) for r in range(4) for ch in range(4)]
        data = bytearray(sum(([*row[k:], *([0] * k)] for k in range(4)), []))
        data[2], data[3] = interp[2], interp[3]
        out.append(bytes(data))
    return out


def sample(motion_tracks, name, frame):
    """VMD のトラックの、あるフレームでの (移動, 回転)。キーの間は MMD と同じく補間曲線どおりに補間する。"""
    keys = motion_tracks.get(name)
    if not keys:
        return np.zeros(3), Q.IDENTITY.copy()
    if frame <= keys[0].frame:
        return keys[0].pos.copy(), keys[0].rot.copy()
    for a, b in zip(keys, keys[1:]):
        if a.frame <= frame <= b.frame:
            u = 0.0 if b.frame == a.frame else (frame - a.frame) / (b.frame - a.frame)
            w = np.array([bezier_weight(b.interp, c, u) for c in range(3)])
            return a.pos + (b.pos - a.pos) * w, Q.slerp(a.rot, b.rot, bezier_weight(b.interp, 3, u))
    return keys[-1].pos.copy(), keys[-1].rot.copy()
