"""MMD のキー（VMD）→ Kimodo → 間のフレームの VMD、の流れ。

キーのフレームそのものは書かない（マスターが打ったキーをそのまま残す）。
「全ての親」は読むだけでキーは打たない。読む時は全ての親も込みの世界の座標で姿勢を出し、
書き戻す時は MMD がそのフレームで全ての親を補間する位置・向きを差し引いて、残りをセンターなどに書く。
全ての親だけにキーがあるフレームは、体の姿勢は決めずに「腰の XZ がここを通る」制約（Kimodo の root2d）にする。
"""
import json
import os
import socket
import subprocess
from dataclasses import dataclass, field

import numpy as np

from . import quat as Q
from . import resident, vmd
from .mmd_skel import MMDSkeleton, sample
from .retarget import TOE_GROUND, Retargeter, conv_p, conv_q

KIMODO_PYTHON = r"F:\kimodo\.venv\Scripts\python.exe"
KIMODO_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "kimodo_gen.py")
KIMODO_DIR = r"F:\kimodo"
KIMODO_PORT = 9551        # 常駐の Kimodo（tools/kimodo_gen.py --serve）
TEXT_SERVER_PORT = 9550   # Kimodo のテキスト読み取りサーバー
KIMODO_HF_CACHE = r"F:\kimodo\hf_cache"
SOMA_JSON = r"F:\kimodo\tools\somaskel30.json"
MAX_FRAMES = 300  # Kimodo は 10 秒（30fps）までで学習している
STOP_HOLD = 10    # 「最後のキーで止まる」で、キーの後ろに腰を止めておくフレーム数
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
    hip_targets: dict = field(default_factory=dict)   # センターの動きを使う時の、フレームごとの腰の目印（世界・Kimodo 座標・m）
    ref_pos: np.ndarray = None    # 最初のキーの腰の XZ（Kimodo 座標・m）
    ref_yaw: float = 0.0          # 最初のキーの腰の向き（ラジアン）。Kimodo には +Z 向き・原点で渡す
    ground_lift: float = 0.0      # 足が床に着くように上げ下げした量（m）
    stop_frames: list = field(default_factory=list)   # 最後のキーで止まるために腰を止めておくフレーム（MMD のフレーム。範囲の外も含む）
    mmd_frames: set = field(default_factory=set)      # 書き戻さず MMD の補間のままにするフレーム（中割りで作れなかった間）
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


def pose_at(skel, tracks, frame, solve_ik=True, skip_ik=()):
    """skip_ik: 解かない IK（Retargeter.idle_iks。読む骨に効かない髪・ネクタイなど）。"""
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
        raise ValueError(f"「{ROOT_BONE}」に親のボーンがあります（一番上の骨である前提）")
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


def snap_segments(segments, key_frames):
    """区間の始めの直後（0〜TRANSITION フレーム後ろ）にキーがあれば、区間の始めをそのキーの次のフレームへずらす。

    Kimodo の multi_prompt は区間を前から 1 つずつ作り、各区間には自分の範囲のキーしか渡さない（kimodo_model.py の crop_move）。
    次の区間は「前の区間の最後の 5 フレームに合わせる」制約から始まるので、区間の始めにキーがあると、
    前の区間がキーを知らずに終わった場所から、キーの場所まで 1 フレームで飛ぶ
    （11-04 試験台: 区間の始め＝キーの 60F で、腰が 1 フレームで 0.9〜2.9m 動いた）。
    キーを前の区間の最後のフレームにすれば、前の区間がキーへ向かって作り、次の区間はキーを含む 5 フレームから始まる。
    segments: [(開始, 長さ, プロンプト)]、key_frames: 制約のあるフレーム（同じ座標）。戻り値: (ずらした区間, [(元, 新, キー)])
    """
    starts = [s for s, _, _ in segments]
    end = segments[-1][0] + segments[-1][1]
    moves = []
    for i in range(1, len(starts)):
        near = [k for k in key_frames if starts[i] <= k <= starts[i] + TRANSITION]
        if near:
            new = max(near) + 1
            if any(new <= k <= new + TRANSITION for k in key_frames):
                raise ValueError(f"{starts[i]}F の区間の始めのすぐ後ろにキーが続いていて、区間の始めを置けません。"
                                 f"毎フレームにキーがある時は、先に「元に戻す」をしてください")
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
        if not text:
            raise ValueError(f"{s}F の区間のプロンプトが空です")
        if not first <= s <= last:
            raise ValueError(f"{s}F の区間が生成する範囲（{first}〜{last}F）の外です")
        if e - s < MIN_SEGMENT:
            raise ValueError(f"{s}F の区間が {e - s} フレームしかありません（{MIN_SEGMENT} フレーム以上にしてください）")
        out.append((s, e - s, text))
    return out


def prepare(pmx, motion, prompt, steps=100, seed=-1, post_processing=True, frame_range=None, cfg=(2.0, 2.0),
            length=None, use_keys=True, use_center=False, stop_at_last_key=False):
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
                キーの後ろに全ての親・手足の目印がある（その先も動かす）時と、センターの動きを使う時は止めない。
    """
    skel = MMDSkeleton(pmx)
    rt = Retargeter(skel, SOMA_JSON)
    tracks = tracks_of(skel, motion)
    body = body_bone_names(skel, rt)
    # 手足を動かす IK（腕の IK・足ＩＫ）だけにキーがあるフレームは、その手足の目印にする。体の他の骨にもキーがあれば全身のポーズ
    limb_iks = set(rt.ik_effector)
    pose_frames = key_frames_of(tracks, body - limb_iks)
    limb_frames = key_frames_of(tracks, limb_iks)
    root_all = key_frames_of(tracks, {ROOT_BONE})
    if frame_range:
        pose_frames = [f for f in pose_frames if frame_range[0] <= f <= frame_range[1]]
        limb_frames = [f for f in limb_frames if frame_range[0] <= f <= frame_range[1]]
        root_all = [f for f in root_all if frame_range[0] <= f <= frame_range[1]]
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
    if num > MAX_FRAMES:
        raise ValueError(f"{num} フレームあります。Kimodo は {MAX_FRAMES} フレーム（10 秒）までです。範囲か長さを絞ってください")
    if not prompt.strip():
        raise ValueError("プロンプトが空です（Kimodo はプロンプト必須）")
    last = first + num - 1
    frames = [f for f in pose_frames if f <= last] if use_keys else []
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
    full = set(frames + [first] + list(limb_keys))   # 全身の姿勢が要るフレーム（手足の IK まで解く）
    for f in sorted(full | set(root_frames)):
        # 通り道だけのフレームは腰の位置と向きしか使わないので、IK は解かない（腰は脚の IK に左右されない）
        G, P = pose_at(skel, tracks, f, solve_ik=f in full, skip_ik=rt.idle_iks)
        poses[f] = rt.mmd_to_soma(G, P)

    job = Job(pmx=pmx, frames=frames, first=first, num_frames=num, root_frames=root_frames,
              root_track=list(tracks.get(ROOT_BONE, [])),
              parent_tracks={n: tracks[n] for n in unwritten_parents(skel, body) if n in tracks})
    hips0, loc0 = poses[first]
    job.ref_pos = np.array([hips0[0], 0.0, hips0[2]])
    job.ref_yaw = _yaw_of(loc0[0])
    # 一番低い足の裏が Kimodo の床（つま先の付け根 TOE_GROUND）に来るように上げ下げする
    job.ground_lift = TOE_GROUND - min(rt.foot_clearance(*poses[f]) for f in (frames or [first]))

    to_canon = Q.from_axis_angle([0, 1, 0], -job.ref_yaw)

    def canon_hips(hips):
        return Q.rotate(to_canon, hips - job.ref_pos) + np.array([0.0, job.ground_lift, 0.0])

    def pose_key(f):
        hips, loc = poses[f]
        loc = [Q.mul(to_canon, loc[0])] + list(loc[1:])
        return {"frame": f - first, "root": [float(v) for v in canon_hips(hips)],
                "local_rot": [float(v) for q in loc for v in q]}

    keys = [pose_key(f) for f in frames]
    ee_keys = [dict(pose_key(f), joints=joints) for f, joints in sorted(limb_keys.items())]
    job.limb_frames = sorted(limb_keys)
    # 全ての親を回している（回転のキーがある）時は、全ての親だけのキーで腰の向きも合わせる。
    # 回していない時（スラロームなど）に向きまで固定すると、毎回正面を向かされるので位置だけにする
    # センターの動きを使う時は、センターの回転も向きとして扱う
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
    if stop_at_last_key and frames and not use_center:
        stop_key = frames[-1]
        later = [f for f in root_frames + list(limb_keys) if f > stop_key]
        hold = list(range(stop_key + 1, min(stop_key + STOP_HOLD, first + MAX_FRAMES - 1) + 1))
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
    if len(job.segments) > 1 and not use_center:   # センターの動きを使う時は毎フレームが目印なので、ずらせない
        constrained = sorted({f for f in frames + root_frames + list(limb_keys) + job.stop_frames})
        job.segments, job.segment_moves = snap_segments(job.segments, constrained)
    segments = [{"prompt": t, "frames": n} for _, n, t in job.segments]
    segments[-1]["frames"] += pad
    job.request = {"prompt": job.segments[0][2], "num_frames": num + pad, "steps": int(steps), "seed": int(seed),
                   "segments": segments,
                   "post_processing": bool(post_processing), "keys": keys, "root_keys": root_keys,
                   "root_y_keys": root_y_keys, "ee_keys": ee_keys, "cfg_weight": [float(cfg[0]), float(cfg[1])]}
    return job


def _port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def kimodo_server():
    env = dict(os.environ, HF_HUB_CACHE=KIMODO_HF_CACHE, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return resident.Server("Kimodo", KIMODO_PORT, KIMODO_PYTHON, KIMODO_SCRIPT, KIMODO_DIR, env)


def run_kimodo(job, work_dir, on_line=None):
    """Kimodo で作って結果を返す。依頼と結果は work_dir に残す（見返す用）。

    テキスト読み取りサーバー（127.0.0.1:9550）が動いていれば、常駐の Kimodo（tools/kimodo_gen.py --serve）に頼む
    （11-04: 1 回 32 秒のうち 25 秒が torch とモデルの読み込みだった）。止まっていれば常駐させず、毎回 1 回だけの形で回す
    （常駐が Llama を抱え込むと、あとでサーバーを起動した時に VRAM が足りなくなるため。tools/kimodo_gen.py の説明）。
    """
    log = on_line or (lambda _l: None)
    os.makedirs(work_dir, exist_ok=True)
    req = os.path.join(work_dir, "request.json")
    res = os.path.join(work_dir, "result.json")
    if os.path.exists(res):
        os.remove(res)
    json.dump(job.request, open(req, "w", encoding="utf-8"))
    if _port_open(TEXT_SERVER_PORT):
        result, line = resident.call(kimodo_server(), job.request, log=log)
        log(line)
        json.dump(result, open(res, "w", encoding="utf-8"))
        return result
    log("テキスト読み取りサーバーが止まっているので、Kimodo を常駐させずに毎回読み込みます（Llama も毎回読むので遅い）")
    env = kimodo_server().env
    proc = subprocess.Popen([KIMODO_PYTHON, KIMODO_SCRIPT, req, res], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env, cwd=KIMODO_DIR, text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = []
    for line in proc.stdout:
        line = line.rstrip()
        if line.startswith("ok ") or "Error" in line or "Traceback" in line or line.startswith("  File "):
            lines.append(line)
            if on_line:
                on_line(line)
    proc.wait()
    if proc.returncode != 0 or not os.path.exists(res):
        raise RuntimeError("Kimodo が失敗しました:\n" + "\n".join(lines[-12:]))
    return json.load(open(res, encoding="utf-8"))


def merge(original, generated, job):
    """元のモーション（丸ごと）に、生成した間のフレームを差し込む。

    MMD に読み込む前に今のキーを全部消すので（mmd_link.load_motion）、元のキー・体以外の骨・表情（tail）を全部残す。
    生成した骨の、範囲の中（両端も含む）でキーのフレームでないところだけを入れ替える。
    完全新規（キーのポーズを使わない）では、最初のフレームの元のキーも入れ替わる。
    """
    # 名前は VMD に入る形（15 バイトで切ったもの）でそろえて比べる。長い名前のボーンで元のキーと生成したキーが二重にならないように
    gen_names = {vmd.vmd_name(k.name) for k in generated.bones}
    keys = set(job.frames)
    lo, hi = job.first, job.first + job.num_frames - 1
    keep = [k for k in original.bones   # 読んだキーの名前はもう VMD の形
            if not (k.name in gen_names and lo <= k.frame <= hi and k.frame not in keys)]
    # キーのフレームで、書き戻す骨にキーが無ければ、元の値（MMD がそのフレームで見せていた値）でキーを足す。
    # 無いままだと、前後の生成したフレームから補間された値が入る（付与の受け渡し元・IK の目標で腕の回転が二重になる）
    orig_tracks = original.tracks()
    have = {(k.name, k.frame) for k in original.bones}
    filled = []
    for f in sorted(keys):
        for name in {k.name for k in generated.bones}:   # 書く時は元の名前から 15 バイトで切る（切った名前を書くと文字化けする）
            vn = vmd.vmd_name(name)
            if (vn, f) not in have:
                t, q = sample(orig_tracks, vn, f)
                filled.append(vmd.BoneKey(name, f, t, q))
    return vmd.Motion(model_name=original.model_name, bones=keep + filled + generated.bones, tail=original.tail)


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
    rt = Retargeter(skel, SOMA_JSON)
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
            # センターの動きを使う時: 腰の高さを目印ぴったりに。足ＩＫは動かさないので、差は MMD の IK が膝の曲げで吸収する
            target_local, _ = to_root_local(rt, target, Q.IDENTITY, root_q, root_p)
            poss["センター"] = poss["センター"] + np.array([0.0, (target_local[1] - hips[1]) / rt.scale, 0.0])
        for name, q in rots.items():
            rows.append((name, job.first + k, poss.get(name, np.zeros(3)), q))
    return rows
