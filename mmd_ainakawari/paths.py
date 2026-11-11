"""Kimodo・MotionBricks の置き場所。セットアップ（詳細の窓）が work/paths.json に書き、ここから全部の場所を組み立てる。

置き場所の中の形（セットアップが作る形・11-05 までの手作業の F:\\kimodo・F:\\motionbricks と同じ）:
    Kimodo:        .venv\\Scripts\\python.exe・hf_cache\\・text_encoder\\（GGUF）・llamacpp\\llama-server.exe・tools\\somaskel30.json
    MotionBricks:  .venv\\Scripts\\python.exe（中身は GitHub の motionbricks そのまま）

計算の方式（kimodo_backend・motionbricks_backend）も同じファイルに書く。セットアップの試しの生成が、通った方式を書く:
    cuda      NVIDIA の GPU（Kimodo は PyTorch の CUDA・MotionBricks は TensorRT）。書いていない時はこれ（0.2.x までと同じ）
    directml  DirectX 12 の GPU（NVIDIA・AMD・Intel）を ONNX Runtime の DirectML で使う（tools/kimodo_ort.py・tools/mb_ort.py。11-10）
    cpu       GPU を使わない（Kimodo は PyTorch の CPU で、数十秒〜数分かかる。MotionBricks は ONNX Runtime の CPU）

設定が無い時に、決まった場所を探しに行ったりはしない（11-05 まで F:\\ に決め打ちだった）。Kimodo が無ければ生成の時に
NotSetUp で止め、セットアップへ案内する。MotionBricks は入れなくてもよいので、無ければ「無い」（None）として扱う。
"""
import json
import os

from .i18n import N_, _

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK_DIR = os.path.join(HOME, "work")
PATHS_FILE = os.path.join(WORK_DIR, "paths.json")
# 入れ方の案内（セットアップの画面は mmd_ainakawari/installer。11-06 にできた）
SETUP_HINT = N_("詳細の窓の下の「セットアップ」で入れてください")
KEYS = ("kimodo", "motionbricks")
CACHE_KEY = "cache_dir"   # 生成ごとの VMD の置き場（cache_dir()）
BACKENDS = ("cuda", "directml", "cpu")
BACKEND_LABEL = {"cuda": N_("CUDA（NVIDIA）"), "directml": "DirectML", "cpu": "CPU"}
BACKEND_ENV = "AINAKAWARI_BACKEND"   # 試す時に、設定より先に見る（窓のプロセスの環境変数。常駐にも同じ名前で渡す）


class NotSetUp(RuntimeError):
    """Kimodo の置き場所が決まっていない・決まった場所に無い。"""


def load():
    """work/paths.json の中身（無ければ空）。小さいので、毎回読む（セットアップが書いた直後から効く）。"""
    try:
        with open(PATHS_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except ValueError as e:   # 壊れた JSON（手で書き換えた時など）
        raise NotSetUp(_("{file} が読めません（{error}）。{hint}", file=PATHS_FILE, error=e, hint=_(SETUP_HINT))) from None
    if not isinstance(data, dict) or any(not isinstance(data[k], str) or not data[k] for k in KEYS + (CACHE_KEY,) if k in data):
        raise NotSetUp(_("{file} の形が違います。{hint}", file=PATHS_FILE, hint=_(SETUP_HINT)))
    return data


def save(**changes):
    """kimodo=・motionbricks= を書く（None は消す。渡さなかった物は残す）。壊れていたら書き直す（セットアップで直せるように）。
    場所が正しいか（中に .venv があるか）は呼ぶ側が先に確かめる（check）。"""
    try:
        data = load()
    except NotSetUp:
        data = {}
    for key, value in changes.items():
        if key not in KEYS:
            raise ValueError(f"paths.save に渡せるのは {KEYS}（{key!r}）")   # i18n: skip
        if value is None:
            data.pop(key, None)
        else:
            data[key] = os.path.abspath(value)
    _write(data)


def _write(data):
    os.makedirs(WORK_DIR, exist_ok=True)
    tmp = PATHS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATHS_FILE)


def backend(name):
    """name（"kimodo"・"motionbricks"）の計算の方式（BACKENDS のどれか）。書いていなければ cuda。
    環境変数 AINAKAWARI_BACKEND があれば、設定より先にそれを使う（試す時用）。"""
    if name not in KEYS:
        raise ValueError(name)
    value = os.environ.get(BACKEND_ENV) or load().get(name + "_backend", "cuda")
    if value not in BACKENDS:
        raise NotSetUp(_("計算の方式が正しくありません（{value}。{choices} のどれか）。{hint}",
                         value=repr(value), choices=" / ".join(BACKENDS), hint=_(SETUP_HINT)))
    return value


def save_backend(name, value):
    """name（"kimodo"・"motionbricks"）の計算の方式を書く（セットアップの試しの生成が、通った方式を書く）。"""
    if name not in KEYS or value not in BACKENDS:
        raise ValueError(f"{name!r} {value!r}")
    try:
        data = load()
    except NotSetUp:
        data = {}
    data[name + "_backend"] = value
    _write(data)


def cache_dir():
    """生成ごとの VMD（元の控え original_*・結果 kimodo_*・「元に戻す」の前の控え before_undo_*）を書く所。
    詳しい設定で決める（paths.json の cache_dir。11-11 マスター）。決めていなければ work。無ければ作る。
    last_run.json・settings.json・app.log は work のまま（last_run.json は控えを絶対パスで指すので、途中で変えても前回の分は戻せる）。"""
    folder = load().get(CACHE_KEY) or WORK_DIR
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        raise NotSetUp(_("一時ファイルの置き場 {folder} を作れません（{error}）。詳しい設定で置き場を選び直してください", folder=folder, error=e)) from None
    return folder


def save_cache_dir(folder):
    """一時ファイルの置き場を書く。None なら既定（work）に戻す。書ける所かは先に確かめる（書けなければ OSError）。"""
    try:
        data = load()
    except NotSetUp:
        data = {}
    if folder is None:
        data.pop(CACHE_KEY, None)
    else:
        folder = os.path.abspath(folder)
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, f".ainakawari_write_test_{os.getpid()}")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        data[CACHE_KEY] = folder
    _write(data)


def check(folder, name):
    """folder に name（Kimodo・MotionBricks）の環境があるか。無ければ NotSetUp。"""
    if not os.path.isfile(_venv_python(folder)):
        raise NotSetUp(_("{name} が {folder} にありません（{python} が無い）", name=name, folder=folder, python=_venv_python(folder)))


def kimodo_dir():
    folder = load().get("kimodo")
    if not folder:
        raise NotSetUp(_("Kimodo の場所が決まっていません。{hint}", hint=_(SETUP_HINT)))
    if not os.path.isfile(_venv_python(folder)):
        raise NotSetUp(_("Kimodo が {folder} にありません。{hint}", folder=folder, hint=_(SETUP_HINT)))
    return folder


def _venv_python(folder):
    return os.path.join(folder, ".venv", "Scripts", "python.exe")


def kimodo_python():
    return _venv_python(kimodo_dir())


def kimodo_hf_cache():
    return os.path.join(kimodo_dir(), "hf_cache")


def text_gguf():
    """文の読み取り（LLM2Vec ＋ Llama 3 の GGUF Q8_0）。セットアップの「文の読み取りのモデルを落とす」が置く。"""
    from .installer.pins import TEXT_GGUF_FILE
    return os.path.join(kimodo_dir(), "text_encoder", TEXT_GGUF_FILE[0])


def llama_server():
    """文の読み取りを動かす llama.cpp の llama-server（CPU 版）。セットアップの「llama.cpp を落とす」が置く。"""
    return os.path.join(kimodo_dir(), "llamacpp", "llama-server.exe")


def has_text_encoder():
    """文の読み取り（Llama 3 の GGUF・llama-server）が入っているか。GGUF は照らしてから名前を付けるので、あれば全部そろっている。
    入っていない時（セットアップで外した。11-10）は、読み取り結果のある文（サンプル）だけで作る（text_keys.py）。
    Kimodo の場所が決まっていなければ NotSetUp。"""
    return os.path.isfile(text_gguf()) and os.path.isfile(llama_server())


def soma_json():
    """Kimodo の骨格（tools/export_skeleton.py が書き出す）。"""
    return os.path.join(kimodo_dir(), "tools", "somaskel30.json")


def motionbricks_dir():
    """MotionBricks の置き場所。入れていなければ None。paths.json が壊れていれば NotSetUp（窓を作る時は smooth_stop.available() で包む）。"""
    folder = load().get("motionbricks")
    return folder if folder and os.path.isfile(_venv_python(folder)) else None


def motionbricks_python():
    folder = motionbricks_dir()
    return _venv_python(folder) if folder else None


def main():
    """手で入れた時の書き方: python -m mmd_ainakawari.paths <Kimodo の場所> [<MotionBricks の場所>]"""
    import argparse
    parser = argparse.ArgumentParser(description="Kimodo・MotionBricks の置き場所を work/paths.json に書く（確かめてから書く）")
    parser.add_argument("kimodo")
    parser.add_argument("motionbricks", nargs="?", help="省くと今の設定のまま")
    parser.add_argument("--no-motionbricks", action="store_true", help="MotionBricks の設定を消す")
    args = parser.parse_args()
    changes = {"kimodo": args.kimodo}
    try:
        check(args.kimodo, "Kimodo")
        if args.motionbricks:
            check(args.motionbricks, "MotionBricks")
            changes["motionbricks"] = args.motionbricks
        elif args.no_motionbricks:
            changes["motionbricks"] = None
    except NotSetUp as e:
        raise SystemExit(f"書きませんでした: {e}")   # i18n: skip
    save(**changes)
    print(f"書きました: {PATHS_FILE}")   # i18n: skip
    print(f"  Kimodo: {kimodo_dir()}")
    print(f"  MotionBricks: {motionbricks_dir() or '（入っていません）'}")   # i18n: skip
    print(f"  計算の方式: Kimodo {backend('kimodo')}・MotionBricks {backend('motionbricks')}")   # i18n: skip


if __name__ == "__main__":
    main()
