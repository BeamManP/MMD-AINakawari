"""Kimodo・MotionBricks の置き場所。セットアップ（詳細の窓）が work/paths.json に書き、ここから全部の場所を組み立てる。

置き場所の中の形（セットアップが作る形・11-05 までの手作業の F:\\kimodo・F:\\motionbricks と同じ）:
    Kimodo:        .venv\\Scripts\\python.exe・hf_cache\\・text_encoders\\・tools\\somaskel30.json・start_textencoder.cmd
    MotionBricks:  .venv\\Scripts\\python.exe（中身は GitHub の motionbricks そのまま）

設定が無い時に、決まった場所を探しに行ったりはしない（11-05 まで F:\\ に決め打ちだった）。Kimodo が無ければ生成の時に
NotSetUp で止め、セットアップへ案内する。MotionBricks は入れなくてもよいので、無ければ「無い」（None）として扱う。
"""
import json
import os

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK_DIR = os.path.join(HOME, "work")
PATHS_FILE = os.path.join(WORK_DIR, "paths.json")
SETUP_HINT = "詳細の窓のセットアップで入れてください"


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
        raise NotSetUp(f"{PATHS_FILE} が読めません（{e}）。{SETUP_HINT}") from None
    if not isinstance(data, dict):
        raise NotSetUp(f"{PATHS_FILE} の形が違います。{SETUP_HINT}")
    return data


def save(**changes):
    """kimodo=・motionbricks= を書く（None は消す）。ほかの値は残す。壊れていたら書き直す（セットアップで直せるように）。"""
    try:
        data = load()
    except NotSetUp:
        data = {}
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = os.path.abspath(value)
    os.makedirs(WORK_DIR, exist_ok=True)
    tmp = PATHS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PATHS_FILE)


def kimodo_dir():
    folder = load().get("kimodo")
    if not folder:
        raise NotSetUp(f"Kimodo の場所が決まっていません。{SETUP_HINT}")
    if not os.path.isfile(_venv_python(folder)):
        raise NotSetUp(f"Kimodo が {folder} にありません。{SETUP_HINT}")
    return folder


def _venv_python(folder):
    return os.path.join(folder, ".venv", "Scripts", "python.exe")


def kimodo_python():
    return _venv_python(kimodo_dir())


def kimodo_hf_cache():
    return os.path.join(kimodo_dir(), "hf_cache")


def text_encoders():
    """文の読み取り（LLM2Vec ＋ Llama 3）の置き場所。tools/prepare_text_encoder.py が置き、Kimodo の TEXT_ENCODERS_DIR で読ませる。"""
    return os.path.join(kimodo_dir(), "text_encoders")


def soma_json():
    """Kimodo の骨格（tools/export_skeleton.py が書き出す）。"""
    return os.path.join(kimodo_dir(), "tools", "somaskel30.json")


def server_cmd():
    """高速モードのテキスト読み取りサーバーの起動バッチ（tools/start_textencoder.cmd を置いた物）。"""
    return os.path.join(kimodo_dir(), "start_textencoder.cmd")


def motionbricks_dir():
    """MotionBricks の置き場所。入れていなければ None。"""
    folder = load().get("motionbricks")
    return folder if folder and os.path.isfile(_venv_python(folder)) else None


def motionbricks_python():
    folder = motionbricks_dir()
    return _venv_python(folder) if folder else None


def main():
    """手で入れた時の書き方: python -m mmd_ainakawari.paths <Kimodo の場所> [<MotionBricks の場所>]"""
    import argparse
    parser = argparse.ArgumentParser(description="Kimodo・MotionBricks の置き場所を work/paths.json に書く")
    parser.add_argument("kimodo")
    parser.add_argument("motionbricks", nargs="?")
    args = parser.parse_args()
    save(kimodo=args.kimodo, motionbricks=args.motionbricks)
    print(f"書きました: {PATHS_FILE}")
    print(f"  Kimodo: {kimodo_dir()}")
    print(f"  MotionBricks: {motionbricks_dir() or '（入っていません）'}")


if __name__ == "__main__":
    main()
