"""セットアップの本体（画面は window.py）。Kimodo（と MotionBricks）を 1 つのフォルダに入れて、work\\paths.json に書く。

入れる形（<場所> はセットアップで選んだフォルダ。半角の英数字のパスだけ）:
    <場所>\\kimodo\\         .venv・repo（GitHub の zip）・hf_cache（Kimodo のモデル）・text_encoder（文の読み取りの GGUF）・
                           llamacpp（llama.cpp の CPU 版）・tools\\somaskel30.json   … paths.py の Kimodo の形
    <場所>\\motionbricks\\   GitHub の zip の中身・LFS の 3 ファイル・.venv（uv sync）・.trt-cache（TensorRT の準備）
    <場所>\\uv\\             uv の控え（cache）と uv が落とした Python（python）
    <場所>\\hf_home\\        セットアップ中の huggingface_hub の置き場所（ユーザーのフォルダに物を作らない）
    <場所>\\downloads\\      落とした zip（展開したら消す）
    <場所>\\setup_state.json  済んだ段（段の名前 → 版）
段ごとに済んだ印を残すので、途中で止まっても（失敗・中止・PC の再起動）、もう一度押せば続きから進む。
ある段をやり直したら、同じ組（Kimodo・MotionBricks）の後ろの段の印も消す（前の段の作り直しで、後ろの段の物が壊れうるため）。
git・Python・Hugging Face のアカウントは要らない（uv は zip に同梱。Python は uv が落とす）。

手で回す時（窓と同じ Python で。--reuse-text-gguf は開発用: 手元の GGUF を照らしてから写し、8GB を落とし直さない）:
    python -m mmd_ainakawari.installer.steps D:\\AINakawari [--reuse-text-gguf F:\\kimodo\\text_encoder\\<名前>.gguf]
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile

from .. import __version__, gpu, i18n, paths
from ..i18n import N_, _
from . import pins

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(HERE, "kimodo-requirements.txt")
# ONNX Runtime（DirectML）と ONNX。NVIDIA 以外の GPU・今の CUDA では動かない GPU で動かすため（tools/kimodo_ort.py・tools/mb_ort.py。11-10）
ORT_KIMODO = os.path.join(HERE, "ort-kimodo.txt")
ORT_MOTIONBRICKS = os.path.join(HERE, "ort-motionbricks.txt")
FETCH_MODEL = os.path.join(HERE, "fetch_kimodo_model.py")
FETCH_DONE = N_("できました: {path}")   # fetch_kimodo_model.py が落とし終えた時に出す文（Kimodo の Python で回るので、文は引数で渡す）
TOOLS = os.path.join(paths.HOME, "tools")
STATE_FILE = "setup_state.json"
FINISHED = "_finished"   # setup_state.json の中の「最後まで済んだ時の AIナカワリ の版」（段の名前とぶつからない名前）
# setup_state.json の中の「プロンプトの読み取り（Llama 3）を入れるか」（11-10 マスター。外すとサンプルの文だけで作る）。
# 印の無い場所（11-09 までに入れた場所）は入れた物として扱う
WITH_TEXT = "_with_text_encoder"
# setup_state.json の中の「試しの生成が通った計算の方式」（paths.BACKENDS のどれか）。register が窓の paths.json へ写す
BACKEND_STATE = {"kimodo": "_backend_kimodo", "motionbricks": "_backend_motionbricks"}
BACKEND_ORDER_ENV = "AINAKAWARI_SETUP_BACKENDS"   # 試す順を決め打ちする（開発用。例: directml,cpu）
TEXT_STEPS = ("text_gguf", "llamacpp")
# 組み立て済みの部品の置き場所（配布の zip では MMD-AINakawari\prebuilt\。開発版は work\prebuilt\）。
# kimodo は入れる時に C++ の部品（MotionCorrection。生成の「後処理」が使う）を CMake とコンパイラで組み立てるが、
# 使う人の PC にコンパイラは無いので、組み立て済みの pyd を配って置く（11-06。試しのセットアップで CMake が無くて止まった）
PREBUILT = "prebuilt"
MOTION_CORRECTION_JSON = "motion_correction.json"   # {"file": pyd の名前, "sha256": …, "kimodo_commit": 作った元のコミット}
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
# 入れる場所に使える字。日本語・空白・cmd で意味を持つ字（& ( ) ! ^ % など）は、途中の部品（cmd・TensorRT など）で壊れうる
FOLDER_RE = re.compile(r"^[A-Za-z]:\\[A-Za-z0-9_.\-\\]*$")
USER_AGENT = "MMD-AINakawari-setup"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# tqdm などの進み具合の行（ログには残さず、上書きの 1 行に出す）
# uv の「落とし始めた」「落とし終わった」の行（uv 0.9.26: "Downloading torch (2.5GiB)"・" Downloaded torch"）。今落としている物を出すのに使う
UV_START_RE = re.compile(r"^\s*Downloading (\S+) \(([^)]+)\)")
UV_END_RE = re.compile(r"^\s*Downloaded (\S+)")
PROGRESS_RE = re.compile(r"\d+%\||\d+(\.\d+)?\s*[kMG]?i?B/s|^\s*(Downloading|Downloaded|Fetching|Building|Built)\b")


# 通信の失敗と見る文。uv の実物の文から（11-10 に、つながらない相手・引けない名前で出した: 「error: Failed to fetch」
# 「error sending request for url」「operation timed out」「client error (Connect)」「dns error」「os error 11001」）と、
# huggingface_hub（requests）の例外の名前。ここに当たった失敗は、少し待ってやり直す（Setup.call の retries）
NETWORK_RE = re.compile(
    r"Failed to (fetch|download)|error sending request|timed out|timeout|dns error|client error|"
    r"connection (reset|closed|refused|aborted)|os error 1(0053|0054|0060|1001|1002)\b|"
    r"ConnectionError|ReadTimeout|ConnectTimeout|IncompleteRead|ChunkedEncodingError|MaxRetryError|ProtocolError", re.IGNORECASE)
NETWORK_HINT = N_("通信が途中で切れたようです。少し時間をおいて、もう一度「セットアップ」を押してください。"
                  "済んだ手順は飛ばして、続きから始めます。")
NETWORK_RETRIES = 2      # 通信の失敗の時に、同じ手順をやり直す回数（最初の 1 回は別）
NETWORK_WAIT = 10.0      # やり直す前に待つ秒
DOWNLOAD_RETRIES = 5     # 自前で落とす物（zip・モデル・GGUF）が途中で切れた時に、続きから落とし直す回数


class Failed(Exception):
    """段が失敗した（使う人に見せる文）。"""


class Cancelled(Exception):
    """中止のボタンで止めた。"""


def short_title(title):
    """段の見出しの、（ ）より前の短い名前（日本語は全角の（、英語は " (" で切る）。画面に出す物なので、見分けには使わない。"""
    return re.split(r"（| \(", title)[0]   # i18n: skip


def sha256(path, stop=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            if stop is not None and stop.is_set():
                raise Cancelled()
            h.update(block)
    return h.hexdigest()


def file_sha256(path, eol="lf"):
    """文字のファイルの中身の印（sha256 の頭 16 字）。段の版に使う。改行を LF にそろえてから数える（eol="crlf" なら CRLF にそろえて）。

    配る zip の中のファイルの改行は、作った時の作業フォルダの状態で変わる（git が CRLF で取り出した物・道具が LF で書いた物）。
    そろえずに数えていたので、中身が同じでも zip によって版が変わり、更新のたびに Kimodo の環境（約 5GB）を入れ直させていた
    （kimodo-requirements.txt は 0.2.2 の zip が CRLF・0.2.3 が LF。11-10 に 0.3.0 の zip を検証用の MMD に入れて気づいた）。
    これまでの zip で入れた印はどちらの改行の物もあるので、済んだかどうかは両方と比べる（Setup.finished_steps）。"""
    with open(path, "rb") as f:
        data = f.read().replace(b"\r\n", b"\n")
    if eol == "crlf":
        data = data.replace(b"\n", b"\r\n")
    return hashlib.sha256(data).hexdigest()[:16]


def find_uv():
    """配布の zip では MMD-AINakawari\\uv\\uv.exe（app の隣）。リポジトリから動かす開発版は PATH の uv。"""
    bundled = os.path.join(os.path.dirname(paths.HOME), "uv", "uv.exe")
    if os.path.isfile(bundled):
        return bundled
    found = shutil.which("uv")
    if found:
        return found
    raise Failed(_("セットアップの道具（uv）が見つかりません: {path}。zip の中身を全部展開し直してください", path=bundled))


def tls_context():
    """落とす時の証明書: Windows の証明書ストア ＋ certifi（Mozilla の束）。
    Windows はルート証明書を、ほかのアプリが使った時に後から取ってくるので、まっさらな PC ではまだ無いことがある
    （11-06: まっさらな環境の試しで、GitHub の zip が CERTIFICATE_VERIFY_FAILED になった）。会社のプロキシの証明書などは
    Windows にだけ入っているので、Windows の分も残して足し合わせる。certifi は窓の Python の部品（tools/release/requirements.in）"""
    import ssl
    import certifi
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


def motion_correction_info():
    """組み立て済みの MotionCorrection の (フォルダ, 記録)。無ければ Failed。"""
    for folder in (os.path.join(os.path.dirname(paths.HOME), PREBUILT), os.path.join(paths.WORK_DIR, PREBUILT)):
        path = os.path.join(folder, MOTION_CORRECTION_JSON)
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return folder, json.load(f)
    raise Failed(_("zip の中身が足りません（{name} がありません）。zip の中身を全部展開し直してください",
                   name=f"{PREBUILT}\\{MOTION_CORRECTION_JSON}"))


def check_vc_runtime():
    """torch と MotionCorrection は Visual C++ のランタイム（System32 の msvcp140.dll）を要る。zip には入れられないので、無ければ案内する。"""
    system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    if not os.path.isfile(os.path.join(system, "msvcp140.dll")):
        raise Failed(_("Microsoft Visual C++ 再頒布可能パッケージ（x64）が入っていません。") + "\n"
                     + _("{url} から落として入れてから、もう一度押してください（Microsoft の公式の物です）", url=VC_REDIST_URL))


def check_folder(dest):
    """入れる場所に使えるか。使えなければ Failed（理由と直し方）。"""
    if not FOLDER_RE.match(dest or ""):
        raise Failed(_("入れる場所は「D:\\AINakawari」のような、ドライブから始まる半角の英数字だけのフォルダにしてください。") + "\n"
                     + _("日本語・空白・記号（& ( ) など）が入ると、途中の部品が動かないことがあります。"))
    drive = os.path.splitdrive(dest)[0] + "\\"
    if not os.path.isdir(drive):
        raise Failed(_("ドライブ {drive} がありません", drive=drive))
    if (os.path.normcase(os.path.abspath(dest)) + os.sep).startswith(os.path.normcase(paths.HOME) + os.sep):
        raise Failed(_("{name} 本体のフォルダ（{path}）の中には入れられません。別のフォルダにしてください", name=i18n.name(), path=paths.HOME))
    # MMD の plugin\ の下は、MMDPlugin が DLL を奥まで全部読み込もうとして MMD が落ちる（11-05 に踏んだ。11-06 Codex のレビュー）
    folder = os.path.abspath(dest)
    while True:
        if os.path.basename(folder).lower() == "plugin" and os.path.isfile(os.path.join(os.path.dirname(folder), "MikuMikuDance.exe")):
            raise Failed(_("MMD の plugin フォルダ（{path}）の中には入れられません。MMD が起動しなくなります。別のフォルダにしてください", path=folder))
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent


def free_gb(dest):
    return shutil.disk_usage(os.path.splitdrive(dest)[0] + "\\").free / 1e9


def default_folder():
    """空きのいちばん多いドライブの \\AINakawari（固定ディスクだけ。光学・ネットワークのドライブは選ばない）。"""
    import ctypes
    best, best_free = None, -1.0
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) != 3:   # DRIVE_FIXED
            continue
        try:
            free = shutil.disk_usage(root).free
        except OSError:
            continue
        if free > best_free:
            best, best_free = root, free
    return os.path.join(best or "C:\\", "AINakawari")


def gpu_tag():
    """この PC の GPU の名前から作る短い印。試しの生成の段の版に混ぜる: GPU を替えると印が変わり、セットアップが
    「更新があります」と出して、試しの生成（計算の方式の選び直し）をやり直す。GPU を読めない時は "unknown"（毎回同じ）。"""
    names = sorted(name for name, _vram in gpu._adapters())
    return hashlib.sha256("|".join(names).encode("utf-8")).hexdigest()[:8] if names else "unknown"


class Setup:
    """1 回のセットアップ。run() は時間がかかるので、画面からは裏のスレッドで回す。cancel() は別のスレッドから呼んでよい。

    log(行): ログに残す 1 行。progress(文): 上書きの 1 行（落としている途中の量など）。
    on_step(段の名前, "skip" | "run" | "done" | "fail"): 段の印を画面に出す。
    """

    def __init__(self, dest, log=print, progress=None, on_step=None, reuse_text_gguf=None, with_text=None):
        """with_text: プロンプトの読み取り（Llama 3）を入れるか。None は前にこの場所で選んだ方（初めてなら入れる）。"""
        check_folder(dest)
        self.dest = dest
        self.log = log
        self.progress = progress or (lambda _text: None)
        self.on_step = on_step or (lambda _key, _state: None)
        self.reuse_text_gguf = reuse_text_gguf
        self.kimodo = os.path.join(dest, "kimodo")
        self.mb = os.path.join(dest, "motionbricks")
        self.downloads = os.path.join(dest, "downloads")
        self.state_path = os.path.join(dest, STATE_FILE)
        self.with_text = self.chosen_text() if with_text is None else bool(with_text)
        self.uv = None
        self.found = {}   # 試しの生成が通った計算の方式（BACKEND_STATE の名前 → 方式）。run が setup_state.json に書く
        self._stop = threading.Event()
        self._proc = None

    # ---- 段の並び --------------------------------------------------------------------------------
    def steps(self, eol="lf"):
        """[(名前, 組, 見出し, 版, 使う GB, 関数)]。版が setup_state.json の物と同じ段は飛ばす（finished_steps）。
        eol は版に混ぜるファイルの印の数え方（file_sha256）。書く印はいつも "lf" の物。"""
        def file_sha256(path):   # この関数の中では、頼まれた改行で数える
            return globals()["file_sha256"](path, eol)

        k = [
            ("kimodo_src", "kimodo", _("Kimodo の本体を落とす"), pins.KIMODO_COMMIT, 0.2, self.kimodo_src),
            ("kimodo_env", "kimodo", _("Kimodo の Python の環境を作る（約 5GB）"),
             f"{pins.KIMODO_COMMIT}/{pins.KIMODO_PYTHON}/{file_sha256(REQUIREMENTS)}/{self._prebuilt_version()}", 5.5,
             self.kimodo_env),
            ("skeleton", "kimodo", _("Kimodo の骨格を用意する"), file_sha256(os.path.join(TOOLS, "export_skeleton.py")), 0, self.skeleton),
            ("kimodo_model", "kimodo", _("Kimodo のモデルを落とす（約 1GB）"), pins.KIMODO_MODEL_REVISION, 1.2, self.kimodo_model),
        ]
        if self.with_text:
            k += [
                # 文の読み取り（11-07 に bf16 の Llama 約 16GB から GGUF Q8_0 約 8GB ＋ llama.cpp に替えた）
                ("text_gguf", "kimodo", _("プロンプトを読み取るモデルを落とす（約 8GB。いちばん長くかかります）"),
                 f"{pins.TEXT_GGUF_REVISION}/{pins.TEXT_GGUF_FILE[1]}", 8.0, self.text_gguf),
                ("llamacpp", "kimodo", _("プロンプトの読み取りに使う llama.cpp を落とす"), pins.LLAMACPP_ZIP[1], 0.1, self.llamacpp),
            ]
        elif any(os.path.isdir(os.path.join(self.kimodo, d)) for d in ("text_encoder", "llamacpp")):
            # 前に入れた Llama を外した時だけ出る段（消し終われば出なくなる）
            k.append(("text_remove", "kimodo", _("プロンプトの読み取り（Llama 3）を消す（約 8GB 空きます）"), "removed", 0, self.text_remove))
        # 環境を作り直した時に入れ直すように、Kimodo の環境の段より後ろ・試しの生成の前に置く（run は後ろの段をやり直させる）
        k.append(("kimodo_ort", "kimodo", _("ONNX Runtime を Kimodo の環境に入れる（NVIDIA 以外の GPU でも動かすため）"),
                  file_sha256(ORT_KIMODO), 0.2, self.kimodo_ort))
        k.append(("kimodo_test", "kimodo", _("Kimodo が動くか確かめる（2 秒の動きを試しに作る）"),
                  f"{pins.KIMODO_COMMIT}/{file_sha256(os.path.join(TOOLS, 'gguf_text.py'))}/{'text' if self.with_text else 'samples'}"
                  f"/{file_sha256(os.path.join(TOOLS, 'kimodo_ort.py'))}/{gpu_tag()}",
                  1.2, self.kimodo_test))   # 1.2GB は DirectML の時に書き出す ONNX（CUDA で動く PC では作らない）
        m = [
            ("mb_src", "mb", _("MotionBricks の本体を落とす"), pins.MOTIONBRICKS_COMMIT, 0.2, self.mb_src),
            ("mb_models", "mb", _("MotionBricks のモデルを落とす（約 1.1GB）"), pins.MOTIONBRICKS_COMMIT, 1.2, self.mb_models),
            ("mb_env", "mb", _("MotionBricks の Python の環境を作る（約 3GB）"),
             f"{pins.MOTIONBRICKS_COMMIT}/{pins.MOTIONBRICKS_PYTHON}", 3.3, self.mb_env),
            ("mb_ort", "mb", _("ONNX Runtime を MotionBricks の環境に入れる（NVIDIA 以外の GPU でも動かすため）"),
             file_sha256(ORT_MOTIONBRICKS), 0.2, self.mb_ort),
            ("mb_test", "mb", _("MotionBricks が動くか確かめる（1 秒の動きを試しに作る。初回は数分かかる）"),
             f"{pins.MOTIONBRICKS_COMMIT}/{file_sha256(os.path.join(TOOLS, 'mb_ort.py'))}/{gpu_tag()}", 0.8, self.mb_test),
        ]
        # MotionBricks は選ばせずに必ず入れる（11-06 マスター。前は画面で選べた）
        return k + m

    def load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def chosen_text(self):
        """この場所で前に選んだ「プロンプトの読み取り（Llama 3）を入れるか」。印が無ければ入れる。"""
        return bool(self.load_state().get(WITH_TEXT, True))

    def save_state(self, state):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)

    def finished_steps(self, state):
        """済んでいる段の名前の集合。印が今の版と同じ段。改行が LF・CRLF どちらの zip で入れた印でも、同じ版と見る（file_sha256）。"""
        return {key for eol in ("lf", "crlf") for key, _g, _t, version, _gb, _fn in self.steps(eol) if state.get(key) == version}

    def intact(self, key):
        """済んだ印のある段 key の中身が、今も使える形であるか。run が、飛ばす前に確かめる。

        印は「その手順が最後まで終わった」ことしか言わない。その後で中身が欠けること（ウイルス対策ソフトが部品を消した・
        フォルダの一部を手で消した・環境の作り直しが途中で止まって古い印が残った）があり、印だけ見て飛ばすと、先の手順で
        原因から遠いエラーになって、使う人には直す手が無かった（11-10 に検証用の置き場で踏んだ: 環境が半分消えているのに
        「ONNX Runtime の読み込みで google が無い」と出た。マスター「中途半端に環境が入ったフォルダに再更新かけても大丈夫？」）。
        見るのは、ファイルがあるか・大きさが合うか・Python の環境なら主な部品を読み込めるか（全部で 10 秒ほど）。
        試しの生成など、物を置かない段は True。"""
        k, m = self.kimodo, self.mb
        if key == "kimodo_src":
            return os.path.isfile(os.path.join(k, "repo", "kimodo", "__init__.py"))
        if key == "kimodo_env":
            return self._imports(self.kimodo_python(), "import torch, kimodo, motion_correction._motion_correction")
        if key == "skeleton":
            return os.path.isfile(os.path.join(k, "tools", "somaskel30.json"))
        if key == "kimodo_model":
            snapshot = os.path.join(k, "hf_cache", "models--" + pins.KIMODO_MODEL_REPO.replace("/", "--"), "snapshots",
                                    pins.KIMODO_MODEL_REVISION)
            return os.path.isdir(snapshot) and bool(os.listdir(snapshot))
        if key == "text_gguf":
            name, _digest, size = pins.TEXT_GGUF_FILE
            path = os.path.join(k, "text_encoder", name)
            return os.path.isfile(path) and os.path.getsize(path) == size
        if key == "llamacpp":
            return os.path.isfile(os.path.join(k, "llamacpp", "llama-server.exe"))
        if key == "kimodo_ort":
            return self._imports(self.kimodo_python(), "import onnx, onnxruntime")
        if key == "mb_src":
            return os.path.isfile(os.path.join(m, "pyproject.toml"))
        if key == "mb_models":
            return all(os.path.isfile(os.path.join(m, *path.split("/"))) and os.path.getsize(os.path.join(m, *path.split("/"))) == size
                       for path, (_digest, size) in pins.MOTIONBRICKS_LFS.items())
        if key == "mb_env":
            return self._imports(self.mb_python(), "import numpy, scipy, warp, motionbricks")
        if key == "mb_ort":
            return self._imports(self.mb_python(), "import onnx, onnxruntime")
        return True

    def _imports(self, python, code):
        """python（環境の Python）が code（import の文）を読み込めるか。Python が無い・読み込めない・答えないなら False。"""
        if not os.path.isfile(python):
            return False
        try:
            return subprocess.run([python, "-c", code], env=self.env(), stdin=subprocess.DEVNULL, capture_output=True, timeout=300,
                                  creationflags=NO_WINDOW).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def remaining_gb(self):
        done = self.finished_steps(self.load_state())
        return sum(gb for key, _g, _t, _version, gb, _fn in self.steps() if key not in done)

    def status(self):
        """この場所の状態と、残りの段 [(名前, 見出し, GB)]。状態は
        "new"（まだ何も済んでいない）・"partial"（途中で止まった）・"update"（最後まで済んだ後に版が上がった）・"done"（全部済み）。
        「最後まで済んだ」は FINISHED の印で見る。印を書く前の版（0.1.x）は、最後の段（MotionBricks の試し）が済んでいれば済んだと見る。"""
        state = self.load_state()
        steps = self.steps()
        done = self.finished_steps(state)
        pending = [(key, title, gb) for key, _g, title, _version, gb, _fn in steps if key not in done]
        if not pending:
            return "done", []
        if not any(key in state for key, *_rest in steps):
            return "new", pending
        finished = bool(state.get(FINISHED)) or steps[-1][0] in state
        return ("update" if finished else "partial"), pending

    def in_use(self):
        """この窓の paths.json が、この場所の Kimodo を指しているか（別の MMD に入れた AIナカワリ からは、まだ指していない）。"""
        try:
            return os.path.normcase(os.path.normpath(paths.load().get("kimodo") or "")) == os.path.normcase(self.kimodo)
        except paths.NotSetUp:
            return False

    def run(self):
        os.makedirs(self.dest, exist_ok=True)
        need, free = self.remaining_gb(), free_gb(self.dest)
        if free < need:
            raise Failed(_("空きが足りません。残りの手順で約 {need:.0f}GB 使いますが、{drive} の空きは {free:.0f}GB です。"
                           "空きを作るか、別のドライブを選んでください", need=need, drive=os.path.splitdrive(self.dest)[0], free=free))
        check_vc_runtime()
        motion_correction_info()   # 部品が欠けた zip なら、落とし始める前に止める
        self.uv = find_uv()
        self.log(_("入れる場所: {path}（空き {free:.0f}GB・残りの手順で約 {need:.0f}GB）", path=self.dest, free=free, need=need))
        self.log(f"uv: {self.uv}")
        state = self.load_state()
        state[WITH_TEXT] = self.with_text
        if not self.with_text:   # 後でまた入れる時に、落とし直すように
            for key in TEXT_STEPS:
                state.pop(key, None)
        self.log(_("プロンプトの読み取り（Llama 3）: 入れます") if self.with_text
                 else _("プロンプトの読み取り（Llama 3）: 入れません（「サンプルから選ぶ」の文だけで作ります）"))
        steps = self.steps()
        ran = 0
        for i, (key, group, title, version, _gb, fn) in enumerate(steps):
            if key in self.finished_steps(state):
                # 済んだ印があっても、中身を確かめてから飛ばす（intact）。欠けていれば、印を無視してやり直す
                self.progress(_("点検しています: {name}", name=short_title(title)))
                if self.intact(key):
                    self.on_step(key, "skip")
                    continue
                self.log(_("―― 点検: 「{name}」は済んだ印がありますが、中身が欠けているので、やり直します", name=short_title(title)))
            ran += 1
            for later in steps[i + 1:]:   # 後ろの段は作り直しの影響を受けうるので、やり直させる
                if later[1] == group:
                    state.pop(later[0], None)
            self.save_state(state)
            self.on_step(key, "run")
            self.log(f"―― {title}")
            t0 = time.time()
            try:
                fn()
            except Exception:
                self.on_step(key, "fail")
                raise
            finally:
                self.progress("")
            if self._stop.is_set():
                self.on_step(key, "fail")
                raise Cancelled()
            state[key] = version
            state.update(self.found)
            self.save_state(state)
            self.on_step(key, "done")
            self.log("   " + _("済み（{s:.0f} 秒）", s=time.time() - t0))
        shutil.rmtree(self.downloads, ignore_errors=True)
        state[FINISHED] = __version__   # 最後まで済んだ印（status の「途中」と「更新あり」を分ける）
        self.save_state(state)
        self.register()
        self.progress("")
        self.log(_("セットアップが終わりました") if ran else _("点検しました。欠けている物はありませんでした"))

    def register(self):
        """この窓の paths.json に場所を書く。全部の段が済んでいて飛ばした時も書く（別の MMD に入れた AIナカワリから、
        前にセットアップした場所を選んだ時。試しの生成の段は飛ばされるので、そこで書くだけでは足りなかった。11-06 Codex のレビュー）。"""
        paths.check(self.kimodo, "Kimodo")
        paths.check(self.mb, "MotionBricks")
        paths.save(kimodo=self.kimodo, motionbricks=self.mb)
        state = self.load_state()
        for name, key in BACKEND_STATE.items():   # 0.2.x までにセットアップした場所には印が無い（cuda で動いていた）
            paths.save_backend(name, state.get(key) if state.get(key) in paths.BACKENDS else "cuda")
        self.log(_("この場所を使うように設定しました（{path}）", path=paths.PATHS_FILE))

    def cancel(self):
        self._stop.set()
        self._kill(self._proc)

    @staticmethod
    def _kill(proc):
        if proc and proc.poll() is None:   # uv・Python の子プロセスごと止める
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)

    # ---- 道具 --------------------------------------------------------------------------------------
    def env(self, **extra):
        """外のプロセスの環境。uv と huggingface_hub の置き場所を入れる場所の中にする。開発の環境の Python の設定は渡さない。"""
        env = {k: v for k, v in os.environ.items()
               if k.upper() not in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "CONDA_PREFIX", "UV_PROJECT_ENVIRONMENT")}
        env.update(
            UV_CACHE_DIR=os.path.join(self.dest, "uv", "cache"),
            UV_PYTHON_INSTALL_DIR=os.path.join(self.dest, "uv", "python"),
            UV_PYTHON_PREFERENCE="only-managed",   # PC に入っている別の Python は使わない
            UV_NO_CONFIG="1",                      # 使う人の uv の設定は読まない
            HF_HOME=os.path.join(self.dest, "hf_home"),
            HF_XET_CHUNK_CACHE_SIZE_BYTES="0",     # xet の部品の控え（既定 10GB）を作らない
            HF_HUB_DISABLE_SYMLINKS_WARNING="1",
            PYTHONUTF8="1", PYTHONIOENCODING="utf-8", CUDA_DEVICE_ORDER="PCI_BUS_ID",
        )
        # 回線が細い・不安定な所でも落とし切れるように（11-10 利用者の声「torch のダウンロードが時間切れ」）。
        # uv の既定は「30 秒データが来なければ切る」で、1 個 2.5GB の torch が途中で切られていた。
        # 同時に落とす数も減らす（既定の 50 本を細い回線で分け合うと、1 本ごとがさらに止まりやすい）。
        # 使う人が自分で決めていれば、そちらを使う
        for key, value in (("UV_HTTP_TIMEOUT", "300"), ("UV_HTTP_RETRIES", "8"), ("UV_CONCURRENT_DOWNLOADS", "4"),
                           ("HF_HUB_DOWNLOAD_TIMEOUT", "120"), ("HF_HUB_ETAG_TIMEOUT", "60")):
            env.setdefault(key, value)
        env.update(extra)
        return env

    def call(self, args, what, cwd=None, retries=0, **extra_env):
        """外のプロセスを回し、出力をログ（と上書きの 1 行）に流す。失敗したら Failed。
        retries: 通信の失敗（NETWORK_RE）の時に、少し待って同じ事をやり直す回数（部品やモデルを落とす手順で NETWORK_RETRIES）。
        落とし終わった物は uv・huggingface_hub の置き場に残るので、やり直しは続きからになる。"""
        for attempt in range(retries + 1):
            try:
                return self._call_once(args, what, cwd, extra_env)
            except Failed as e:
                if not getattr(e, "network", False):
                    raise
                if attempt == retries:
                    raise Failed(_(NETWORK_HINT) + "\n" + str(e)) from None
                self.log("  " + _("通信が途中で切れたようです。{s:.0f} 秒待って、続きからもう一度試します（{n} 回目／全 {total} 回）",
                                   s=NETWORK_WAIT, n=attempt + 2, total=retries + 1))
                self.progress(_("{what}: 通信が切れたので、少し待ってやり直します…", what=what))
                if self._stop.wait(NETWORK_WAIT):
                    raise Cancelled()

    def _free_bytes(self):
        try:
            return shutil.disk_usage(self.dest).free
        except OSError:
            return None

    def _call_once(self, args, what, cwd, extra_env):
        if self._stop.is_set():
            raise Cancelled()
        self.log("> " + subprocess.list2cmdline(args))
        self._proc = proc = subprocess.Popen(args, cwd=cwd, env=self.env(**extra_env), stdin=subprocess.DEVNULL,
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        if self._stop.is_set():   # 起動の途中で中止が押された（cancel からは、まだ _proc が見えていなかった。11-06 Codex のレビュー）
            self._kill(proc)
            proc.wait()
            self._proc = None
            raise Cancelled()
        buf = b""
        tail = []
        # 進み具合の 1 行: 「何をしているか・かかった時間・ここまでに落として入れた量」を 2 秒ごとに出し直す。
        # uv は画面につながっていないと「Downloading torch」の 1 行しか出さないので、大きい物を落としている何十分かの間、
        # 窓に何も動きが出ず、止まったように見えていた（11-10 利用者の声「セットアップ画面に一つも進展が無い」）。
        # 量はディスクの空きの減りで見る（落とした物も入れた物も、入れる場所のドライブに置くので）
        started, free_before, last, done = time.time(), self._free_bytes(), [""], threading.Event()
        active = {}   # uv が今落としている物（名前 → 大きさの字）

        def show():
            elapsed = time.time() - started
            if elapsed < 4 and not last[0]:
                return
            text = _("{what}… {m} 分 {s:02d} 秒", what=what, m=int(elapsed // 60), s=int(elapsed % 60))
            free_now = self._free_bytes()
            if free_before is not None and free_now is not None and free_before - free_now >= 50 * 2**20:
                text += _("・ここまでに約 {gb:.1f}GB", gb=(free_before - free_now) / 2**30)
            self.progress(text + (_("　") + last[0] if last[0] else ""))

        lang = i18n.lang()   # この裏のスレッドの言葉（新しいスレッドには引き継がれない）

        def tick():
            with i18n.use(lang):
                while not done.wait(2.0) and proc.poll() is None:
                    show()
        threading.Thread(target=tick, daemon=True).start()

        def emit(line, overwrite):
            nonlocal tail
            text = line.decode("utf-8", "replace").rstrip()
            if not text:
                return
            if overwrite or PROGRESS_RE.search(text):
                # uv の行は、今落としている物の一覧にして出す（最後の 1 行をそのまま出すと、大きい物を落としている間じゅう、
                # 先に終わった小さい物の「Downloaded …」が出たままになる。11-10 に通しのセットアップで見た）
                start, end = UV_START_RE.match(text), UV_END_RE.match(text)
                if start:
                    active[start.group(1)] = start.group(2)
                elif end:
                    active.pop(end.group(1), None)
                if start or end:
                    names = [_("{name}（{size}）", name=name, size=size) for name, size in list(active.items())[:2]]
                    last[0] = (_("落としている物: ") + _("・").join(names)
                               + (_(" ほか {n} 個", n=len(active) - 2) if len(active) > 2 else "")) if names else ""
                else:
                    last[0] = text.strip()[-90:]
                show()
            else:
                self.log("  " + text)
                tail = (tail + [text])[-15:]

        # 行の終わり: \n と \r\n は改行（Windows の Python は \r\n で書く）、\r だけは上書きの 1 行（tqdm などの進み具合）。
        # 11-06: \r を先に見て全部を進み具合にしていたので、Python の子の出力（失敗の理由も）がログに残らなかった
        while True:
            chunk = proc.stdout.read1(65536)
            if not chunk:
                break
            buf += chunk
            while True:
                cut = min((i for i in (buf.find(b"\n"), buf.find(b"\r")) if i >= 0), default=-1)
                if cut < 0:
                    break
                if buf[cut:cut + 1] == b"\r":
                    if cut + 1 == len(buf):
                        break   # 次の字が \n かどうか、続きを読んでから決める
                    if buf[cut + 1:cut + 2] == b"\n":
                        emit(buf[:cut], False)
                        buf = buf[cut + 2:]
                    else:
                        emit(buf[:cut], True)
                        buf = buf[cut + 1:]
                else:
                    emit(buf[:cut], False)
                    buf = buf[cut + 1:]
        emit(buf.rstrip(b"\r"), False)   # 最後の改行の無い行
        rc = proc.wait()
        done.set()
        self._proc = None
        if self._stop.is_set():
            raise Cancelled()
        if rc != 0:
            error = Failed(_("「{what}」で失敗しました（終了コード {rc}）。", what=what, rc=rc) + "\n" + "\n".join(tail[-6:]))
            error.network = bool(NETWORK_RE.search("\n".join(tail)))   # call が、待ってやり直すかを決める
            raise error

    def download(self, url, target, label, digest=None, size=None, retry=True):
        """url を target に落とす。途中の .part があれば続きから（サーバーが応じれば）。digest があれば sha256 で照らす。

        落とし終えてから照らす前に止まると、全部そろった .part が残る。そこから続きを頼むとサーバーが断る（416）ので、
        大きさが分かっていて全部そろっていれば頼まずに照らすだけにし、断られた時は照らして合えば使い、合わなければ最初から落とす
        （11-06 Codex のレビュー: 何度押しても進まなくなっていた）。"""
        os.makedirs(os.path.dirname(target), exist_ok=True)
        part = target + ".part"
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if size is not None and have > size:
            os.remove(part)
            have = 0
        if size is None or have != size:
            # 通信が途中で切れたら、少し待って続きから落とし直す（前は「もう一度押してください」で止まっていた。
            # 8GB の GGUF を細い回線で落とすと、押し直しが何度も要った。11-10）
            for attempt in range(DOWNLOAD_RETRIES + 1):
                try:
                    self._fetch(url, part, have, label, size, digest, retry)
                    break
                except Failed as e:
                    if not getattr(e, "network", False):
                        raise
                    if attempt == DOWNLOAD_RETRIES:
                        raise Failed(_(NETWORK_HINT) + "\n" + str(e)) from None
                    have = os.path.getsize(part) if os.path.exists(part) else 0
                    self.log("  " + _("{label}: 通信が途中で切れました。{s:.0f} 秒待って、続き（{mb:,.0f} MB）から落とします（{n} 回目／全 {total} 回）",
                                       label=label, s=NETWORK_WAIT, mb=have / 1e6, n=attempt + 2, total=DOWNLOAD_RETRIES + 1))
                    self.progress(_("{label}: 通信が切れたので、少し待って続きから落とします…", label=label))
                    if self._stop.wait(NETWORK_WAIT):
                        raise Cancelled()
            if not os.path.exists(part):   # 断られて照らして合い、もう置いた（_fetch の中）
                return self._finish_download(target, label, digest, size, verified=True)
        return self._finish_download(target, label, digest, size)

    def _finish_download(self, target, label, digest, size, verified=False):
        part = target + ".part"
        if verified:
            return
        if size is not None and os.path.getsize(part) != size:
            raise Failed(_("{label} の大きさが違います（{actual} バイト・正しくは {size}）。もう一度押してください",
                           label=label, actual=os.path.getsize(part), size=size))
        if digest:
            self.progress(_("{label}: 中身を確かめています", label=label))
            if sha256(part, self._stop) != digest:
                os.remove(part)
                raise Failed(_("{label} の中身が違います（壊れて届いたかもしれません）。もう一度押してください", label=label))
        os.replace(part, target)

    def _fetch(self, url, part, have, label, size, digest, retry):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if have:
            request.add_header("Range", f"bytes={have}-")
        try:
            response = urllib.request.urlopen(request, timeout=60, context=tls_context())
        except urllib.error.HTTPError as e:
            if e.code == 416 and have:   # 続きを断られた: 手元の .part が全部そろっているかもしれない
                if digest and sha256(part, self._stop) == digest:
                    os.replace(part, part[:-len(".part")])
                    return
                os.remove(part)
                if retry:
                    return self._fetch(url, part, 0, label, size, digest, False)
            error = Failed(_("{label} を落とせませんでした（{error}）。もう一度押してください", label=label, error=e))
            error.network = e.code >= 500 or e.code in (408, 429)   # 相手の都合・混雑は、待ってやり直す（download）
            raise error from None
        except OSError as e:
            error = Failed(_("{label} を落とせませんでした（{error}）。ネットにつながっているか確かめて、もう一度押してください", label=label, error=e))
            error.network = True
            raise error from None
        with response:
            if have and response.status != 206:   # 続きに応じなかった（最初から落とす）
                have = 0
            total = response.headers.get("Content-Length")
            total = int(total) + have if total else size
            last = 0.0
            with open(part, "ab" if have else "wb") as f:
                done = have
                while True:
                    if self._stop.is_set():
                        raise Cancelled()
                    try:
                        block = response.read(1 << 20)
                    except OSError as e:
                        error = Failed(_("{label} を落とす途中で切れました（{error}）。もう一度押すと続きから落とします", label=label, error=e))
                        error.network = True
                        raise error from None
                    if not block:
                        # 相手が途中で接続を閉じると、読み取りは例外を出さずに空で終わることがある。届いた量が足りなければ
                        # 「途中で切れた」と見る（前は落とし終わったと見て、後で「大きさが違います」で止まっていた。11-10 のテストで気づいた）
                        if total and done < total:
                            error = Failed(_("{label} を落とす途中で切れました（{done:,.0f} / {total:,.0f} MB）。もう一度押すと続きから落とします",
                                             label=label, done=done / 1e6, total=total / 1e6))
                            error.network = True
                            raise error
                        break
                    f.write(block)
                    done += len(block)
                    if time.time() - last > 0.5:
                        last = time.time()
                        self.progress(_("{label}: {done:,.0f} / {total:,.0f} MB（{pct}%）", label=label, done=done / 1e6, total=total / 1e6,
                                        pct=done * 100 // total) if total
                                      else _("{label}: {done:,.0f} MB", label=label, done=done / 1e6))

    def fetch_zip(self, url, name, into, keep=()):
        """GitHub の zip を落として、中の 1 つのフォルダの中身を into に置く。keep の名前の物（.venv など）は into に残す。

        残す物は入れ替えの間 into.keep に退避する。入れ替えの途中で止まっても、次に回した時にそこから戻す
        （前は展開先の一時フォルダに移していたので、止まると次に一時フォルダごと消していた。11-06 Codex のレビュー）。"""
        keep_dir = into + ".keep"
        if os.path.isdir(keep_dir):   # 前の入れ替えが途中で止まった
            os.makedirs(into, exist_ok=True)
            for entry in os.listdir(keep_dir):
                if not os.path.exists(os.path.join(into, entry)):
                    os.replace(os.path.join(keep_dir, entry), os.path.join(into, entry))
            shutil.rmtree(keep_dir, ignore_errors=True)
        archive = os.path.join(self.downloads, f"{name}.zip")
        if not os.path.isfile(archive):
            self.download(url, archive, _("{name} の zip", name=name))
        work = into + ".extract"
        shutil.rmtree(work, ignore_errors=True)
        self.progress(_("{name} の zip を展開しています", name=name))
        try:
            with zipfile.ZipFile(archive) as z:
                z.extractall(work)
        except zipfile.BadZipFile:
            os.remove(archive)
            raise Failed(_("{name} の zip が壊れていました。もう一度押すと落とし直します", name=name)) from None
        tops = os.listdir(work)
        if len(tops) != 1:
            raise Failed(_("{name} の zip の中身が正しくありません（{tops}）", name=name, tops=tops[:3]))
        top = os.path.join(work, tops[0])
        if os.path.isdir(into):
            os.makedirs(keep_dir, exist_ok=True)
            for entry in os.listdir(into):
                if entry in keep:
                    os.replace(os.path.join(into, entry), os.path.join(keep_dir, entry))
            shutil.rmtree(into)
        os.replace(top, into)
        if os.path.isdir(keep_dir):
            for entry in os.listdir(keep_dir):
                os.replace(os.path.join(keep_dir, entry), os.path.join(into, entry))
            shutil.rmtree(keep_dir, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)

    def kimodo_python(self):
        return os.path.join(self.kimodo, ".venv", "Scripts", "python.exe")

    def mb_python(self):
        return os.path.join(self.mb, ".venv", "Scripts", "python.exe")

    # ---- 計算の方式 ---------------------------------------------------------------------------------
    def backends_to_try(self):
        """試しの生成で試す計算の方式の順。NVIDIA の GPU が見える（nvidia-smi がある）時だけ cuda から。
        環境変数 AINAKAWARI_SETUP_BACKENDS があれば、その順（開発用）。"""
        forced = [b.strip() for b in os.environ.get(BACKEND_ORDER_ENV, "").split(",") if b.strip()]
        if forced:
            if any(b not in paths.BACKENDS for b in forced):
                raise Failed(_("{env}={value} は {choices} の並びにしてください", env=BACKEND_ORDER_ENV, value=repr(os.environ[BACKEND_ORDER_ENV]),
                           choices=" / ".join(paths.BACKENDS)))
            return forced
        return (["cuda"] if shutil.which("nvidia-smi") else []) + ["directml", "cpu"]

    def try_backends(self, name, label, attempt):
        """attempt(方式) を順に試して、最初に通った方式を返す。覚えてもおく（self.found。run が setup_state.json に書く）。
        途中の失敗はログに残して次の方式へ。全部だめなら最後の失敗をそのまま出す。
        GPU の世代を決め打ちしないための作り: 今の PyTorch（CUDA 12.8）や TensorRT で動かない NVIDIA の GPU も、ここで DirectML に落ちる。"""
        order = self.backends_to_try()
        for i, backend in enumerate(order):
            self.log("  " + _("計算の方式: {backend} で試します", backend=_(paths.BACKEND_LABEL[backend])))
            try:
                attempt(backend)
            except Failed as e:
                if i == len(order) - 1:
                    raise
                self.log("  " + _("{label} は {backend} では動きませんでした。次の方式で試します:", label=label, backend=_(paths.BACKEND_LABEL[backend])))
                for line in str(e).splitlines():
                    self.log("    " + line)
                continue
            self.found[BACKEND_STATE[name]] = backend
            return backend

    # ---- Kimodo -------------------------------------------------------------------------------------
    def kimodo_src(self):
        self.fetch_zip(pins.KIMODO_ZIP, f"kimodo-{pins.KIMODO_COMMIT[:7]}", os.path.join(self.kimodo, "repo"))

    def stop_residents(self, why=N_("環境を作り直すため")):
        """常駐の Kimodo・MotionBricks がいれば終わらせる。
        環境を作り直す前: 常駐が環境のファイルをつかんでいると、uv が古い環境を消せずに「アクセスが拒否されました」で止まり、
        環境が途中まで消えた形で残る（11-10 に検証用の MMD で踏んだ）。
        計算の方式を書いた後: 前の方式で動いている常駐に、次の生成を頼まないように。"""
        try:
            from .. import pipeline, resident, smooth_stop
            for name, port in ((pipeline.KIMODO_NAME, pipeline.KIMODO_PORT), ("MotionBricks", smooth_stop.MB_PORT)):
                if resident.stop(name, port):
                    self.log("  " + _("常駐の {name} を終わらせました（{why}）", name=name, why=_(why)))
        except Exception as e:   # 終わらせられなくても、作り直しは試す（だめなら uv の失敗がそのまま出る）
            self.log("  " + _("常駐を終わらせられませんでした（{kind}: {error}）", kind=type(e).__name__, error=e))

    def kimodo_env(self):
        self.stop_residents()
        venv = os.path.join(self.kimodo, ".venv")
        self.log("  " + _("PyTorch など約 5GB を落として入れます（いちばん大きい物は 1 個で約 2.5GB）。回線によって 10 分〜1 時間ほどかかります"))
        self.log("  " + _("下の青い字の時間と量が増えていれば、進んでいます。通信が切れた時は、自動で続きからやり直します"))
        self.call([self.uv, "venv", venv, "--python", pins.KIMODO_PYTHON, "--clear"], _("Python の用意"), retries=NETWORK_RETRIES)
        py = self.kimodo_python()
        self.call([self.uv, "pip", "install", "--python", py, "--require-hashes", "--index-strategy", "unsafe-best-match",
                   "-r", REQUIREMENTS], _("Kimodo の部品を入れる"), retries=NETWORK_RETRIES)
        # kimodo 本体は部品表に入れられない（GitHub の zip）ので、部品を入れた後に依存なしで入れる。
        # C++ の部品は組み立てない（SKIP_MOTION_CORRECTION_IN_SETUP は kimodo の setup.py の切り替え）。組み立て済みの物を後で置く
        self.call([self.uv, "pip", "install", "--python", py, "--no-deps", "--no-build-isolation",
                   os.path.join(self.kimodo, "repo")], _("Kimodo を入れる"), SKIP_MOTION_CORRECTION_IN_SETUP="1")
        self.place_motion_correction()

    def _prebuilt_version(self):
        try:
            return motion_correction_info()[1]["sha256"][:16]
        except (Failed, OSError, ValueError, KeyError):
            return "missing"   # 回す時に place_motion_correction が Failed にする

    def place_motion_correction(self):
        """motion_correction の .py（kimodo の zip から）と、組み立て済みの pyd を Kimodo の環境に置いて、読めるか確かめる。"""
        folder, info = motion_correction_info()
        if info.get("kimodo_commit") != pins.KIMODO_COMMIT:
            raise Failed(_("zip の中の部品が、別の版の Kimodo 用です（{commit}）。zip を落とし直してください", commit=info.get("kimodo_commit")))
        pyd = os.path.join(folder, info["file"])
        if not os.path.isfile(pyd) or sha256(pyd) != info["sha256"]:
            raise Failed(_("zip の中の部品（{path}）が無いか、壊れています。zip を落とし直してください", path=pyd))
        src = os.path.join(self.kimodo, "repo", "MotionCorrection", "python", "motion_correction")
        site = os.path.join(self.kimodo, ".venv", "Lib", "site-packages", "motion_correction")
        shutil.rmtree(site, ignore_errors=True)
        shutil.copytree(src, site, ignore=shutil.ignore_patterns("__pycache__", "*.pyd", "*.so"))
        shutil.copyfile(pyd, os.path.join(site, info["file"]))
        self.call([self.kimodo_python(), "-c", "import torch, motion_correction._motion_correction; print('motion_correction ok')"],
                  _("組み立て済みの部品の読み込み"))

    def kimodo_ort(self):
        self.call([self.uv, "pip", "install", "--python", self.kimodo_python(), "--require-hashes", "-r", ORT_KIMODO],
                  _("ONNX Runtime を入れる（Kimodo）"), retries=NETWORK_RETRIES)
        self.call([self.kimodo_python(), "-c",
                   "import onnx, onnxruntime; print('onnxruntime', onnxruntime.__version__, onnxruntime.get_available_providers())"],
                  _("ONNX Runtime の読み込み（Kimodo）"))

    def skeleton(self):
        os.makedirs(os.path.join(self.kimodo, "tools"), exist_ok=True)
        self.call([self.kimodo_python(), os.path.join(TOOLS, "export_skeleton.py"),
                   os.path.join(self.kimodo, "tools", "somaskel30.json")], _("骨格の書き出し"))

    def kimodo_model(self):
        cache = os.path.join(self.kimodo, "hf_cache")
        self.call([self.kimodo_python(), FETCH_MODEL, cache, pins.KIMODO_MODEL_REPO, pins.KIMODO_MODEL_REVISION, _(FETCH_DONE)],
                  _("Kimodo のモデルを落とす"), retries=NETWORK_RETRIES, HF_HUB_CACHE=cache)

    def text_gguf(self):
        """文の読み取りの GGUF（約 8GB）とライセンスの文を <kimodo>\\text_encoder に置く。GGUF は sha256 で照らしてから名前を付ける。"""
        folder = os.path.join(self.kimodo, "text_encoder")
        name, digest, size = pins.TEXT_GGUF_FILE
        target = os.path.join(folder, name)
        url = lambda n: pins.TEXT_GGUF_URL.format(repo=pins.TEXT_GGUF_REPO, revision=pins.TEXT_GGUF_REVISION, name=n)
        os.makedirs(folder, exist_ok=True)
        if os.path.isfile(target) and os.path.getsize(target) == size:
            self.progress(_("{label}: 中身を確かめています", label=name))
            if sha256(target, self._stop) == digest:
                self.log("  " + _("もう置いてありました: {name}", name=name))
                target = None
        if target and self.reuse_text_gguf:   # 開発用: 手元の物を照らしてから写す（同じドライブならハードリンク）
            self.progress(_("{label}: 中身を確かめています", label=self.reuse_text_gguf))
            if sha256(self.reuse_text_gguf, self._stop) != digest:
                raise Failed(_("写す元の GGUF の中身が違います（{path}）", path=self.reuse_text_gguf))
            try:
                os.link(self.reuse_text_gguf, target)
            except OSError:
                shutil.copyfile(self.reuse_text_gguf, target)
            self.log("  " + _("写しました: {path}", path=self.reuse_text_gguf))
            target = None
        if target:
            self.download(url(name), target, name, digest=digest, size=size)
            self.log("  " + _("落としました: {name}", name=name))
        for n in pins.TEXT_GGUF_LICENSES:   # Llama 3 のライセンスの文などを、モデルの横に置く（ライセンスの決まり）
            self.download(url(n), os.path.join(folder, n), n)

    def llamacpp(self):
        """llama.cpp の CPU 版の zip（sha256 で照らす）を <kimodo>\\llamacpp に展開する。使うのは llama-server.exe だけ。"""
        url, digest, size = pins.LLAMACPP_ZIP
        archive = os.path.join(self.downloads, os.path.basename(url))
        self.download(url, archive, _("llama.cpp の zip"), digest=digest, size=size)
        into = os.path.join(self.kimodo, "llamacpp")
        work = into + ".extract"
        shutil.rmtree(work, ignore_errors=True)
        self.progress(_("llama.cpp の zip を展開しています"))
        with zipfile.ZipFile(archive) as z:
            z.extractall(work)
        if not os.path.isfile(os.path.join(work, "llama-server.exe")):
            raise Failed(_("llama.cpp の zip の中身が正しくありません（llama-server.exe がありません）"))
        shutil.rmtree(into, ignore_errors=True)
        os.replace(work, into)
        self.call([os.path.join(into, "llama-server.exe"), "--version"], _("llama.cpp の版を確かめる"))

    def text_remove(self):
        """前に入れたプロンプトの読み取り（GGUF 約 8GB・llama.cpp）を消す（セットアップで外した時。消す前に窓で確かめる）。"""
        for d in ("text_encoder", "llamacpp"):
            folder = os.path.join(self.kimodo, d)
            if os.path.isdir(folder):
                self.progress(_("{path} を消しています", path=folder))
                shutil.rmtree(folder)
                self.log("  " + _("消しました: {path}", path=folder))

    def kimodo_test(self):
        """常駐と同じ置き方で 1 回作る。通ったら paths.json に書く。
        Llama を入れた時は、読み取り結果を使わずに llama-server で読む（AINAKAWARI_TEXT_NO_CACHE。Llama そのものを確かめる）。
        入れていない時は、同梱の読み取り結果（サンプルの文）で作る。"""
        work = os.path.join(self.dest, "setup_test")
        os.makedirs(work, exist_ok=True)
        req, out = os.path.join(work, "kimodo_request.json"), os.path.join(work, "kimodo_result.json")
        with open(req, "w", encoding="utf-8") as f:
            json.dump({"prompt": "A person walks forward.", "num_frames": 60, "seed": 0}, f)
        if self.with_text:
            self.log("  " + _("初めての読み込みなので 1〜2 分かかります（プロンプトを読み取るモデル約 8GB をメインメモリに読みます）"))
        else:
            self.log("  " + _("初めての読み込みなので 1 分ほどかかります（プロンプトはサンプルの読み取り結果を使います）"))

        def attempt(backend):
            if os.path.exists(out):
                os.remove(out)
            if backend == "directml":
                self.log("  " + _("DirectML では、初回だけ Kimodo のモデルを ONNX に書き出します（約 1.2GB・1 分ほど）"))
            elif backend == "cpu":
                self.log("  " + _("GPU を使わずに作ります（2 秒の動きに 1 分ほどかかります）"))
            self.call([self.kimodo_python(), os.path.join(TOOLS, "kimodo_gen.py"), req, out], _("Kimodo の試しの生成"), cwd=self.kimodo,
                      HF_HUB_CACHE=os.path.join(self.kimodo, "hf_cache"), LOCAL_CACHE="true", HF_HUB_OFFLINE="1",
                      AINAKAWARI_LLAMA_SERVER=os.path.join(self.kimodo, "llamacpp", "llama-server.exe"),
                      AINAKAWARI_TEXT_GGUF=os.path.join(self.kimodo, "text_encoder", pins.TEXT_GGUF_FILE[0]), AINAKAWARI_LOG_DIR=work,
                      AINAKAWARI_TEXT_NO_CACHE="1" if self.with_text else "0",
                      AINAKAWARI_BACKEND=backend, AINAKAWARI_ORT_CACHE=os.path.join(self.kimodo, "ort_cache"))
            with open(out, encoding="utf-8") as f:
                if not json.load(f).get("num_frames"):
                    raise Failed(_("Kimodo の試しの生成の結果が空でした（{path}）", path=out))

        backend = self.try_backends("kimodo", "Kimodo", attempt)
        with open(out, encoding="utf-8") as f:
            frames = json.load(f).get("num_frames")
        paths.check(self.kimodo, "Kimodo")
        paths.save(kimodo=self.kimodo)   # 通ってから、場所と方式を書く
        paths.save_backend("kimodo", backend)
        self.stop_residents(N_("次の生成から、選んだ計算の方式で動かすため"))
        self.log("  " + _("Kimodo で {frames} フレーム作れました（計算の方式: {backend}）。この場所を使うように設定しました",
                        frames=frames, backend=_(paths.BACKEND_LABEL[backend])))

    # ---- MotionBricks -------------------------------------------------------------------------------
    def mb_src(self):
        self.fetch_zip(pins.MOTIONBRICKS_ZIP, f"motionbricks-{pins.MOTIONBRICKS_COMMIT[:7]}", self.mb, keep=(".venv", ".trt-cache", ".ort-cache"))

    def mb_models(self):
        for path, (digest, size) in pins.MOTIONBRICKS_LFS.items():
            target = os.path.join(self.mb, *path.split("/"))
            name = path.rsplit("/", 1)[-1]
            if os.path.isfile(target) and os.path.getsize(target) == size:
                self.progress(_("{label}: 中身を確かめています", label=name))
                if sha256(target, self._stop) == digest:
                    continue
            url = pins.MOTIONBRICKS_LFS_URL.format(commit=pins.MOTIONBRICKS_COMMIT, path=path)
            self.download(url, target, name, digest=digest, size=size)
            self.log("  " + _("落としました: {name}", name=name))

    def mb_env(self):
        self.stop_residents()
        self.log("  " + _("約 3GB を落として入れます。下の青い字の時間と量が増えていれば、進んでいます"))
        self.call([self.uv, "sync", "--frozen", "--python", pins.MOTIONBRICKS_PYTHON], _("MotionBricks の部品を入れる"), cwd=self.mb,
                  retries=NETWORK_RETRIES)

    def mb_ort(self):
        self.call([self.uv, "pip", "install", "--python", self.mb_python(), "--require-hashes", "-r", ORT_MOTIONBRICKS],
                  _("ONNX Runtime を入れる（MotionBricks）"), retries=NETWORK_RETRIES)
        self.call([self.mb_python(), "-c",
                   "import onnx, onnxruntime; print('onnxruntime', onnxruntime.__version__, onnxruntime.get_available_providers())"],
                  _("ONNX Runtime の読み込み（MotionBricks）"))

    def mb_test(self):
        """T ポーズから T ポーズへ 1 回つなぐ。通った計算の方式と場所を paths.json に書く。
        CUDA の初回は TensorRT のエンジンを作る（.trt-cache。GPU ごとに数分）。DirectML の初回は手直しした ONNX を作る（.ort-cache。数秒）。"""
        skeleton = os.path.join(self.kimodo, "tools", "somaskel30.json")
        if not os.path.isfile(skeleton):
            raise Failed(_("Kimodo の骨格がありません。先に Kimodo のセットアップを済ませてください"))
        with open(skeleton, encoding="utf-8") as f:
            soma = json.load(f)
        pose = {"root": soma["neutral_joints"][soma["root_idx"]], "local_rot": [0.0, 0.0, 0.0, 1.0] * len(soma["names"])}
        work = os.path.join(self.dest, "setup_test")
        os.makedirs(work, exist_ok=True)
        req, out = os.path.join(work, "mb_request.json"), os.path.join(work, "mb_result.json")
        with open(req, "w", encoding="utf-8") as f:
            json.dump({"skeleton": skeleton, "context": [pose] * 4,
                       "targets": [{"poses": [pose], "frames": 30, "num_poses_to_use": 1}]}, f)

        def attempt(backend):
            if os.path.exists(out):
                os.remove(out)
            if backend == "cuda":
                self.log("  " + _("初回は GPU に合わせた TensorRT の準備で数分かかります（止まって見えても進んでいます）"))
            self.call([self.mb_python(), os.path.join(TOOLS, "mb_gen.py"), req, out], _("MotionBricks の試しの生成"), cwd=self.mb,
                      AINAKAWARI_BACKEND=backend)
            with open(out, encoding="utf-8") as f:
                if not json.load(f).get("num_frames"):
                    raise Failed(_("MotionBricks の試しの生成の結果が空でした（{path}）", path=out))

        backend = self.try_backends("motionbricks", "MotionBricks", attempt)
        with open(out, encoding="utf-8") as f:
            frames = json.load(f).get("num_frames")
        paths.check(self.mb, "MotionBricks")
        paths.save(motionbricks=self.mb)   # 通ってから、場所と方式を書く
        paths.save_backend("motionbricks", backend)
        self.stop_residents(N_("次の生成から、選んだ計算の方式で動かすため"))
        self.log("  " + _("MotionBricks で {frames} フレーム作れました（計算の方式: {backend}）。この場所を使うように設定しました",
                        frames=frames, backend=_(paths.BACKEND_LABEL[backend])))


def main():
    parser = argparse.ArgumentParser(description="AIナカワリ のセットアップ（ふつうは詳細の窓の「セットアップ」から）")
    parser.add_argument("dest", nargs="?", help="入れる場所（省くと空きのいちばん多いドライブの \\AINakawari）")
    parser.add_argument("--reuse-text-gguf", help="開発用: 手元の文の読み取りの GGUF を照らしてから写す（8GB を落とし直さない）")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--no-text-encoder", dest="with_text", action="store_false", default=None,
                        help="プロンプトの読み取り（Llama 3・約 8GB）を入れない（サンプルの文だけで作る。前に入れていれば消す）")
    choice.add_argument("--text-encoder", dest="with_text", action="store_true", help="プロンプトの読み取りを入れる")
    parser.set_defaults(with_text=None)   # どちらも無ければ、前にこの場所で選んだ方
    args = parser.parse_args()
    try:
        setup = Setup(args.dest or default_folder(), log=lambda line: print(line, flush=True),
                      on_step=lambda key, state: print(f"[{state}] {key}", flush=True), reuse_text_gguf=args.reuse_text_gguf,
                      with_text=args.with_text)
        setup.run()
    except (Failed, Cancelled) as e:
        print(f"止まりました: {e}", file=sys.stderr)   # i18n: skip  開発用の手回しの出力
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
