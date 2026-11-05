"""「生成」1 回分の流れと「元に戻す」。窓（app.py）と確認用のコマンドの両方から呼ぶ。

1. MMD のメモリから選択中のモデルのモーションを丸ごと読み、VMD の控えにする（「元に戻す」用。mmd_memory.py）
2. 体の骨のキーを読んで Kimodo に渡し、間のフレームを作る
3. 元のモーションに間のフレームを差し込み、0F で MMD に読み込ませる
"""
import json
import os
import threading
import time
from dataclasses import dataclass

import numpy as np

from . import nakawari, paths, pipeline, smooth_stop, vmd
from .mmd_link import MMDLink
from .mmd_skel import MMDSkeleton

WORK_DIR = paths.WORK_DIR


@dataclass
class Settings:
    prompt: str
    pmx: str = None             # None なら MMD で選択中のモデル（読み込んだ PMX）
    steps: int = 100
    seed: int = -1
    post_processing: bool = True
    range_start: int = None     # 作り直す範囲（MMD のフレーム）。None なら全部（pipeline.prepare の frame_range）
    range_end: int = None
    cfg_text: float = 2.0       # テキストの効き（Kimodo の既定 2）
    cfg_key: float = 2.0        # キーの効き（Kimodo の既定 2）
    length: int = None          # 作るフレーム数（最初のキーから）。None なら最後のキーまで
    use_keys: bool = True       # False なら体のキーのポーズを使わない（完全新規）
    use_center: bool = False    # True なら毎フレームの腰の位置（センターの上下など）を目印にする
    stop_at_last_key: bool = True   # 最後の体のキーで止まる（キーの後ろに腰を止める目印を足す）
    smooth_stop: bool = True        # 止まる所を MotionBricks で作り直して、なめらかに止まる（smooth_stop.py）
    engine: str = "kimodo"          # "motionbricks" ならキーの間を MotionBricks だけで埋める（中割り・プロンプト無し。nakawari.py）
    key_stop: bool = False          # 中割りで、キーごとに止まる（オフなら次のキーへの速さで通る）
    wrist_lerp: bool = False        # 中割りで、手首だけキーの間を補間でつなぐ（MotionBricks は手首を回しすぎることがある）
    perf_mode: str = "low"          # 動作モード。"low" はテキストの読み取りを CPU（VRAM 8GB 向け）、"fast" は GPU（pipeline.PERF_MODES）


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
_LAST_RUN_LOCK = threading.Lock()


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
    with _LAST_RUN_LOCK:   # 書いている途中を読んで「前回なし」にしないように
        r = _last_runs().get(link.key)
    return r if r and os.path.exists(r.get("backup", "")) and os.path.exists(r.get("output", "")) else None


def _span_key(settings):
    """作る区間を決める設定。範囲（選んだキーの間）ならその範囲、全部ならキーを使うかと長さ（作り方で区間の終わりが変わる）。
    Kimodo か MotionBricks かは入れない（同じ区間を別の作り方で作り直す時も、前回の元のキーに戻したいので）。"""
    if settings.range_start is not None:
        return {"range": [settings.range_start, settings.range_end]}
    return {"range": None, "use_keys": settings.use_keys, "length": settings.length}


def _save_last_run(link, backup, out, span):
    with _LAST_RUN_LOCK:   # 窓（MMD ごと）は同じプロセスのスレッドで生成するので、読んで書き戻す間をまとめて守る
        runs = _last_runs()
        runs[link.key] = {"backup": backup, "output": out, "span": span}
        # 書き終わってから置き換える（途中で止まっても前のものが残る）。一時ファイルは保存ごとに別の名前
        # （窓と確認用のスクリプトのように別のプロセスが同時に保存すると、同じ名前では片方の置き換えが失敗した。11-04 Codex のレビュー）
        tmp = f"{LAST_RUN}.{os.getpid()}.{threading.get_ident()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(runs, f, ensure_ascii=False, indent=1)
        os.replace(tmp, LAST_RUN)


def generate(settings, log=print, link=None, previous=None):
    """previous: 前回の generate の戻り値（省くと last_run.json）。MMD の中身が前回の結果のままなら、前回の元のキーから作り直す。"""
    t0 = time.time()
    link = link or MMDLink()
    previous = previous or load_last_run(link)
    cursor = link.current_frame()   # 押した時のフレーム。読み込みは 0F で行うので、終わったらここへ戻す（11-06 マスター）
    st = link.state()
    if not st["model_selected"]:
        raise RuntimeError("MMD でモデルを選んでください（今はカメラ・照明・アクセサリが選ばれています）")
    pmx = settings.pmx or link.selected_model()["path"]
    if not pmx.lower().endswith(".pmx"):
        raise RuntimeError(f"PMX のモデルだけに対応しています（「{st['model']}」は {os.path.basename(pmx)}）")
    if not os.path.exists(pmx):
        raise FileNotFoundError(f"PMX が見つかりません: {pmx}")
    os.makedirs(WORK_DIR, exist_ok=True)
    # MMD のプロセス番号も付ける（MMD が 2 つあって同じ秒に生成すると、控えと結果のファイルがぶつかって、
    # 「元に戻す」がほかの MMD の動きを読むことがあった。11-04 Codex のレビュー）
    stamp = time.strftime("%Y%m%d_%H%M%S") + "_" + link.key.split("-")[0]
    backup = os.path.join(WORK_DIR, f"original_{stamp}.vmd")

    log(f"MMD から「{st['model']}」のモーションを読み込み中…")
    original = link.read_motion(backup)
    log(f"  キー {len(original.bones)} 個")
    if original.dropped:   # mmd_memory.MotionReader.read
        log(f"注意: 同じ名前のボーンが 2 本以上あります（{'・'.join(sorted(set(original.dropped)))}）。"
            "MMD は同じ名前のキーを前の方のボーンに入れるので、2 本目以降のキーは残せません（生成のあとは 0 に戻ります）")
    skel = MMDSkeleton(pmx)
    fixed_pos = {vmd.vmd_name(b["name"]) for b in skel.bones if not b["flags"] & 0x0004}
    # 照合は書き戻す骨だけ（それ以外は元のキーをそのまま通しているので、比べても意味が無い）
    rt = pipeline.Retargeter(skel, paths.soma_json())
    if rt.missing:   # 無い骨は飛ばして作る（retarget.py の REQUIRED_BONES と脚だけは要る）
        log(f"注意: モデルに無いボーンは飛ばして作ります: {'・'.join(rt.missing)}"
            + ("（上半身2 の分の曲がりは上半身に入れます）" if rt.chest_on_spine else ""))
    written = {vmd.vmd_name(n) for n in pipeline.body_bone_names(skel, rt)}
    rng = (settings.range_start, settings.range_end) if settings.range_start is not None else None
    # 前回の元のキーから作り直すのは、前回と同じ範囲の時だけ。違う範囲で戻すと、前回作った範囲の結果が消えていた
    # （範囲 A を作った後に範囲 B を作ると、B の外の A が元に戻った。11-05 Codex のレビュー）
    # 区間を決める設定（範囲・全部の時はキーを使うかと長さ）が前回と同じ時だけ。前の形の記録（span が無い）は戻さない
    # （全部どうしで長さだけ違っても戻して、今回作らない所の前回の結果まで消えていた。11-05 Codex のレビュー 2 回目）
    span = _span_key(settings)
    same_range = previous is not None and previous.get("span") == span
    if same_range and os.path.exists(previous.get("output", "")) and _same_motion(original, vmd.read(previous["output"]),
                                                                                 fixed_pos=fixed_pos, names=written):
        backup = previous["backup"]
        original = vmd.read(backup)
        log(f"  前回の生成結果のままなので、前回の元のキーから作り直します（{backup}）")
    else:
        log(f"  控え: {backup}")

    mb = settings.engine == "motionbricks"
    job = pipeline.prepare(pmx, original, "inbetween" if mb else settings.prompt, settings.steps, settings.seed,
                           settings.post_processing, frame_range=rng, cfg=(settings.cfg_text, settings.cfg_key),
                           length=settings.length, use_keys=settings.use_keys, use_center=settings.use_center,
                           stop_at_last_key=settings.stop_at_last_key and not mb,
                           max_frames=None if mb else pipeline.MAX_FRAMES,   # 中割りはキーの間ごとに作るので上限なし
                           context_keys=not mb)   # 中割りは範囲の手前の動きを MotionBricks の文脈にする
    # マスターが打った体のキー（外側の文脈と、キーの無いフレームに置いた範囲の端を除く。選んだキーの間なら端も本物のキー）
    keyed = set(original.key_frames())
    real = [f for f in job.frames if f not in job.mmd_frames and (f not in job.anchors or f in keyed)]
    if rng:
        lo, hi = (job.anchors[0], job.anchors[-1]) if len(job.anchors) > 1 else (rng[0], rng[1])
        shown = f"{rng[0]}〜{rng[1]}F・{rng[1] - rng[0] + 1} フレーム"
        log(f"範囲 {rng[0]}〜{rng[1]}F を作り直します: "
            + (f"始まりと終わり（{lo}F・{hi}F）の姿勢を MMD から取り、外の動きにつなぎます"
               if len(job.anchors) > 1 else f"始まり（{lo}F）の姿勢を MMD から取ってつなぎます（後ろにキーが無いので、終わりは決めません）")
            + f"（外側 {pipeline.RANGE_CONTEXT} フレームの動きも渡します）")
        if settings.length is not None and not mb:
            log("  範囲を使う時は、長さの欄は使いません（範囲の終わりまで作ります）")
    else:
        shown = f"{job.first}〜{job.first + job.num_frames - 1}F・{job.num_frames} フレーム"
    if not mb:
        shown += f"・テキストの効き {settings.cfg_text}・キーの効き {settings.cfg_key}"
    if settings.use_keys:
        log(f"体のキー {len(real)} 個: {real}（{shown}）")
    else:
        log(f"完全新規: 体のキーのポーズは使わず、{job.first}F の場所と向きから作ります（{shown}）")
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
    for old, new, key in job.segment_moves:
        log(f"区間の始め {old}F の直後にキー（{key}F）があるので、区間の始めを {new}F にずらしました（キーで跳ばないように）")
    if not mb:
        short = [(s0, n) for s0, n, _ in job.segments if n < pipeline.SHORT_SEGMENT] if len(job.segments) > 1 else []
        for s0, n in short:
            log(f"注意: {s0}F からの区間は {n} フレームしかありません。Kimodo はつなぎに前の区間の 5 フレームを使うので、"
                f"動きが出きらないことがあります（公式のデモは 1 区間 2 秒以上）")
        if any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for _, _, t in job.segments for ch in t):
            log("注意: プロンプトに日本語があります。Kimodo は英語の文で学習しているので、日本語はほとんど効きません"
                "（例: A person poses cutely, tilting the head.）")
        if len(real) > pipeline.MANY_KEYS:
            log(f"注意: 体のキーが {len(real)} 個あります。Kimodo の推奨は {pipeline.MANY_KEYS} 個未満です"
                f"（多いとキーに縛られて動きが硬くなることがあります）")
    if not mb and not any(t.strip() for _, _, t in job.segments):
        log("プロンプトが空なので、キー（と腰・手足の目印）だけを手がかりに作ります（テキストの効きは使いません）")
    if len(job.segments) > 1 and not mb:
        for s, n, text in job.segments:
            log(f"  区間 {s}〜{s + n - 1}F: {text}")

    if mb:
        log("MotionBricks で中割り中…")
        result = nakawari.generate(job, os.path.join(WORK_DIR, "motionbricks"), key_stop=settings.key_stop,
                                   wrist_lerp=settings.wrist_lerp, log=log)
    else:
        log(f"Kimodo で生成中（{'高速' if settings.perf_mode == 'fast' else '低負荷'}モード）…")
        result = pipeline.run_kimodo(job, os.path.join(WORK_DIR, "kimodo"), on_line=lambda l: log("  " + l), mode=settings.perf_mode)
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
    link.set_frame(job.first if cursor is None else cursor)   # 読めなかった時は、作った範囲の始め（前の動き）
    err = result.get("key_max_error_m") or [0]
    root_err = result.get("root_key_error_m") or []
    extra = f"・全ての親のキーとの腰のずれ最大 {max(root_err) * 100:.0f}cm" if root_err else ""
    log(f"できました（{time.time() - t0:.0f} 秒・生成 {result.get('seconds_generate', 0):.1f} 秒・キーとのずれ最大 {max(err) * 100:.1f}cm{extra}）")
    _save_last_run(link, backup, out, span)
    return {"backup": backup, "output": out, "job": job, "span": span}


def undo(backup, log=print, link=None):
    """控えておいた元のモーションを読み込み直す。"""
    link = link or MMDLink()
    if not backup or not os.path.exists(backup):
        raise RuntimeError("戻す控えがありません")
    cursor = link.current_frame()   # 押した時のフレームへ戻す（読めなければ 0F のまま）
    link.load_motion(backup, 0)
    if cursor is not None:
        link.set_frame(cursor)
    log(f"元に戻しました（{backup}）")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="AIナカワリ を窓なしで 1 回動かす（確認用）")
    ap.add_argument("--pmx", help="省くと MMD で選択中のモデル")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--steps", type=int, default=100)
    a = ap.parse_args()
    generate(Settings(pmx=a.pmx, prompt=a.prompt, seed=a.seed, steps=a.steps))
