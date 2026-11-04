"""MMD のモデル ⇔ Kimodo の SOMA 30 関節 の姿勢の写し替え。

考え方: 対応する骨どうしで「全体の回転 × 基準での向きの差」をそろえる。
  SOMA の全体の回転 = MMD の全体の回転（Kimodo 座標に直したもの）× C
  C は「SOMA の基準（T ポーズ）での骨の向き」を「MMD の基準（A ポーズ）での骨の向き」へ回す最小の回転。
  どちらも基準姿勢では全部の回転が 0 なので、MMD が基準のまま → SOMA は MMD と同じ A ポーズになる。
座標: MMD（+X 左・+Y 上・モデルは −Z 向き・左手系）→ Kimodo（+X 左・+Y 上・+Z 前・右手系）は Z を反転。
位置は脚の長さの比で伸び縮みさせる（MMD の単位 → m もこれに含む）。
"""
import json

import numpy as np

from . import quat as Q

# SOMA の関節 → MMD のボーン（左右は「左」「右」を前に付ける）。None は前後の骨から作る
SOMA_TO_MMD = {
    "Hips": "下半身", "Spine1": "上半身", "Spine2": None, "Chest": "上半身2",
    "Neck1": "首", "Neck2": None, "Head": "頭", "Jaw": None, "LeftEye": None, "RightEye": None,
    "LeftShoulder": "左肩", "LeftArm": "左腕", "LeftForeArm": "左ひじ", "LeftHand": "左手首",
    "LeftHandThumbEnd": None, "LeftHandMiddleEnd": None,
    "RightShoulder": "右肩", "RightArm": "右腕", "RightForeArm": "右ひじ", "RightHand": "右手首",
    "RightHandThumbEnd": None, "RightHandMiddleEnd": None,
    "LeftLeg": "左足", "LeftShin": "左ひざ", "LeftFoot": "左足首", "LeftToeBase": None,
    "RightLeg": "右足", "RightShin": "右ひざ", "RightFoot": "右足首", "RightToeBase": None,
}

# 基準での向きを測る「骨の先」: SOMA の子の関節 / MMD の子のボーン。無いものは C = 回転なし
DIRECTION_PAIRS = {
    "LeftShoulder": ("LeftArm", "左腕"), "LeftArm": ("LeftForeArm", "左ひじ"),
    "LeftForeArm": ("LeftHand", "左手首"), "LeftHand": ("LeftHandMiddleEnd", "左中指１"),
    "RightShoulder": ("RightArm", "右腕"), "RightArm": ("RightForeArm", "右ひじ"),
    "RightForeArm": ("RightHand", "右手首"), "RightHand": ("RightHandMiddleEnd", "右中指１"),
    "LeftLeg": ("LeftShin", "左ひざ"), "LeftShin": ("LeftFoot", "左足首"), "LeftFoot": ("LeftToeBase", "左つま先"),
    "RightLeg": ("RightShin", "右ひざ"), "RightShin": ("RightFoot", "右足首"), "RightFoot": ("RightToeBase", "右つま先"),
}

# 書き戻しで 0（回転なし・移動なし）にする中継のボーン。体の動きはセンター・下半身・上半身などに全部載せる
NEUTRAL_BONES = ["グルーブ", "腰", "左肩P", "右肩P", "左腕捩", "右腕捩", "左手捩", "右手捩"]


def conv_p(p):
    """MMD ⇔ Kimodo の位置（Z 反転。行き帰り同じ）。"""
    p = np.asarray(p, float)
    return p * np.array([1.0, 1.0, -1.0])


def conv_q(q):
    """MMD ⇔ Kimodo の回転（Z 反転の鏡写し。行き帰り同じ）。"""
    return np.array([-q[0], -q[1], q[2], q[3]])


def _find(skel, *names):
    for n in names:
        if n in skel:
            return n
    raise KeyError(f"モデルにボーンがありません: {' / '.join(names)}")


class Retargeter:
    def __init__(self, mmd_skel, soma_json_path):
        self.mmd = mmd_skel
        soma = json.load(open(soma_json_path, encoding="utf-8"))
        self.soma_names = soma["names"]
        self.soma_parent = soma["parents"]
        self.neutral = np.array(soma["neutral_flat"], float).reshape(-1, 3)
        self.sidx = {n: i for i, n in enumerate(self.soma_names)}
        self.J = len(self.soma_names)

        for s, m in SOMA_TO_MMD.items():
            if m is not None:
                self.mmd.i(m)  # 無ければここで止める
        self.ik_names = {side: (_find(mmd_skel, f"{side}足ＩＫ", f"{side}足IK"),
                                _find(mmd_skel, f"{side}つま先ＩＫ", f"{side}つま先IK")) for side in "左右"}

        # 基準での向きの差 C（Kimodo 座標）
        self.C = [Q.IDENTITY.copy() for _ in range(self.J)]
        rest = self.mmd.rest
        for s, (s_child, m_child) in DIRECTION_PAIRS.items():
            j = self.sidx[s]
            m = SOMA_TO_MMD[s]
            if m_child not in self.mmd:
                continue
            d_soma = self.neutral[self.sidx[s_child]] - self.neutral[j]
            d_mmd = conv_p(rest[self.mmd.i(m_child)] - rest[self.mmd.i(m)])
            self.C[j] = Q.from_to(d_soma, d_mmd)

        # 体格: 脚の長さの比（MMD の単位 → SOMA の m）
        def leg(points):
            return sum(np.linalg.norm(points[k + 1] - points[k]) for k in range(len(points) - 1))
        soma_leg = leg([self.neutral[self.sidx[n]] for n in ("LeftLeg", "LeftShin", "LeftFoot")])
        mmd_leg = leg([rest[self.mmd.i(n)] for n in ("左足", "左ひざ", "左足首")])
        self.scale = soma_leg / mmd_leg
        # 腰（Hips）から両脚の付け根の真ん中までの差（SOMA の基準）
        self.legmid_offset = (self.neutral[self.sidx["LeftLeg"]] + self.neutral[self.sidx["RightLeg"]]) / 2 - self.neutral[self.sidx["Hips"]]
        # SOMA の基準で、腰を原点にした時のつま先の付け根・足首の高さ（床合わせに使う）
        self.toe_rest = self.neutral[self.sidx["LeftToeBase"]][1] - self.neutral[self.sidx["Hips"]][1]
        self.ankle_rest = self.neutral[self.sidx["LeftFoot"]][1] - self.neutral[self.sidx["Hips"]][1]
        self._plan_writes()

    def _plan_writes(self):
        """書き戻しで何をどう書くかを、モデルの骨の作り（付与・IK）から決める。ボーン名や親子は決め打ちしない。

        - mapped: SOMA の関節に当たる骨。全体の向きを合わせる
        - proxies: mapped の骨が付与（回転・割合 1）で回転を受け取っていて、その受け渡し元が IK の鎖の骨のもの
                   （例: ノイニクの腕・ひじは「腕IK上腕・腕IK」から受け取る）。回転は受け渡し元に入れ、mapped の骨は 0 にする。
                   そうすると、IK の目標をつまんで動かした時に腕が素直についてくる
        - our_iks: 鎖に mapped か受け渡し元の骨を含む IK（足ＩＫ・つま先ＩＫ・腕の IK など）。目標を FK で届いた位置に毎フレーム置く。
                   書き戻しの計算中は解かない（届いている前提）。それ以外の IK（目線・機構など）はマスターのキーのまま解く
        """
        sk = self.mmd
        self.mapped = [m for m in SOMA_TO_MMD.values() if m]
        ik_links = {}   # 鎖の骨 → その IK のボーン
        for i, b in enumerate(sk.bones):
            if b["ik"]:
                for l in b["ik"]["links"]:
                    ik_links.setdefault(l["bone_index"], i)
        self.proxies = {}
        for m in self.mapped:
            b = sk.bones[sk.i(m)]
            if b["inherit"] and b["flags"] & 0x100:
                src, ratio = b["inherit"]
                if abs(ratio - 1.0) < 1e-6 and src in ik_links:
                    self.proxies[m] = sk.names[src]
        chain_bones = {sk.i(m) for m in self.mapped} | {sk.i(s) for s in self.proxies.values()}
        iks = sorted({ik for link, ik in ik_links.items() if link in chain_bones}, key=lambda i: sk.rank[i])
        self.our_iks = [sk.names[i] for i in iks]
        self.neutral_bones = [n for n in NEUTRAL_BONES + ["センター"] if n in sk]
        self.written_bones = set(self.mapped) | set(self.proxies.values()) | set(self.our_iks) | set(self.neutral_bones)
        self.idle_iks = self._idle_iks()
        # IK がどの手足を動かすか: IK のボーンかその目標の基準の位置が、手首・足首の基準の位置に重なるもの（つま先ＩＫなどは当たらない）
        ends = {"LeftHand": "左手首", "RightHand": "右手首", "LeftFoot": "左足首", "RightFoot": "右足首"}
        self.ik_effector = {}
        for k in self.our_iks:
            i = sk.i(k)
            pts = (sk.rest[i], sk.rest[sk.bones[i]["ik"]["target_index"]])
            joint, d = min(((j, min(np.linalg.norm(p - sk.rest[sk.i(m)]) for p in pts)) for j, m in ends.items()), key=lambda x: x[1])
            if d < 0.3:
                self.ik_effector[k] = joint

    def _idle_iks(self):
        """読む・書く骨のどれにも効かない IK（髪・ネクタイ・目線など）。姿勢の計算で解かずに飛ばす。

        IK が動かすのは鎖の骨なので、そこから子と付与の受け取り先（回転・移動）をたどって、影響の届く骨を集める。
        書き戻す骨・SOMA に当たる骨・足 IK などの目標・左右の足（腰の位置の基準）のどれにも届かなければ、解いても結果は変わらない。
        11-04 Tda ミクで、書き戻しの計算の 97% が髪（鎖 8 本・50 回）とネクタイの IK を解く時間だった（1 フレーム 1.35 秒 → 0.04 秒）
        """
        sk = self.mmd
        inheritors = [[] for _ in sk.bones]
        for i, b in enumerate(sk.bones):
            if b["inherit"] and b["flags"] & 0x300:
                inheritors[b["inherit"][0]].append(i)
        needed = {sk.i(n) for n in self.written_bones | set(self.mapped) | {"左足", "右足"} if n in sk}
        needed |= {sk.bones[sk.i(k)]["ik"]["target_index"] for k in self.our_iks}
        idle = []
        for i, b in enumerate(sk.bones):
            if not b["ik"]:
                continue
            reach = set()
            todo = [l["bone_index"] for l in b["ik"]["links"]]
            while todo:
                j = todo.pop()
                if j not in reach:
                    reach.add(j)
                    todo += sk.children[j] + inheritors[j]
            if not reach & needed:
                idle.append(sk.names[i])
        return idle

    # ---------------- SOMA の計算 ----------------

    def soma_fk(self, hips, local):
        """腰の位置と 30 関節のローカル回転 → 全体の回転と位置。"""
        G = [None] * self.J
        P = [None] * self.J
        for j in range(self.J):
            p = self.soma_parent[j]
            if p < 0:
                G[j] = Q.normalize(local[j])
                P[j] = np.asarray(hips, float)
            else:
                G[j] = Q.normalize(Q.mul(G[p], local[j]))
                P[j] = P[p] + Q.rotate(G[p], self.neutral[j] - self.neutral[p])
        return G, P

    def foot_clearance(self, hips, local):
        """足の裏の床からの高さ（SOMA の基準で立った時が 0）。"""
        _, P = self.soma_fk(hips, local)
        h = []
        for side in ("Left", "Right"):
            h.append(P[self.sidx[side + "ToeBase"]][1] - (self.toe_rest - self.toe_rest))
            h.append(P[self.sidx[side + "Foot"]][1] - (self.ankle_rest - self.toe_rest))
        return min(h)

    # ---------------- MMD → SOMA ----------------

    def mmd_to_soma(self, G, P):
        """MMD の姿勢（MMDSkeleton.pose の結果）→ SOMA の腰の位置（m・Kimodo 座標）と 30 関節のローカル回転。"""
        Gs = [None] * self.J
        for s, m in SOMA_TO_MMD.items():
            if m is not None:
                j = self.sidx[s]
                Gs[j] = Q.normalize(Q.mul(conv_q(G[self.mmd.i(m)]), self.C[j]))
        si = self.sidx
        Gs[si["Spine2"]] = Q.slerp(Gs[si["Spine1"]], Gs[si["Chest"]], 0.5)
        Gs[si["Neck2"]] = Q.slerp(Gs[si["Neck1"]], Gs[si["Head"]], 0.5)
        for j in range(self.J):
            if Gs[j] is None:  # 顎・目・指先・つま先は親と同じ向き
                Gs[j] = Gs[self.soma_parent[j]]
        local = [Gs[0]] + [Q.normalize(Q.mul(Q.inv(Gs[self.soma_parent[j]]), Gs[j])) for j in range(1, self.J)]
        legmid = conv_p((P[self.mmd.i("左足")] + P[self.mmd.i("右足")]) / 2) * self.scale
        hips = legmid - Q.rotate(Gs[0], self.legmid_offset)
        return hips, local

    # ---------------- SOMA → MMD ----------------

    def _offset_under_parent(self, name, world, G, P):
        """ボーン name が世界の位置 world に来る、キーの移動（親から見た値）。"""
        i = self.mmd.i(name)
        p = self.mmd.parent[i]
        rest = self.mmd.rest
        if p < 0:
            return world - rest[i]
        return Q.rotate(Q.inv(G[p]), world - P[p]) - (rest[i] - rest[p])

    def soma_to_mmd(self, hips, local, fixed=None):
        """SOMA の姿勢 → MMD のボーンのキー（回転 {名前: 四元数} と移動 {名前: ベクトル}）。

        fixed: {ボーン名: (移動, 回転)}。ここでは書かない親側の骨（足IK親など）の、マスターのキーの値。計算に入れる。
        """
        Gs, _ = self.soma_fk(hips, local)
        sk = self.mmd
        # 対応する骨の、欲しい全体の向き（MMD 座標）
        targets = {}
        for s, m in SOMA_TO_MMD.items():
            if m is not None:
                j = self.sidx[s]
                targets[m] = conv_q(Q.normalize(Q.mul(Gs[j], Q.inv(self.C[j]))))

        rots = {n: Q.IDENTITY.copy() for n in self.neutral_bones + self.our_iks}
        pos = {n: np.zeros(3) for n in rots}
        fixed = {n: v for n, v in (fixed or {}).items() if n not in self.written_bones}
        f_rot = {n: q for n, (t, q) in fixed.items()}
        f_pos = {n: t for n, (t, q) in fixed.items()}

        def fk(world_targets=None):
            # 対応する骨は、親の実際の向き（間の骨・付与・目線や機構の IK 込み）を見てキーを決める。目標を置く IK と効かない IK は解かない
            return sk.pose({**f_rot, **rots}, {**f_pos, **pos}, world_targets=world_targets, skip_ik=self.our_iks + self.idle_iks)

        # センターの移動: 両脚の付け根の真ん中を、SOMA の位置へ合わせる（センターの親の向きで直す）
        legmid_target = conv_p((np.asarray(hips, float) + Q.rotate(Gs[0], self.legmid_offset)) / self.scale)
        G0, P0 = fk(targets)
        c = sk.i("センター")
        pc = sk.parent[c]
        delta = legmid_target - (P0[sk.i("左足")] + P0[sk.i("右足")]) / 2
        pos["センター"] = Q.rotate(Q.inv(G0[pc]), delta) if pc >= 0 else delta
        fk(targets)
        for m in self.mapped:
            rots[m] = sk.anim_rot(m)
        # 付与で受け取る骨は、回転を受け渡し元（IK の鎖の骨）へ移す。割合 1 なので骨の全体の向きは変わらない
        for m, src in self.proxies.items():
            rots[src] = rots[m]
            rots[m] = Q.IDENTITY.copy()
        # 鎖を含む IK の目標を、鎖の先が FK で届いた位置に置く（親の IK が先に動いた時は、その新しい位置から）
        G, P = fk()
        G, P = list(G), list(P)
        for k in self.our_iks:
            i = sk.i(k)
            t = sk.bones[i]["ik"]["target_index"]
            pos[k] = self._offset_under_parent(k, P[t], G, P)
            P[i] = P[t].copy()
        return rots, pos
