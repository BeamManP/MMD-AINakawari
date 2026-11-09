"""MMD のキー（VMD）→ Kimodo → 間のフレームの VMD、の流れ。

キーのフレームそのものは書かない（マスターが打ったキーをそのまま残す）。
「全ての親」は読むだけでキーは打たない。読む時は全ての親も込みの世界の座標で姿勢を出し、
書き戻す時は MMD がそのフレームで全ての親を補間する位置・向きを差し引いて、残りをセンターなどに書く。
全ての親だけにキーがあるフレームは、体の姿勢は決めずに「腰の XZ がここを通る」制約（Kimodo の root2d）にする。
"""
import json
import os
import threading
from dataclasses import dataclass, field, replace

import numpy as np

from . import paths
from . import quat as Q
from . import resident, text_keys, vmd
from .mmd_skel import MMDSkeleton, sample, split_interp
from .retarget import TOE_GROUND, Retargeter, conv_p, conv_q

# Kimodo の Python・キャッシュ・骨格などの場所は paths（work/paths.json）から。11-05 まで F:\kimodo に決め打ちだった
KIMODO_SCRIPT = os.path.join(paths.HOME, "tools", "kimodo_gen.py")
# 常駐の Kimodo の口。文の読み取りは常駐の子の llama-server（GGUF・CPU・メインメモリ約 7.6GB）。tools/kimodo_gen.py の説明。
# 11-07 まで低負荷（口 9553・bf16 を CPU）と高速（口 9551・GPU のサーバー 9550）の 2 つのモードがあった
KIMODO_PORT = 9553
KIMODO_NAME = "Kimodo"
MAX_FRAMES = 300  # Kimodo の 1 区間は 10 秒（30fps）まで（公式の limitations.md）。区間を分ければ全体はこれより長くてよい
STOP_HOLD = 10    # 「最後のキーで止まる」で、キーの後ろに腰を止めておくフレーム数
RANGE_CONTEXT = 3  # 範囲を作り直す時に、範囲の端の外側から使う姿勢のフレーム数（外の動きの勢いをつなぐ。MotionBricks の文脈は 4 姿勢）
# 足の裏がほかのキー（中央値）よりこれ以上低いキーは、床に沈んでいるかもしれないと知らせる（m）。床は一番低い足で決めるので、
# そのぶん間のフレームが全部沈む（11-08、200F の左足ＩＫが床から 12cm 下で、0〜180F の腰が 15cm ほど沈んだ）
SUNK_KEY = 0.05
SPLIT_MOVE_TOLERANCE = 0.05   # 曲線を分けた後、範囲の外で元と違ってよい移動（MMD の単位）。超える部分は元の値のキーで埋める
SPLIT_ANGLE_TOLERANCE = 0.5   # 同じく回転（度）
PARALLEL_SECONDS = 10   # 書き戻しの計算の残りがこれ以上かかりそうなら、子プロセスに分けて並べる
ROOT_BONE = "全ての親"
IGNORED_ROOTS = ("操作中心",)


@dataclass
class Job:
    pmx: str
    frames: list                  # 体の骨のキーのある MMD のフレーム（体の姿勢ごと合わせる）
    first: int
    num_frames: int
    root_frames: list = field(default_factory=list)   # 全ての親だけにキーのあるフレーム（腰の XZ だけ合わせる）
    root_track: list = field(default_factory=list)    # 全ての親のキー（書き戻しで差し引く）
    parent_tracks: dict = field(default_factory=dict) # 書かない親側の骨（足IK親など）のキー（書き戻しで計算に入れる）
    limb_frames: list = field(default_factory=list)   # 手足の IK だけにキーのあるフレーム（手足の目印）
    segments: list = field(default_factory=list)      # 区間ごとのプロンプト [(開始フレーム, 長さ, プロンプト)]
    segment_moves: list = field(default_factory=list) # 区間の始めをキーの次へずらした [(元の開始, ずらした開始, キー)]（MMD のフレーム）
    hip_targets: dict = field(default_factory=dict)   # センターに合わせて作る時の、フレームごとの腰の目印（世界・Kimodo 座標・m）
    ref_pos: np.ndarray = None    # 最初のキーの腰の XZ（Kimodo 座標・m）
    ref_yaw: float = 0.0          # 最初のキーの腰の向き（ラジアン）。Kimodo には +Z 向き・原点で渡す
    ground_lift: float = 0.0      # 足が床に着くように上げ下げした量（m）
    sunk_keys: list = field(default_factory=list)     # 足の裏がほかのキーより SUNK_KEY 以上低いキー [(MMD のフレーム, 低さ m)]
    stop_frames: list = field(default_factory=list)   # 最後のキーで止まるために腰を止めておくフレーム（MMD のフレーム。範囲の外も含む）
    mmd_frames: set = field(default_factory=set)      # 書き戻さず MMD の補間のままにするフレーム（中割りで作れなかった間・範囲の外側の文脈）
    anchors: list = field(default_factory=list)       # 範囲を作り直す時に、MMD の姿勢をキーにした範囲の端のフレーム
    context_before: list = field(default_factory=list) # 範囲の始まりの手前の姿勢（Kimodo の形。中割りの文脈）
    context_after: list = field(default_factory=list)  # 範囲の終わりの後ろの姿勢（Kimodo の形。中割りで通り抜ける先）
    request: dict = field(default_factory=dict)


def body_bone_names(skel, retarget):
    """書き戻す骨（対応する骨・中継の骨・センター・付与の受け渡し元・目標を置く IK）。モデルの作りから Retargeter が決める。"""
    return {n for n in retarget.written_bones if n in skel}


def tracks_of(skel, motion):
    """VMD のトラックを PMX のボーン名で引けるようにする（15 バイトで切れた長い名前を元の名前に戻す）。"""
    out = {}
    for name, keys in motion.tracks().items():
        out.setdefault(skel.vmd_alias.get(name, name), []).extend(keys)
    for keys in out.values():
        keys.sort(key=lambda k: k.frame)
    return out


def key_frames_of(tracks, names):
    return sorted({k.frame for n, keys in tracks.items() if n in names for k in keys})


def unwritten_parents(skel, names):
    """書き戻す骨 names の祖先のうち、自分では書かない骨（全ての親を除く）。足IK親・腰キャンセルなど。"""
    out = set()
    for n in names:
        p = skel.parent[skel.i(n)]
        while p >= 0:
            pn = skel.names[p]
            if pn not in names and pn != ROOT_BONE and pn not in IGNORED_ROOTS:
                out.add(pn)
            p = skel.parent[p]
    return out


def extend_plan(frames_by_name, body, start, add):
    """「続きを足す」で作る区間と、そこで上書きされる体のキー。窓の赤い注意と生成で同じ決め方にする（11-07 マスター）。

    frames_by_name: VMD の骨の名前 → キーのフレーム。body: 書き戻す骨（VMD の名前）。
    start: 続きの始まり（範囲の終わり）。None なら体（と全ての親）の最後のキー。add: 足すフレーム数。
    返り値: (始まり, 終わり, 上書きされる体のキーのフレーム)。始まりの姿勢は MMD から取って続け、その後ろ add フレームを作る。
    終わりより後ろにもキーがあれば、終わりの姿勢は MMD のまま（つなぐ）ので、終わりのキーは上書きしない。
    """
    if add is None or add < 1:
        raise ValueError("足す長さは 1 フレーム以上にしてください")
    anchor = body | {ROOT_BONE}
    if start is None:
        keyed = [f for n in anchor for f in frames_by_name.get(n, ())]
        if not keyed:
            raise ValueError("キーが 1 つもありません（0F にキーを打ってください）")
        start = max(keyed)
    end = start + add
    later = any(f > end for n in anchor for f in frames_by_name.get(n, ()))
    hit = sorted({f for n in body for f in frames_by_name.get(n, ()) if start < f < end or (f == end and not later)})
    return start, end, hit


def ik_off_bones(skel, ik_rows, frame):
    """表示/IK の行（vmd.split_tail）で、frame の時にオフの IK のボーン名（PMX の名前）。VMD の名前は 20 バイトで切れているので、切って比べる。"""
    off = vmd.ik_off_at(ik_rows, frame)
    if not off:
        return set()
    return {n for n in skel.index if vmd._name(n.encode("cp932", errors="replace")[:20]) in off}


def pose_at(skel, tracks, frame, solve_ik=True, skip_ik=()):
    """skip_ik: 解かない IK（Retargeter.idle_iks。読む骨に効かない髪・ネクタイなど・そのフレームでオフの IK）。"""
    rots, poss = {}, {}
    for name in tracks:
        if name in IGNORED_ROOTS or name not in skel:
            continue
        poss[name], rots[name] = sample(tracks, name, frame)
    return skel.pose(rots, poss, solve_ik=solve_ik, skip_ik=skip_ik)


def _yaw_of(q):
    f = Q.rotate(q, np.array([0.0, 0.0, 1.0]))
    return float(np.arctan2(f[0], f[2]))


def root_transform(skel, root_track, frame):
    """そのフレームで MMD が補間する全ての親の (全体の回転, 位置)。MMD 座標・MMD 単位。"""
    if ROOT_BONE not in skel:
        return Q.IDENTITY.copy(), np.zeros(3)
    i = skel.i(ROOT_BONE)
    if skel.parent[i] >= 0:
        raise ValueError(f"「{ROOT_BONE}」に親のボーンがあります。「{ROOT_BONE}」がいちばん上のボーンのモデルだけに対応しています")
    t, q = sample({ROOT_BONE: root_track}, ROOT_BONE, frame)
    return q, skel.rest[i] + t


def to_root_local(rt, hips, root_rot, root_q, root_p):
    """Kimodo 座標の腰の位置・向き（世界）を、全ての親が回転なし・移動なしだった時の値に直す。

    MMD では子の位置 = 全ての親の位置 + 全ての親の回転 × (基準での差 + …) なので、その逆をかける。
    """
    rest = rt.mmd.rest[rt.mmd.i(ROOT_BONE)] if ROOT_BONE in rt.mmd else np.zeros(3)
    x = conv_p(hips) / rt.scale
    local = rest + Q.rotate(Q.inv(root_q), x - root_p)
    return conv_p(local) * rt.scale, Q.normalize(Q.mul(Q.inv(conv_q(root_q)), root_rot))


MIN_SEGMENT = 8   # Kimodo は区間のつなぎ目に前の区間の最後の 5 フレームを使うので、それより十分長く
TRANSITION = 5    # Kimodo の num_transition_frames（区間のつなぎ目で、前の区間の最後の何フレームに合わせるか）
SHORT_SEGMENT = 30   # これより短い区間はログで注意する（公式のデモは 1 区間 2 秒以上。limitations.md）
MANY_KEYS = 20       # 体のキーがこれより多いとログで注意する（公式の推奨は 1 種類 20 個未満）


def snap_segments(segments, key_frames):
    """区間の始めの直後（0〜TRANSITION フレーム後ろ）にキーがあれば、区間の始めをそのキーの次のフレームへずらす。

    Kimodo の multi_prompt は区間を前から 1 つずつ作り、各区間には自分の範囲のキーしか渡さない（kimodo_model.py の crop_move）。
    次の区間は「前の区間の最後の 5 フレームに合わせる」制約から始まるので、区間の始めにキーがあると、
    前の区間がキーを知らずに終わった場所から、キーの場所まで 1 フレームで飛ぶ
    （11-04 試験台: 区間の始め＝キーの 60F で、腰が 1 フレームで 0.9〜2.9m 動いた）。
    キーを前の区間の最後のフレームにすれば、前の区間がキーへ向かって作り、次の区間はキーを含む 5 フレームから始まる。
    segments: [(開始, 長さ, プロンプト)]、key_frames: 制約のあるフレーム（同じ座標）。戻り値: (ずらした区間, [(元, 新, キー)])
    """
    if len(segments) <= 1:
        return list(segments), []
    starts = [s for s, _, _ in segments]
    end = segments[-1][0] + segments[-1][1]
    moves = []
    for i in range(1, len(starts)):
        near = [k for k in key_frames if starts[i] <= k <= starts[i] + TRANSITION]
        if near:
            new = max(near) + 1
            if any(new <= k <= new + TRANSITION for k in key_frames):
                raise ValueError(f"{starts[i]}F の直後にキーが続いているので、ここでは区間を分けられません。"
                                 f"毎フレームにキーがある時は、先に「元に戻す」を押してください")
            moves.append((starts[i], new, max(near)))
            starts[i] = new
    out = []
    for i, (st, text) in enumerate(zip(starts, [t for _, _, t in segments])):
        e = starts[i + 1] if i + 1 < len(starts) else end
        if e - st < MIN_SEGMENT:
            raise ValueError(f"区間の始めをキーの次へずらしたら、{st}F の区間が {e - st} フレームになりました"
                             f"（{MIN_SEGMENT} フレーム以上要ります）。区間の始めをキーから離してください")
        out.append((st, e - st, text))
    return out, moves


def prompt_segments(prompt, first, num):
    """プロンプトの欄 → 区間 [(開始フレーム, 長さ, プロンプト)]（フレームは MMD の値）。

    行頭に「45: …」のように開始フレームを書いた行があれば区間に分ける（Kimodo の multi_prompt）。
    書いていない行は直前の区間の続きの文としてつなげる。1 行も無ければ全体に 1 つ。
    最初の区間は範囲の始まりから、最後の区間は範囲の終わりまで。
    """
    import re
    starts, texts = [], []
    for line in prompt.splitlines():
        m = re.match(r"\s*(\d+)\s*[:：]\s*(.*)", line)
        if m:
            starts.append(int(m.group(1)))
            texts.append(m.group(2).strip())
        elif line.strip():
            if texts:
                texts[-1] = (texts[-1] + " " + line.strip()).strip()
            else:
                starts.append(first)
                texts.append(line.strip())
    last = first + num - 1
    if len(starts) <= 1:
        return [(first, num, " ".join(texts) if texts else prompt.strip())]
    if starts != sorted(starts) or len(set(starts)) != len(starts):
        raise ValueError("区間の開始フレームは小さい順に、重ならないように書いてください")
    starts[0] = first   # 最初の区間は範囲の始まりから
    out = []
    for i, (s, text) in enumerate(zip(starts, texts)):
        e = starts[i + 1] if i + 1 < len(starts) else last + 1
        if not first <= s <= last:
            raise ValueError(f"{s}F の区間が生成する範囲（{first}〜{last}F）の外です")
        if e - s < MIN_SEGMENT:
            raise ValueError(f"{s}F の区間が {e - s} フレームしかありません（{MIN_SEGMENT} フレーム以上にしてください）")
        out.append((s, e - s, text))
    return out


def prepare(pmx, motion, prompt, steps=100, seed=-1, post_processing=True, frame_range=None, cfg=(2.0, 2.0),
            length=None, use_keys=True, use_center=False, stop_at_last_key=False, max_frames=MAX_FRAMES, context_keys=True,
            extend=False):
    """cfg: (テキストの効き, キーの効き)。Kimodo の既定は (2, 2)。テキストを上げるとプロンプトの動きが強く出る（回転は 8・1 で振り向くほど）。

    length: 作るフレーム数（最初のキーから数える）。None なら最後のキーまで。最後のキーより長くすると、その先は続きを作る。
    use_keys: False なら体のキーのポーズは使わない（完全新規）。最初のキーは場所・向き・床の基準にだけ使う。
              全ての親のキー（腰の通り道）はどちらでも使う。
    use_center: True なら、体のキーのフレーム以外の毎フレームで、腰の世界の位置（センター・グルーブ・全ての親などの補間込み）を
                XZ と高さの目印にする。センターの上下のリズムを残して動きを作る用（完全新規と組み合わせる想定）。
    stop_at_last_key: True なら最後の体のキーで止まる。キーは「その瞬間にこの姿勢を通る」だけで止まる意味は持たないので、
                走りなどは勢いを残して通り過ぎる。キーの後ろ STOP_HOLD フレームに「腰はキーの位置から動かない」目印を足すと、
                Kimodo はキーの手前で減速して止まる（11-04 実験: 走って 60F のキーに着く動きで、行き過ぎ 1.55m → 0.08m・跳び無し）。
                作る範囲がそのキーで終わる時は、裏で余分に作らせる（書き戻すのは元の範囲だけ）。
                キーの後ろに全ての親・手足の目印がある（その先も動かす）時と、センターに合わせて作る時は止めない。
    frame_range: (始まり, 終わり) の MMD のフレーム。その範囲を作り直す。始まりの姿勢（MMD の補間込み）はいつもキーにし、
                終わりの姿勢は後ろにもキーがある（外の動きが続く）時だけキーにする。長さ（length）は使わない。
                範囲の中のキーも通る（完全新規なら使わない）。範囲の端の外側 RANGE_CONTEXT フレームの姿勢も使い、外の勢いをつなぐ。
    extend: True なら frame_range は「続きを足す」区間（extend_plan）。始まりの姿勢から続けて作り、区間の中の体・手足の IK のキーは
            目印に使わずに上書きする（全ての親のキーは書き戻さない骨なので、そのまま目印にする）。
    context_keys: True なら端の外側の姿勢もキーとして渡し、作る長さに含める（Kimodo。書き戻さない）。
                  False なら姿勢だけ job.context_before・context_after に入れる（中割りの MotionBricks の文脈）。
    """
    skel = MMDSkeleton(pmx)
    rt = Retargeter(skel, paths.soma_json())
    tracks = tracks_of(skel, motion)
    body = body_bone_names(skel, rt)
    # 手足を動かす IK（腕の IK・足ＩＫ）だけにキーがあるフレームは、その手足の目印にする。体の他の骨にもキーがあれば全身のポーズ
    limb_iks = set(rt.ik_effector)
    pose_frames = key_frames_of(tracks, body - limb_iks)
    limb_frames = key_frames_of(tracks, limb_iks)
    root_all = key_frames_of(tracks, {ROOT_BONE})
    anchors, before, after = [], [], []   # 範囲の端の姿勢のフレーム・その外側の文脈のフレーム
    if frame_range:
        # 範囲を作り直す: 範囲の始まり（と、後ろにもキーがあれば終わり）の MMD の姿勢をキーにして、外の動きにつなぐ。
        # 前は範囲の中のキーを絞るだけで、範囲の端は使っていなかった（30〜90F でキーが 45・60F なら 45〜60F だけ作っていた）
        a, b = frame_range
        if a > b:
            raise ValueError(f"範囲の始まり（{a}F）が終わり（{b}F）より後ろです")
        if b - a < 1:
            raise ValueError("範囲は 2 フレーム以上にしてください")
        continues = any(f > b for f in key_frames_of(tracks, body | {ROOT_BONE}))
        anchors = [a, b] if continues else [a]
        before = [f for f in range(a - RANGE_CONTEXT, a) if f >= 0]
        after = list(range(b + 1, b + 1 + RANGE_CONTEXT)) if continues else []
        pose_frames = [f for f in pose_frames if a <= f <= b]
        # 全ての親・手足の IK だけのキーは終わりのフレームも拾う（終わりの姿勢をキーにしない時、75F で原点に戻る
        # 全ての親のキーが抜けて、戻らない動きになっていた。11-04 マスター）。姿勢のキーにした端は、その姿勢で決まるので外す
        limb_frames = [f for f in limb_frames if a < f <= b and f not in anchors]
        root_all = [f for f in root_all if a < f <= b and f not in anchors]
        if extend:   # 足す所の中の体のキーは上書きする（始まりの姿勢だけ守る）
            pose_frames = [f for f in pose_frames if f <= a]
            limb_frames = []
        if not context_keys:   # 文脈は姿勢だけ取る（MotionBricks の手前の文脈・通り抜ける先）
            first, last = a, b
        else:   # 文脈もキーとして渡し、勢いをつなぐ。書き戻すのは範囲の中だけ（mmd_frames）
            first, last = (before or [a])[0], (after or [b])[-1]
        num = last - first + 1
    else:
        body_frames = sorted(set(pose_frames) | set(limb_frames))
        candidates = sorted(set(body_frames) | set(root_all))
        if not candidates:
            raise ValueError("キーが 1 つもありません（0F にキーを打ってください）")
        first = candidates[0]
        if length is not None:
            num = int(length)
            if num < 2:
                raise ValueError("長さは 2 フレーム以上にしてください")
        else:
            num = candidates[-1] - first + 1
            if num < 2:
                raise ValueError("キーが 1 つしかありません。長さ（フレーム）を入れるか、キーをもう 1 つ打ってください")
        last = first + num - 1
    real = [f for f in pose_frames if f <= last] if use_keys else []   # マスターが打った体のキー
    context = (before + after) if context_keys else []
    frames = sorted(set(real) | set(anchors) | set(context))
    # 手足の目印: 体のポーズのキーが無いフレームで、手足の IK にキーがあるもの（完全新規でも使う。0F の初期のキーは体にもあるので入らない）
    limb_keys = {}
    for f in limb_frames:
        if f <= last and f not in set(pose_frames):
            joints = sorted({rt.ik_effector[k] for k in limb_iks if any(x.frame == f for x in tracks.get(k, []))})
            limb_keys[f] = joints
    if use_center:
        root_frames = [f for f in range(first, last + 1) if f not in set(frames)]
    else:
        root_frames = [f for f in root_all if f <= last and f not in set(frames)]

    poses = {}
    full = set(frames + [first] + list(limb_keys) + before + after)   # 全身の姿勢が要るフレーム（手足の IK まで解く）
    # MMD で IK をオフにしたフレームは、その IK を解かずに FK のまま読む（前はいつも解いていた。11-07 Codex のレビュー）
    ik_rows = vmd.split_tail(motion.tail)[1]
    for f in sorted(full | set(root_frames)):
        # 通り道だけのフレームは腰の位置と向きしか使わないので、IK は解かない（腰は脚の IK に左右されない）
        G, P = pose_at(skel, tracks, f, solve_ik=f in full, skip_ik=set(rt.idle_iks) | ik_off_bones(skel, ik_rows, f))
        poses[f] = rt.mmd_to_soma(G, P)

    job = Job(pmx=pmx, frames=frames, first=first, num_frames=num, root_frames=root_frames,
              root_track=list(tracks.get(ROOT_BONE, [])),
              parent_tracks={n: tracks[n] for n in unwritten_parents(skel, body) if n in tracks})
    hips0, loc0 = poses[first]
    job.ref_pos = np.array([hips0[0], 0.0, hips0[2]])
    job.ref_yaw = _yaw_of(loc0[0])
    # 一番低い足の裏が Kimodo の床（つま先の付け根 TOE_GROUND）に来るように上げ下げする
    # 床は 1 枚なので、1 つだけ足が沈んだキー（床に埋まった足ＩＫ）があると、間のフレームが全部そこまで沈む。決め方は変えずに知らせる
    # （中央値で決めると、階段を下りるような本当に高さの違うキーで、下の段のキーが床に埋まる。11-08 マスターと決めた）
    clearance = {f: rt.foot_clearance(*poses[f]) for f in (frames or [first])}
    job.ground_lift = TOE_GROUND - min(clearance.values())
    # 中央値はマスターのキーと範囲の端で取る（範囲の外の文脈のフレームは、外のキーに近いと同じ低さで何個も並んで、中央値を引っ張る）
    middle = float(np.median([c for f, c in clearance.items() if f not in set(context)] or list(clearance.values())))
    job.sunk_keys = [(f, middle - c) for f, c in sorted(clearance.items()) if middle - c >= SUNK_KEY]

    to_canon = Q.from_axis_angle([0, 1, 0], -job.ref_yaw)

    def canon_hips(hips):
        return Q.rotate(to_canon, hips - job.ref_pos) + np.array([0.0, job.ground_lift, 0.0])

    def pose_key(f):
        hips, loc = poses[f]
        loc = [Q.mul(to_canon, loc[0])] + list(loc[1:])
        return {"frame": f - first, "root": [float(v) for v in canon_hips(hips)],
                "local_rot": [float(v) for q in loc for v in q]}

    keys = [pose_key(f) for f in frames]
    job.anchors = anchors
    job.mmd_frames = set(context)   # 外側の文脈は勢いをつなぐためだけ。書き戻さず、元のキーも消さない
    if not context_keys:
        job.context_before = [pose_key(f) for f in before]
        job.context_after = [pose_key(f) for f in after]
    ee_keys = [dict(pose_key(f), joints=joints) for f, joints in sorted(limb_keys.items())]
    job.limb_frames = sorted(limb_keys)
    # 全ての親を回している（回転のキーがある）時は、全ての親だけのキーで腰の向きも合わせる。
    # 回していない時（スラロームなど）に向きまで固定すると、毎回正面を向かされるので位置だけにする
    # センターに合わせて作る時は、センターの回転も向きとして扱う
    turning = job.root_track + (list(tracks.get("センター", [])) if use_center else [])
    use_heading = any(abs(k.rot[3]) < 0.9999 for k in turning)
    root_keys, root_y_keys = [], []
    for f in root_frames:
        hips, loc = poses[f]
        h = canon_hips(hips)
        rk = {"frame": f - first, "xz": [float(h[0]), float(h[2])]}
        if use_heading:
            rk["heading"] = _yaw_of(Q.mul(to_canon, loc[0]))   # Kimodo の向きと同じ定義（正面 +Z が 0）
        root_keys.append(rk)
        if use_center:
            root_y_keys.append({"frame": f - first, "y": float(h[1])})
            job.hip_targets[f] = np.asarray(hips, float)   # 書き戻しで腰の高さをこれに合わせる（世界・Kimodo 座標）
    pad = 0   # 止まるために、元の範囲の後ろへ余分に作らせるフレーム数
    # 範囲の終わりで外の動きにつなぐ時は止めない（終わりの姿勢と、その先の動きが決まっている）
    if stop_at_last_key and real and not use_center and len(anchors) < 2:
        stop_key = real[-1]
        later = [f for f in root_frames + list(limb_keys) if f > stop_key]
        # 余分に作らせても、最後の区間が 1 区間の上限を超えないように（区間の始まりは後でキーの次へずれることがあるが、遅れるだけなので安全側）
        cap = prompt_segments(prompt, first, num)[-1][0] + max_frames - 1 if max_frames else stop_key + STOP_HOLD
        hold = list(range(stop_key + 1, min(stop_key + STOP_HOLD, cap) + 1))
        if not later and hold:
            hips, loc = poses[stop_key]
            h = canon_hips(hips)
            # Kimodo の向きの目印は全部に付けるか全部に付けないか。ほかに腰の目印が無ければ、向きも止める（その場で回らないように）
            with_heading = use_heading or not root_keys
            for f in hold:
                rk = {"frame": f - first, "xz": [float(h[0]), float(h[2])]}
                if with_heading:
                    rk["heading"] = _yaw_of(Q.mul(to_canon, loc[0]))
                root_keys.append(rk)
            job.stop_frames = hold
            pad = max(0, hold[-1] - last)
    job.segments = prompt_segments(prompt, first, num)
    if len(job.segments) > 1 and not use_center:   # センターに合わせて作る時は毎フレームが目印なので、ずらせない
        # 止まるための腰の目印（キーの後ろ STOP_HOLD フレーム）は、キーの場所にじっとしているだけで区間のつなぎとぶつからないので数えない
        # （数えると、区間の始めがキーと同じ時に「すぐ後ろに目印が続いて置けない」で止まっていた。11-04 MMD で確認）
        constrained = sorted({f for f in frames + root_frames + list(limb_keys)})
        job.segments, job.segment_moves = snap_segments(job.segments, constrained)
    segments = [{"prompt": t, "frames": n} for _, n, t in job.segments]
    segments[-1]["frames"] += pad
    # 1 区間の上限は、区間をキーの次へずらして、止まるための延長も足した後の長さで見る
    # （ずらす前に見ていたので、300F で分けて 300F にキーがあると 301 フレームの区間を頼んでいた。11-04 Codex のレビュー）
    long = [(s, seg["frames"]) for (s, _, _), seg in zip(job.segments, segments) if seg["frames"] > max_frames] if max_frames else []
    if long:
        s, n = long[0]
        raise ValueError(f"{s}F からの区間が {n} フレームあります。Kimodo の 1 区間は {max_frames} フレーム（10 秒）までです。"
                         f"区間を分けるか、範囲か長さを絞ってください")
    job.request = {"prompt": job.segments[0][2], "num_frames": num + pad, "steps": int(steps), "seed": int(seed),
                   "segments": segments,
                   "post_processing": bool(post_processing), "keys": keys, "root_keys": root_keys,
                   "root_y_keys": root_y_keys, "ee_keys": ee_keys, "cfg_weight": [float(cfg[0]), float(cfg[1])]}
    return job


def kimodo_env():
    """常駐の Kimodo（と、セットアップの試しの生成）に渡す環境。文の読み取りの場所（tools/kimodo_gen.py の説明）を入れる。"""
    # GPU の番号は nvidia-smi と同じ並びに（gpu.py の診断と同じ GPU を cuda:0 にする）
    return dict(os.environ, HF_HUB_CACHE=paths.kimodo_hf_cache(), AINAKAWARI_LLAMA_SERVER=paths.llama_server(),
                AINAKAWARI_TEXT_GGUF=paths.text_gguf(), AINAKAWARI_LOG_DIR=resident.LOG_DIR,
                PYTHONUTF8="1", PYTHONIOENCODING="utf-8", CUDA_DEVICE_ORDER="PCI_BUS_ID")


def kimodo_server():
    return resident.Server(KIMODO_NAME, KIMODO_PORT, paths.kimodo_python(), KIMODO_SCRIPT, paths.kimodo_dir(), kimodo_env())


_KIMODO_LOCK = threading.Lock()


def run_kimodo(job, work_dir, on_line=None, use_llama=True):
    """常駐の Kimodo（tools/kimodo_gen.py --serve）で作って結果を返す。依頼と結果は work_dir に残す（見返す用）。
    use_llama=False（窓の「プロンプトの読み取り（Llama 3）を使う」を外した）: 読み取り結果のある文だけで作り、常駐の llama-server も止める。"""
    log = on_line or (lambda _l: None)
    installed = paths.has_text_encoder()
    job.request["text_cache_only"] = not (installed and use_llama)
    if job.request["text_cache_only"]:   # 読み取り結果の無い文は、常駐を起こす前に止める
        lost = text_keys.missing(s["prompt"] for s in job.request["segments"])
        if lost:
            why, how = (("「プロンプトの読み取り（Llama 3）を使う」を外している", "詳細の窓でチェックを入れてください") if installed else
                        ("プロンプトの読み取り（Llama 3）を入れていない", "セットアップで入れてください"))
            raise ValueError(f"{why}ので、「サンプルから選ぶ」の文だけが使えます。"
                             f"読み取れない文: {' / '.join(lost)}（自由に書くには、{how}）")
    # 頼み終わるまでを 1 つずつにする（MMD ごとの窓が同時に頼んでも、常駐はどのみち 1 つずつ作る）
    with _KIMODO_LOCK:
        os.makedirs(work_dir, exist_ok=True)
        res = os.path.join(work_dir, "result.json")
        if os.path.exists(res):
            os.remove(res)
        json.dump(job.request, open(os.path.join(work_dir, "request.json"), "w", encoding="utf-8"))
        result, line = resident.call(kimodo_server(), job.request, log=log)
        log(line)
        json.dump(result, open(res, "w", encoding="utf-8"))
        return result


def _key_difference(a, b):
    """2 つの (移動, 回転) が、見て分かるほど違うか（移動 SPLIT_MOVE_TOLERANCE・回転 SPLIT_ANGLE_TOLERANCE 度を超える）。"""
    (ta, qa), (tb, qb) = a, b
    if np.abs(ta - tb).max() > SPLIT_MOVE_TOLERANCE:
        return True
    qa, qb = qa / np.linalg.norm(qa), qb / np.linalg.norm(qb)
    half = min(np.linalg.norm(qa - qb), np.linalg.norm(qa + qb)) / 2   # 四元数の差から角度（float32 でも 1 の近くで安定）
    return np.degrees(4 * np.arcsin(min(1.0, half))) > SPLIT_ANGLE_TOLERANCE


def merge(original, generated, job):
    """元のモーション（丸ごと）に、生成した間のフレームを差し込む。

    MMD に読み込む前に今のキーを全部消すので（mmd_link.load_motion）、元のキー・体以外の骨・表情（tail）を全部残す。
    生成した骨の、範囲の中（両端も含む）でキーのフレームでないところだけを入れ替える。
    完全新規（キーのポーズを使わない）では、最初のフレームの元のキーも入れ替わる。
    MMD の補間のまま残すフレーム（job.mmd_frames。中割りで作れなかった間・範囲の外側の文脈）は書き戻さないので、元のキーも消さない
    （11-04 Codex のレビュー: 消していたので、残す間にあった足ＩＫだけのキーなどが無くなっていた）。
    """
    # 名前は VMD に入る形（15 バイトで切ったもの）でそろえて比べる。長い名前のボーンで元のキーと生成したキーが二重にならないように
    gen_names = {vmd.vmd_name(k.name) for k in generated.bones}
    keys = set(job.frames)
    lo, hi = job.first, job.first + job.num_frames - 1
    keep = [k for k in original.bones   # 読んだキーの名前はもう VMD の形
            if not (k.name in gen_names and lo <= k.frame <= hi and k.frame not in keys and k.frame not in job.mmd_frames)]
    # キーのフレームで、書き戻す骨にキーが無ければ、元の値（MMD がそのフレームで見せていた値）でキーを足す。
    # 無いままだと、前後の生成したフレームから補間された値が入る（付与の受け渡し元・IK の目標で腕の回転が二重になる）
    orig_tracks = original.tracks()
    have = {(k.name, k.frame) for k in original.bones}
    filled = []
    new_interp = {}   # 元のキー（id）→ 足したキーの後ろの部分の曲線
    generated_at = {}
    for k in generated.bones:
        generated_at.setdefault(k.name, set()).add(k.frame)
    for name in {k.name for k in generated.bones}:   # 書く時は元の名前から 15 バイトで切る（切った名前を書くと文字化けする）
        vn = vmd.vmd_name(name)
        track = orig_tracks.get(vn, [])
        added = [f for f in sorted(keys) if (vn, f) not in have and f not in job.mmd_frames]
        for f in added:
            t, q = sample(orig_tracks, vn, f)
            filled.append(vmd.BoneKey(name, f, t, q))
        # 元のキーの間に足したキーは、元の曲線をそこで分けた部分を持たせる。範囲の端（とキーのフレームの外側）で、
        # MMD の補間のまま残る所の動きの形を変えないため（足したキーが直線の補間だと、範囲の手前の動きが直線になっていた）
        for p, n in zip(track, track[1:]):
            inside = [f for f in added if p.frame < f < n.frame]
            if not inside:
                continue
            us = [(f - p.frame) / (n.frame - p.frame) for f in inside]
            pieces = split_interp(n.interp, us)
            by_frame = dict(zip(inside, pieces))
            for key in filled:
                if key.name == name and key.frame in by_frame:
                    key.interp = by_frame[key.frame]
            new_interp[id(n)] = pieces[-1]
            # 分けた曲線で元の形を表せない部分は、MMD の補間のまま残るフレームに元の値のキーを打つ（その区間だけキーが増えるが、動きは元のまま）。
            # 表せるかは、残るフレームごとに元の値と分けた後の値を比べて決める（曲線の上の決まった 15 点で測っていた時は、
            # 長い区間の急な所を見逃して範囲の外が 16° ずれた。11-05 Codex のレビュー 2 回目）
            bounds = [p.frame] + inside + [n.frame]
            for i, piece in enumerate(pieces):
                a, b = bounds[i], bounds[i + 1]
                left = p if i == 0 else vmd.BoneKey(vn, a, *sample(orig_tracks, vn, a))
                right = replace(n if i == len(pieces) - 1 else vmd.BoneKey(vn, b, *sample(orig_tracks, vn, b)), interp=piece)
                trial = {vn: [left, right]}
                kept = [f for f in range(a + 1, b) if f not in generated_at[name] and (vn, f) not in have]
                if any(_key_difference(sample(orig_tracks, vn, f), sample(trial, vn, f)) for f in kept):
                    for f in kept:
                        filled.append(vmd.BoneKey(name, f, *sample(orig_tracks, vn, f)))
    keep = [replace(k, interp=new_interp[id(k)]) if id(k) in new_interp else k for k in keep]
    return vmd.Motion(model_name=original.model_name, bones=keep + filled + generated.bones, tail=original.tail,
                      name_raw=original.name_raw)


def build_motion(job, result, include_keys=False, workers=None):
    """Kimodo の結果 → MMD のボーンのキー（間のフレームと、全ての親だけ・手足の IK だけのキーのフレーム）。

    Kimodo の動きは世界の座標なので、そのフレームの全ての親の補間値を差し引いてから MMD の骨に直す。
    フレームごとに独立なので、フレームを分けて複数のプロセスで計算する（機構の IK が多いモデルでは 1 フレームが重い）。
    呼ぶ側のスクリプトは `if __name__ == "__main__":` で守ること（Windows は子プロセスが呼んだスクリプトを読み直す）。
    """
    T, J = result["num_frames"], len(result["names"])
    root = np.array(result["root"]).reshape(T, 3)
    rot = np.array(result["local_rot"]).reshape(T, J, 4)
    key_set = {f - job.first for f in job.frames}
    # 最後のキーで止まるために余分に作らせたフレーム（job.num_frames より後ろ）は書き戻さない
    ks = [k for k in range(min(T, job.num_frames)) if (include_keys or k not in key_set) and job.first + k not in job.mmd_frames]
    out = vmd.Motion(model_name=MMDSkeleton(job.pmx).model_name)
    rows = []
    if workers is None:
        # 先に数フレームだけ作って測り、残りが PARALLEL_SECONDS 未満なら 1 プロセスのまま（子プロセスはモデルを読み直すので数秒かかる）。
        # 11-04: Tda ミクは効かない IK を飛ばして 1 フレーム 19ms（並べない）、ノイニクは機構の IK が残って 286ms（並べる）
        import time
        probe, ks = ks[:4], ks[4:]
        t = time.perf_counter()
        rows = _build_frames((job, result["names"], root, rot, probe))
        rest = (time.perf_counter() - t) / max(1, len(probe)) * len(ks)
        workers = 1 if rest < PARALLEL_SECONDS else max(1, min(8, (os.cpu_count() or 2) // 2))   # PC 全体を使い切らない
    workers = max(1, min(workers, len(ks) // 8))   # 少ないフレームは子プロセスを立てる方が遅い
    if workers == 1:
        rows += _build_frames((job, result["names"], root, rot, ks))
    else:
        from concurrent.futures import ProcessPoolExecutor
        # 子プロセスの numpy の内部スレッドは 1 本に（小さい計算ばかりなので、取り合うと並べた分だけ遅くなる）
        for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
            os.environ.setdefault(var, "1")
        chunks = [ks[i::workers] for i in range(workers)]
        with ProcessPoolExecutor(max_workers=workers) as ex:
            rows += [r for part in ex.map(_build_frames, [(job, result["names"], root, rot, c) for c in chunks]) for r in part]
    rows.sort(key=lambda r: r[1])
    out.bones = [vmd.BoneKey(name, frame, pos, q) for name, frame, pos, q in rows]
    return out


def _build_frames(args):
    """build_motion の 1 プロセス分。(名前, フレーム, 移動, 回転) の一覧を返す。"""
    job, names, root, rot, ks = args
    skel = MMDSkeleton(job.pmx)
    rt = Retargeter(skel, paths.soma_json())
    if names != rt.soma_names:
        raise ValueError("Kimodo の結果の関節の並びが SOMA の骨格ファイルと違います")
    from_canon = Q.from_axis_angle([0, 1, 0], job.ref_yaw)
    rows = []
    for k in ks:
        hips = Q.rotate(from_canon, root[k] - np.array([0.0, job.ground_lift, 0.0])) + job.ref_pos
        root_q, root_p = root_transform(skel, job.root_track, job.first + k)
        hips, hips_rot = to_root_local(rt, hips, Q.mul(from_canon, rot[k, 0]), root_q, root_p)
        loc = [hips_rot] + list(rot[k, 1:])
        fixed = {n: sample(job.parent_tracks, n, job.first + k) for n in job.parent_tracks}
        rots, poss = rt.soma_to_mmd(hips, loc, fixed)
        target = job.hip_targets.get(job.first + k)
        if target is not None:
            # センターに合わせて作る時: 腰の高さを目印ぴったりに。足ＩＫは動かさないので、差は MMD の IK が膝の曲げで吸収する
            target_local, _ = to_root_local(rt, target, Q.IDENTITY, root_q, root_p)
            poss["センター"] = poss["センター"] + np.array([0.0, (target_local[1] - hips[1]) / rt.scale, 0.0])
        for name, q in rots.items():
            rows.append((name, job.first + k, poss.get(name, np.zeros(3)), q))
    return rows
