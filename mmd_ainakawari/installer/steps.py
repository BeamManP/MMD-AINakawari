"""セットアップの本体（画面は window.py）。Kimodo（と MotionBricks）を 1 つのフォルダに入れて、work\\paths.json に書く。

入れる形（<場所> はセットアップで選んだフォルダ。半角の英数字のパスだけ）:
    <場所>\\kimodo\\         .venv・repo（GitHub の zip）・hf_cache（Kimodo のモデル）・text_encoders（Llama 3 ＋ LLM2Vec）・
                           tools\\somaskel30.json・start_textencoder.cmd   … paths.py の Kimodo の形
    <場所>\\motionbricks\\   GitHub の zip の中身・LFS の 3 ファイル・.venv（uv sync）・.trt-cache（TensorRT の準備）
    <場所>\\uv\\             uv の控え（cache）と uv が落とした Python（python）
    <場所>\\hf_home\\        セットアップ中の huggingface_hub の置き場所（ユーザーのフォルダに物を作らない）
    <場所>\\downloads\\      落とした zip（展開したら消す）
    <場所>\\setup_state.json  済んだ段（段の名前 → 版）
段ごとに済んだ印を残すので、途中で止まっても（失敗・中止・PC の再起動）、もう一度押せば続きから進む。
ある段をやり直したら、同じ組（Kimodo・MotionBricks）の後ろの段の印も消す（前の段の作り直しで、後ろの段の物が壊れうるため）。
git・Python・Hugging Face のアカウントは要らない（uv は zip に同梱。Python は uv が落とす）。

手で回す時（窓と同じ Python で。--reuse-hf-cache は開発用: Llama の重みが入ったキャッシュから写す）:
    python -m mmd_ainakawari.installer.steps D:\\AINakawari [--motionbricks] [--reuse-hf-cache F:\\kimodo\\hf_cache]
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
import urllib.request
import zipfile

from .. import paths
from . import pins

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(HERE, "kimodo-requirements.txt")
FETCH_MODEL = os.path.join(HERE, "fetch_kimodo_model.py")
TOOLS = os.path.join(paths.HOME, "tools")
STATE_FILE = "setup_state.json"
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
PROGRESS_RE = re.compile(r"\d+%\||\d+(\.\d+)?\s*[kMG]?i?B/s|^\s*(Downloading|Downloaded|Fetching|Building|Built)\b")


class Failed(Exception):
    """段が失敗した（使う人に見せる文）。"""


class Cancelled(Exception):
    """中止のボタンで止めた。"""


def sha256(path, stop=None):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            if stop is not None and stop.is_set():
                raise Cancelled()
            h.update(block)
    return h.hexdigest()


def file_sha256(path):
    return sha256(path)[:16]


def find_uv():
    """配布の zip では MMD-AINakawari\\uv\\uv.exe（app の隣）。リポジトリから動かす開発版は PATH の uv。"""
    bundled = os.path.join(os.path.dirname(paths.HOME), "uv", "uv.exe")
    if os.path.isfile(bundled):
        return bundled
    found = shutil.which("uv")
    if found:
        return found
    raise Failed(f"uv が見つかりません（{bundled} が無い）。zip の中身を全部展開し直してください")


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
    raise Failed(f"組み立て済みの部品（{PREBUILT}\\{MOTION_CORRECTION_JSON}）がありません。zip の中身を全部展開し直してください")


def check_vc_runtime():
    """torch と MotionCorrection は Visual C++ のランタイム（System32 の msvcp140.dll）を要る。zip には入れられないので、無ければ案内する。"""
    system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
    if not os.path.isfile(os.path.join(system, "msvcp140.dll")):
        raise Failed("Microsoft Visual C++ 再頒布可能パッケージ（x64）が入っていません。\n"
                     f"{VC_REDIST_URL} から落として入れてから、もう一度押してください（Microsoft の公式の物です）")


def check_folder(dest):
    """入れる場所に使えるか。使えなければ Failed（理由と直し方）。"""
    if not FOLDER_RE.match(dest or ""):
        raise Failed("入れる場所は「D:\\AINakawari」のような、ドライブから始まる半角の英数字だけのフォルダにしてください。\n"
                     "日本語・空白・記号（& ( ) など）が入ると、途中の部品が動かないことがあります。")
    drive = os.path.splitdrive(dest)[0] + "\\"
    if not os.path.isdir(drive):
        raise Failed(f"ドライブ {drive} がありません")
    if (os.path.normcase(os.path.abspath(dest)) + os.sep).startswith(os.path.normcase(paths.HOME) + os.sep):
        raise Failed(f"AIナカワリ の窓のフォルダ（{paths.HOME}）の中には入れられません。別のフォルダにしてください")


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


class Setup:
    """1 回のセットアップ。run() は時間がかかるので、画面からは裏のスレッドで回す。cancel() は別のスレッドから呼んでよい。

    log(行): ログに残す 1 行。progress(文): 上書きの 1 行（落としている途中の量など）。
    on_step(段の名前, "skip" | "run" | "done" | "fail"): 段の印を画面に出す。
    """

    def __init__(self, dest, motionbricks, log=print, progress=None, on_step=None, reuse_hf_cache=None):
        check_folder(dest)
        self.dest = dest
        self.motionbricks = motionbricks
        self.log = log
        self.progress = progress or (lambda _text: None)
        self.on_step = on_step or (lambda _key, _state: None)
        self.reuse_hf_cache = reuse_hf_cache
        self.kimodo = os.path.join(dest, "kimodo")
        self.mb = os.path.join(dest, "motionbricks")
        self.downloads = os.path.join(dest, "downloads")
        self.state_path = os.path.join(dest, STATE_FILE)
        self.uv = None
        self._stop = threading.Event()
        self._proc = None

    # ---- 段の並び --------------------------------------------------------------------------------
    def steps(self):
        """[(名前, 組, 見出し, 版, 使う GB, 関数)]。版が setup_state.json の物と同じ段は飛ばす。"""
        k = [
            ("kimodo_src", "kimodo", "Kimodo の本体を落とす", pins.KIMODO_COMMIT, 0.2, self.kimodo_src),
            ("kimodo_env", "kimodo", "Kimodo の Python の環境を作る（約 5GB）",
             f"{pins.KIMODO_COMMIT}/{pins.KIMODO_PYTHON}/{file_sha256(REQUIREMENTS)}/{self._prebuilt_version()}", 5.5,
             self.kimodo_env),
            ("skeleton", "kimodo", "骨格を書き出す", file_sha256(os.path.join(TOOLS, "export_skeleton.py")), 0, self.skeleton),
            ("kimodo_model", "kimodo", "Kimodo のモデルを落とす（約 1GB）", pins.KIMODO_MODEL_REVISION, 1.2, self.kimodo_model),
            ("text_encoder", "kimodo", "文の読み取りのモデルを落とす（約 16GB。いちばん長くかかります）",
             file_sha256(os.path.join(TOOLS, "prepare_text_encoder.py")), 15.6, self.text_encoder),
            ("server_cmd", "kimodo", "高速モードの起動バッチを置く", file_sha256(os.path.join(TOOLS, "start_textencoder.cmd")), 0,
             self.server_cmd),
            ("kimodo_test", "kimodo", "Kimodo で試しに作って、場所を書く", pins.KIMODO_COMMIT, 0, self.kimodo_test),
        ]
        m = [
            ("mb_src", "mb", "MotionBricks の本体を落とす", pins.MOTIONBRICKS_COMMIT, 0.2, self.mb_src),
            ("mb_models", "mb", "MotionBricks のモデルを落とす（約 1.1GB）", pins.MOTIONBRICKS_COMMIT, 1.2, self.mb_models),
            ("mb_env", "mb", "MotionBricks の Python の環境を作る（約 3GB）",
             f"{pins.MOTIONBRICKS_COMMIT}/{pins.MOTIONBRICKS_PYTHON}", 3.3, self.mb_env),
            ("mb_test", "mb", "MotionBricks で試しに作って、場所を書く（初回は TensorRT の準備で数分）", pins.MOTIONBRICKS_COMMIT, 0.8,
             self.mb_test),
        ]
        return k + (m if self.motionbricks else [])

    def load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def save_state(self, state):
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)

    def remaining_gb(self):
        state = self.load_state()
        return sum(gb for key, _g, _t, version, gb, _fn in self.steps() if state.get(key) != version)

    def run(self):
        os.makedirs(self.dest, exist_ok=True)
        need, free = self.remaining_gb(), free_gb(self.dest)
        if free < need:
            raise Failed(f"空きが足りません。残りの段で約 {need:.0f}GB 使いますが、{os.path.splitdrive(self.dest)[0]} の空きは "
                         f"{free:.0f}GB です。空きを作るか、別のドライブを選んでください")
        check_vc_runtime()
        motion_correction_info()   # 部品が欠けた zip なら、落とし始める前に止める
        self.uv = find_uv()
        self.log(f"入れる場所: {self.dest}（空き {free:.0f}GB・残りの段で約 {need:.0f}GB）")
        self.log(f"uv: {self.uv}")
        state = self.load_state()
        steps = self.steps()
        for i, (key, group, title, version, _gb, fn) in enumerate(steps):
            if state.get(key) == version:
                self.on_step(key, "skip")
                continue
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
            self.save_state(state)
            self.on_step(key, "done")
            self.log(f"   済み（{time.time() - t0:.0f} 秒）")
        shutil.rmtree(self.downloads, ignore_errors=True)
        self.log("セットアップが終わりました")

    def cancel(self):
        self._stop.set()
        proc = self._proc
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
        env.update(extra)
        return env

    def call(self, args, what, cwd=None, **extra_env):
        """外のプロセスを回し、出力をログ（と上書きの 1 行）に流す。失敗したら Failed。"""
        if self._stop.is_set():
            raise Cancelled()
        self.log("> " + subprocess.list2cmdline(args))
        self._proc = proc = subprocess.Popen(args, cwd=cwd, env=self.env(**extra_env), stdin=subprocess.DEVNULL,
                                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        buf = b""
        tail = []

        def emit(line, overwrite):
            nonlocal tail
            text = line.decode("utf-8", "replace").rstrip()
            if not text:
                return
            if overwrite or PROGRESS_RE.search(text):
                self.progress(text[-160:])
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
        self._proc = None
        if self._stop.is_set():
            raise Cancelled()
        if rc != 0:
            raise Failed(f"{what} が失敗しました（終了コード {rc}）。\n" + "\n".join(tail[-6:]))

    def download(self, url, target, label, digest=None, size=None):
        """url を target に落とす。途中の .part があれば続きから（サーバーが応じれば）。digest があれば sha256 で照らす。"""
        os.makedirs(os.path.dirname(target), exist_ok=True)
        part = target + ".part"
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if size is not None and have > size:
            os.remove(part)
            have = 0
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if have:
            request.add_header("Range", f"bytes={have}-")
        try:
            response = urllib.request.urlopen(request, timeout=60, context=tls_context())
        except OSError as e:
            raise Failed(f"{label} を落とせませんでした（{e}）。ネットにつながっているか確かめて、もう一度押してください") from None
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
                        raise Failed(f"{label} を落とす途中で切れました（{e}）。もう一度押すと続きから落とします") from None
                    if not block:
                        break
                    f.write(block)
                    done += len(block)
                    if time.time() - last > 0.5:
                        last = time.time()
                        self.progress(f"{label}: {done / 1e6:,.0f} / {total / 1e6:,.0f} MB" if total else f"{label}: {done / 1e6:,.0f} MB")
        if size is not None and os.path.getsize(part) != size:
            raise Failed(f"{label} の大きさが違います（{os.path.getsize(part)} バイト・正しくは {size}）。もう一度押してください")
        if digest:
            self.progress(f"{label}: 中身を確かめています")
            if sha256(part, self._stop) != digest:
                os.remove(part)
                raise Failed(f"{label} の中身が違います（壊れて届いたかもしれません）。もう一度押してください")
        os.replace(part, target)

    def fetch_zip(self, url, name, into, keep=()):
        """GitHub の zip を落として、中の 1 つのフォルダの中身を into に置く。keep の名前の物（.venv など）は into に残す。"""
        archive = os.path.join(self.downloads, f"{name}.zip")
        if not os.path.isfile(archive):
            self.download(url, archive, f"{name} の zip")
        work = into + ".extract"
        shutil.rmtree(work, ignore_errors=True)
        self.progress(f"{name} の zip を展開しています")
        try:
            with zipfile.ZipFile(archive) as z:
                z.extractall(work)
        except zipfile.BadZipFile:
            os.remove(archive)
            raise Failed(f"{name} の zip が壊れていました。もう一度押すと落とし直します") from None
        tops = os.listdir(work)
        if len(tops) != 1:
            raise Failed(f"{name} の zip の形が思っていた物と違います（{tops[:3]}）")
        top = os.path.join(work, tops[0])
        if os.path.isdir(into):
            for entry in os.listdir(into):
                if entry in keep:
                    os.replace(os.path.join(into, entry), os.path.join(top, entry))
            shutil.rmtree(into)
        os.replace(top, into)
        shutil.rmtree(work, ignore_errors=True)

    def kimodo_python(self):
        return os.path.join(self.kimodo, ".venv", "Scripts", "python.exe")

    def mb_python(self):
        return os.path.join(self.mb, ".venv", "Scripts", "python.exe")

    # ---- Kimodo -------------------------------------------------------------------------------------
    def kimodo_src(self):
        self.fetch_zip(pins.KIMODO_ZIP, f"kimodo-{pins.KIMODO_COMMIT[:7]}", os.path.join(self.kimodo, "repo"))

    def kimodo_env(self):
        venv = os.path.join(self.kimodo, ".venv")
        self.call([self.uv, "venv", venv, "--python", pins.KIMODO_PYTHON, "--clear"], "Python の用意")
        py = self.kimodo_python()
        self.call([self.uv, "pip", "install", "--python", py, "--require-hashes", "--index-strategy", "unsafe-best-match",
                   "-r", REQUIREMENTS], "Kimodo の部品を入れる")
        # kimodo 本体は部品表に入れられない（GitHub の zip）ので、部品を入れた後に依存なしで入れる。
        # C++ の部品は組み立てない（SKIP_MOTION_CORRECTION_IN_SETUP は kimodo の setup.py の切り替え）。組み立て済みの物を後で置く
        self.call([self.uv, "pip", "install", "--python", py, "--no-deps", "--no-build-isolation",
                   os.path.join(self.kimodo, "repo")], "Kimodo を入れる", SKIP_MOTION_CORRECTION_IN_SETUP="1")
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
            raise Failed(f"組み立て済みの部品が、別の版の Kimodo の物です（{info.get('kimodo_commit')}）。zip を落とし直してください")
        pyd = os.path.join(folder, info["file"])
        if not os.path.isfile(pyd) or sha256(pyd) != info["sha256"]:
            raise Failed(f"組み立て済みの部品（{pyd}）が無いか、壊れています。zip を落とし直してください")
        src = os.path.join(self.kimodo, "repo", "MotionCorrection", "python", "motion_correction")
        site = os.path.join(self.kimodo, ".venv", "Lib", "site-packages", "motion_correction")
        shutil.rmtree(site, ignore_errors=True)
        shutil.copytree(src, site, ignore=shutil.ignore_patterns("__pycache__", "*.pyd", "*.so"))
        shutil.copyfile(pyd, os.path.join(site, info["file"]))
        self.call([self.kimodo_python(), "-c", "import torch, motion_correction._motion_correction; print('motion_correction ok')"],
                  "組み立て済みの部品の読み込み")

    def skeleton(self):
        os.makedirs(os.path.join(self.kimodo, "tools"), exist_ok=True)
        self.call([self.kimodo_python(), os.path.join(TOOLS, "export_skeleton.py"),
                   os.path.join(self.kimodo, "tools", "somaskel30.json")], "骨格の書き出し")

    def kimodo_model(self):
        cache = os.path.join(self.kimodo, "hf_cache")
        self.call([self.kimodo_python(), FETCH_MODEL, cache, pins.KIMODO_MODEL_REPO, pins.KIMODO_MODEL_REVISION],
                  "Kimodo のモデルを落とす", HF_HUB_CACHE=cache)

    def text_encoder(self):
        args = [self.kimodo_python(), os.path.join(TOOLS, "prepare_text_encoder.py"), os.path.join(self.kimodo, "text_encoders")]
        if self.reuse_hf_cache:
            args += ["--reuse", self.reuse_hf_cache]
        self.call(args, "文の読み取りのモデルを落とす")

    def server_cmd(self):
        shutil.copyfile(os.path.join(TOOLS, "start_textencoder.cmd"), os.path.join(self.kimodo, "start_textencoder.cmd"))

    def kimodo_test(self):
        """低負荷モードと同じ置き方（文の読み取りは CPU）で 1 回作る。通ったら paths.json に書く。"""
        work = os.path.join(self.dest, "setup_test")
        os.makedirs(work, exist_ok=True)
        req, out = os.path.join(work, "kimodo_request.json"), os.path.join(work, "kimodo_result.json")
        with open(req, "w", encoding="utf-8") as f:
            json.dump({"prompt": "A person walks forward.", "num_frames": 60, "seed": 0}, f)
        if os.path.exists(out):
            os.remove(out)
        self.log("  初めての読み込みなので 1〜3 分かかります（文の読み取りのモデル約 15GB をメインメモリに読みます）")
        self.call([self.kimodo_python(), os.path.join(TOOLS, "kimodo_gen.py"), req, out], "Kimodo の試しの生成", cwd=self.kimodo,
                  HF_HUB_CACHE=os.path.join(self.kimodo, "hf_cache"), TEXT_ENCODERS_DIR=os.path.join(self.kimodo, "text_encoders"),
                  LOCAL_CACHE="true", TEXT_ENCODER_MODE="local", TEXT_ENCODER_DEVICE="cpu", HF_HUB_OFFLINE="1")
        with open(out, encoding="utf-8") as f:
            frames = json.load(f).get("num_frames")
        if not frames:
            raise Failed(f"Kimodo の試しの生成の結果が空でした（{out}）")
        paths.check(self.kimodo, "Kimodo")
        paths.save(kimodo=self.kimodo)
        self.log(f"  Kimodo で {frames} フレーム作れました。場所を書きました: {paths.PATHS_FILE}")

    # ---- MotionBricks -------------------------------------------------------------------------------
    def mb_src(self):
        self.fetch_zip(pins.MOTIONBRICKS_ZIP, f"motionbricks-{pins.MOTIONBRICKS_COMMIT[:7]}", self.mb, keep=(".venv", ".trt-cache"))

    def mb_models(self):
        for path, (digest, size) in pins.MOTIONBRICKS_LFS.items():
            target = os.path.join(self.mb, *path.split("/"))
            name = path.rsplit("/", 1)[-1]
            if os.path.isfile(target) and os.path.getsize(target) == size:
                self.progress(f"{name}: 中身を確かめています")
                if sha256(target, self._stop) == digest:
                    continue
            url = pins.MOTIONBRICKS_LFS_URL.format(commit=pins.MOTIONBRICKS_COMMIT, path=path)
            self.download(url, target, name, digest=digest, size=size)
            self.log(f"  落としました: {name}")

    def mb_env(self):
        self.call([self.uv, "sync", "--frozen", "--python", pins.MOTIONBRICKS_PYTHON], "MotionBricks の部品を入れる", cwd=self.mb)

    def mb_test(self):
        """T ポーズから T ポーズへ 1 回つなぐ。初回は TensorRT のエンジンを作る（.trt-cache。GPU ごとに数分）。通ったら paths.json に書く。"""
        skeleton = os.path.join(self.kimodo, "tools", "somaskel30.json")
        if not os.path.isfile(skeleton):
            raise Failed("Kimodo の骨格がありません。先に Kimodo のセットアップを済ませてください")
        with open(skeleton, encoding="utf-8") as f:
            soma = json.load(f)
        pose = {"root": soma["neutral_joints"][soma["root_idx"]], "local_rot": [0.0, 0.0, 0.0, 1.0] * len(soma["names"])}
        work = os.path.join(self.dest, "setup_test")
        os.makedirs(work, exist_ok=True)
        req, out = os.path.join(work, "mb_request.json"), os.path.join(work, "mb_result.json")
        with open(req, "w", encoding="utf-8") as f:
            json.dump({"skeleton": skeleton, "context": [pose] * 4,
                       "targets": [{"poses": [pose], "frames": 30, "num_poses_to_use": 1}]}, f)
        if os.path.exists(out):
            os.remove(out)
        self.log("  初回は GPU に合わせた TensorRT の準備で数分かかります（止まって見えても進んでいます）")
        self.call([self.mb_python(), os.path.join(TOOLS, "mb_gen.py"), req, out], "MotionBricks の試しの生成", cwd=self.mb)
        with open(out, encoding="utf-8") as f:
            frames = json.load(f).get("num_frames")
        if not frames:
            raise Failed(f"MotionBricks の試しの生成の結果が空でした（{out}）")
        paths.check(self.mb, "MotionBricks")
        paths.save(motionbricks=self.mb)
        self.log(f"  MotionBricks で {frames} フレーム作れました。場所を書きました: {paths.PATHS_FILE}")


def main():
    parser = argparse.ArgumentParser(description="AIナカワリ のセットアップ（ふつうは詳細の窓の「セットアップ」から）")
    parser.add_argument("dest", nargs="?", help="入れる場所（省くと空きのいちばん多いドライブの \\AINakawari）")
    parser.add_argument("--motionbricks", action="store_true", help="MotionBricks も入れる")
    parser.add_argument("--reuse-hf-cache", help="開発用: Llama の重みが入った Hugging Face のキャッシュから写す")
    args = parser.parse_args()
    try:
        setup = Setup(args.dest or default_folder(), args.motionbricks, log=lambda line: print(line, flush=True),
                      on_step=lambda key, state: print(f"[{state}] {key}", flush=True), reuse_hf_cache=args.reuse_hf_cache)
        setup.run()
    except (Failed, Cancelled) as e:
        print(f"止まりました: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
