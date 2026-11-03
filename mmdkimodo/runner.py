"""「生成」1 回分の流れと「元に戻す」。窓（app.py）と確認用のコマンドの両方から呼ぶ。

1. MMD から選択中のモデルのモーションを丸ごと書き出す（これが「元に戻す」用の控えにもなる）
2. 体の骨のキーを読んで Kimodo に渡し、間のフレームを作る
3. 元のモーションに間のフレームを差し込み、0F で MMD に読み込ませる
"""
import json
import os
import time
from dataclasses import dataclass

import numpy as np

from . import pipeline, smooth_stop, vmd
from .mmd_link import MMDLink
from .mmd_skel import MMDSkeleton

WORK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")


@dataclass
class Settings:
    prompt: str
    pmx: str = None             # None なら MMD で選択中のモデル（読み込んだ PMX）
    steps: int = 100
    seed: int = -1
    post_processing: bool = True
    range_start: int = None     # 使うキーの範囲（MMD のフレーム）。None なら全部
    range_end: int = None
    cfg_text: float = 2.0       # テキストの効き（Kimodo の既定 2）
    cfg_key: float = 2.0        # キーの効き（Kimodo の既定 2）
    length: int = None          # 作るフレーム数（最初のキーから）。None なら最後のキーまで
    use_keys: bool = True       # False なら体のキーのポーズを使わない（完全新規）
    use_center: bool = False    # True なら毎フレームの腰の位置（センターの上下など）を目印にする
    stop_at_last_key: bool = True   # 最後の体のキーで止まる（キーの後ろに腰を止める目印を足す）
    smooth_stop: bool = True        # 止まる所を MotionBricks で作り直して、なめらかに止まる（smooth_stop.py）


def _check_frame_base(link, motion, log):
    """MMD の書き出しは最初のキーを 0F に詰める。0F にキーが無いとフレームがずれるので、センター（無ければ全ての親）の値で確かめる。"""
    tracks = motion.tracks()
    for bone in ("センター", pipeline.ROOT_BONE):
        probe = next((k for k in tracks.get(bone, []) if np.abs(k.pos).max() > 0.05), None)
        if probe is not None:
            break
    if probe is None:
        log("（センターも全ての親も動いていないので、フレームのずれの照合は飛ばしました）")
        return
    live = np.array(link.bone_value(bone, probe.frame))
    if np.abs(live - probe.pos).max() > 0.02:
        raise RuntimeError(
            f"MMD の {probe.frame}F の{bone} {tuple(live)} が、書き出したモーションの値 {tuple(probe.pos.round(2))} と合いません。\n"
            "0F にキーが無いと、MMD の書き出しでフレームが詰まってずれます。0F にキーを打ってからもう一度押してください")


def _same_motion(a, b, tol=1e-3, fixed_pos=(), names=None):
    """MMD に読み込ませて書き出し直したものが、こちらの書いたものと同じか（小数は MMD を通ると少し丸まる）。

    fixed_pos: 移動を比べない骨（移動できない骨）。MMD は読み込みでその一部の移動を 0 にする（ネクタイで確認）。
    names: 比べる骨（VMD の名前）。None なら全部。
    名前が 15 バイトで同じになる別々の骨のキーは、MMD が 1 つにまとめるので、(名前, フレーム) でまとめてから比べる。
    """
    def keyed(m):
        return {(k.name, k.frame): k for k in m.bones if names is None or k.name in names}
    ka, kb = keyed(a), keyed(b)
    if ka.keys() != kb.keys():
        return False
    for key, x in ka.items():
        y = kb[key]
        if x.name not in fixed_pos and np.abs(x.pos - y.pos).max() > tol:
            return False
        if min(np.abs(x.rot - y.rot).max(), np.abs(x.rot + y.rot).max()) > tol:
            return False
    return True


LAST_RUN = os.path.join(WORK_DIR, "last_run.json")


def _last_runs():
    try:
        runs = json.load(open(LAST_RUN, encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return runs if isinstance(runs, dict) and "backup" not in runs else {}  # 11-03 以前の 1 件だけの形は捨てる


def load_last_run(link):
    """その MMD での前回の生成の控えと結果（窓を開き直した時・コマンドで回した後も、作り直しと「元に戻す」に使う）。無ければ None。

    MMD ごと（プロセス番号と起動時刻）に分けて残す。MMD を開き直したら引き継がない（別の場面に古い控えを読み込ませないため）。
    """
    r = _last_runs().get(link.key)
    return r if r and os.path.exists(r.get("backup", "")) and os.path.exists(r.get("output", "")) else None


def _save_last_run(link, backup, out):
    runs = _last_runs()
    runs[link.key] = {"backup": backup, "output": out}
    json.dump(runs, open(LAST_RUN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def generate(settings, log=print, link=None, previous=None):
    """previous: 前回の generate の戻り値（省くと last_run.json）。MMD の中身が前回の結果のままなら、前回の元のキーから作り直す。"""
    t0 = time.time()
    link = link or MMDLink()
    previous = previous or load_last_run(link)
    st = link.state()
    if not st["model_selected"]:
        raise RuntimeError("MMD でモデルを選んでください（今はカメラ・照明・アクセサリが選ばれています）")
    pmx = settings.pmx or link.selected_model()["path"]
    if not pmx.lower().endswith(".pmx"):
        raise RuntimeError(f"PMX のモデルだけに対応しています（「{st['model']}」は {os.path.basename(pmx)}）")
    if not os.path.exists(pmx):
        raise FileNotFoundError(f"PMX が見つかりません: {pmx}")
    os.makedirs(WORK_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = os.path.join(WORK_DIR, f"original_{stamp}.vmd")

    log(f"MMD から「{st['model']}」のモーションを書き出し中…")
    link.export_motion(backup)
    original = vmd.read(backup)
    log(f"  キー {len(original.bones)} 個")
    skel = MMDSkeleton(pmx)
    fixed_pos = {vmd.vmd_name(b["name"]) for b in skel.bones if not b["flags"] & 0x0004}
    # 照合は書き戻す骨だけ（それ以外は元のキーをそのまま通しているので、比べても意味が無い）
    written = {vmd.vmd_name(n) for n in pipeline.body_bone_names(skel, pipeline.Retargeter(skel, pipeline.SOMA_JSON))}
    if previous and os.path.exists(previous.get("output", "")) and _same_motion(original, vmd.read(previous["output"]),
                                                                                fixed_pos=fixed_pos, names=written):
        backup = previous["backup"]
        original = vmd.read(backup)
        log(f"  前回の生成結果のままなので、前回の元のキーから作り直します（{backup}）")
    else:
        log(f"  控え: {backup}")
    _check_frame_base(link, original, log)

    rng = (settings.range_start, settings.range_end) if settings.range_start is not None else None
    job = pipeline.prepare(pmx, original, settings.prompt, settings.steps, settings.seed,
                           settings.post_processing, frame_range=rng, cfg=(settings.cfg_text, settings.cfg_key),
                           length=settings.length, use_keys=settings.use_keys, use_center=settings.use_center,
                           stop_at_last_key=settings.stop_at_last_key)
    span = f"{job.first}〜{job.first + job.num_frames - 1}F・{job.num_frames} フレーム・テキストの効き {settings.cfg_text}・キーの効き {settings.cfg_key}"
    if settings.use_keys:
        log(f"体のキー {len(job.frames)} 個: {job.frames}（{span}）")
    else:
        log(f"完全新規: 体のキーのポーズは使わず、{job.first}F の場所と向きから作ります（{span}）")
    if settings.use_center:
        log(f"センターの動きを使う: {len(job.root_frames)} フレームで腰の位置と高さを目印にします")
    elif job.root_frames:
        log(f"全ての親だけのキー {len(job.root_frames)} 個: {job.root_frames}（腰がそこを通るように作る）")
    if job.stop_frames:
        outside = job.stop_frames[-1] - (job.first + job.num_frames - 1)
        log(f"最後のキー（{job.stop_frames[0] - 1}F）で止まる: {job.stop_frames[0]}〜{job.stop_frames[-1]}F は腰を動かさない"
            + (f"（後ろ {outside} フレームは止まるために余分に作るだけで、書き戻さない）" if outside > 0 else ""))
    if job.limb_frames:
        log(f"手足の IK だけのキー {len(job.limb_frames)} 個: {job.limb_frames}（手足の位置だけ合わせ、体は任せる）")
    if len(job.segments) > 1:
        for s, n, text in job.segments:
            log(f"  区間 {s}〜{s + n - 1}F: {text}")

    log("Kimodo で生成中…")
    result = pipeline.run_kimodo(job, os.path.join(WORK_DIR, "kimodo"), on_line=lambda l: log("  " + l))
    if settings.smooth_stop and job.stop_frames:
        log("MotionBricks で止まり方を作り直し中…")
        result = smooth_stop.apply(job, result, os.path.join(WORK_DIR, "motionbricks"), log=log)
    generated = pipeline.build_motion(job, result)
    merged = pipeline.merge(original, generated, job)
    out = os.path.join(WORK_DIR, f"kimodo_{stamp}.vmd")
    vmd.write(out, merged)
    log(f"間のフレームのキー {len(generated.bones)} 個を差し込みました → {out}")

    log("MMD に読み込み中…")
    link.load_motion(out, 0)
    link.set_frame(job.first)
    err = result.get("key_max_error_m") or [0]
    root_err = result.get("root_key_error_m") or []
    extra = f"・全ての親のキーとの腰のずれ最大 {max(root_err) * 100:.0f}cm" if root_err else ""
    log(f"できました（{time.time() - t0:.0f} 秒・生成 {result.get('seconds_generate', 0):.1f} 秒・キーとのずれ最大 {max(err) * 100:.1f}cm{extra}）")
    _save_last_run(link, backup, out)
    return {"backup": backup, "output": out, "job": job}


def undo(backup, log=print, link=None):
    """控えておいた元のモーションを読み込み直す。"""
    link = link or MMDLink()
    if not backup or not os.path.exists(backup):
        raise RuntimeError("戻す控えがありません")
    link.load_motion(backup, 0)
    log(f"元に戻しました（{backup}）")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="MMDKimodo を窓なしで 1 回動かす（確認用）")
    ap.add_argument("--pmx", help="省くと MMD で選択中のモデル")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--steps", type=int, default=100)
    a = ap.parse_args()
    generate(Settings(pmx=a.pmx, prompt=a.prompt, seed=a.seed, steps=a.steps))
