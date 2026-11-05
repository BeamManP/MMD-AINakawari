r"""配布の zip を作る（作る人の手元で回す。使う人は回さない）。

    python tools\release\build_release.py --mmdplugin E:\Downloads\MMDPlugin_v0.41_x64.zip [--mmd-mcp E:\Projects\mmd-mcp] [--allow-dirty]

要る物: Python 3.10.12 以上（このスクリプトを回す物）・uv（PATH）・Visual Studio の C++（プラグインと mmd-mcp の DLL をビルドする）・
MMDPlugin の開発用ファイル（mmd_plugin\build.cmd の AINAKAWARI_SDK）。ネットから落とす物は版と sha256 を固定して照らす。

zip の形（使う人は、中身を MMD のフォルダに展開して「AIナカワリ導入.cmd」をダブルクリックする）:
    AIナカワリ導入.cmd           tools\release\install.cmd（中身は MMD-AINakawari\app\tools\install_plugin.py）
    plugin\MMD-AINakawari\
        MMD-AINakawari.dll/.ini   MMDPlugin 用のプラグインと、その場所の設定（ini のフォルダからの相対）。ここには DLL を増やさない
    MMD-AINakawari\
        python\                   Python 3.10（python-build-standalone。tkinter 入り）＋ 窓の部品 ＋ mmd-mcp
        app\                      mmd_ainakawari・tools の一部・LICENSE・README.md（設定は app\work に書かれる）
        uv\uv.exe                 セットアップで Kimodo・MotionBricks の Python を作る
        mmdplugin\                MMDPlugin 0.41 x64（AIナカワリ導入.cmd が exe の横に置く）
        BUILD.json                作った時の版（コミット・Python・uv）
        THIRD_PARTY.txt           同梱した物とライセンス
    Python などを plugin\ の下に置かないこと。MMDPlugin は plugin\ の下の DLL を奥まで全部読み込もうとして、MMD が起動直後に落ちる
    （2026-11-05 に検証用の MMD で確かめた）。

できた物は work\release\ に置く。work\release\stage は毎回作り直す。落とした物は work\release\cache に残して使い回す。
"""
import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RELEASE = os.path.join(ROOT, "work", "release")
CACHE = os.path.join(RELEASE, "cache")
STAGE = os.path.join(RELEASE, "stage")
NAME = "MMD-AINakawari"
INSTALL_CMD = "AIナカワリ導入.cmd"

# 窓の Python。Kimodo の環境と同じ 3.10.19（版の決まりは python-build-standalone の SHA256SUMS から）
PYTHON_FILE = "cpython-3.10.19+20260114-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
PYTHON_URL = "https://github.com/astral-sh/python-build-standalone/releases/download/20260114/cpython-3.10.19%2B20260114-x86_64-pc-windows-msvc-install_only_stripped.tar.gz"
PYTHON_SHA256 = "57576c3faae0bdf8936daeee59fbdd4853adc65b45e7186fbc2b122cf89393bb"
# uv（2026-11-05 にマスターの手元で使っていた版。sha256 は release の .sha256 から）
UV_VERSION = "0.9.26"
UV_FILE = f"uv-{UV_VERSION}-x86_64-pc-windows-msvc.zip"
UV_URL = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
UV_SHA256 = "eb02fd95d8e0eed462b4a67ecdd320d865b38c560bffcda9a0b87ec944bdf036"
# MMDPlugin 0.41 x64（落とし先は作る人が --mmdplugin で渡す。中身は tools/install_plugin.py の照らしと同じ）
MMDPLUGIN_FILES = {
    "MMDPlugin.dll": "28154f11e24191fff6d1c014f2a9c6f83e771b0b5bedf4c94d1ca3f5ea0801ea",
    "d3d9.dll": "c9bf260655294f020d73679df05247e14507fccd286aad85837e84e7b43e13d5",
    "d3dx9_43.dll": "faa934f1e82de5ef38b65efa5afc7942e6749c4688d77b524b3f80f1f1d41a86",
    "MMDPlugin_readme.txt": "a83df5f7742a0d470f924829dc35d9032b1166bd0d3eb55da38439f5fb2be3f4",
}
# app\ に入れる物（git で管理している物だけ。フォルダは中身ごと）
APP_FILES = (
    "LICENSE",
    "README.md",
    "mmd_ainakawari/",
    "tools/export_skeleton.py",
    "tools/install_plugin.py",
    "tools/kimodo_gen.py",
    "tools/mb_gen.py",
    "tools/prepare_text_encoder.py",
    "tools/start_textencoder.cmd",
)
# 窓で読み込んで確かめる物（mmd_ainakawari の部品と、それが使う mmd-mcp の部品）
SMOKE = (
    "import tkinter; tkinter.Tk().destroy();"
    "import numpy, psutil, win32gui, pydantic;"
    "import mmd_mcp.bone_selection, mmd_mcp.bone_state;"
    "import mmd_ainakawari.app, mmd_ainakawari.panel, mmd_ainakawari.runner, mmd_ainakawari.nakawari,"
    " mmd_ainakawari.pipeline, mmd_ainakawari.smooth_stop, mmd_ainakawari.mmd_link, mmd_ainakawari.mmd_memory,"
    " mmd_ainakawari.mmd_skel, mmd_ainakawari.paths, mmd_ainakawari.applog;"
    "import mmd_ainakawari.installer.window, mmd_ainakawari.installer.steps as s;"
    "import os, mmd_mcp.bone_selection as b; assert os.path.isfile(b.DLL_PATH), b.DLL_PATH;"
    "assert os.path.isfile(s.REQUIREMENTS) and os.path.isfile(s.FETCH_MODEL), s.REQUIREMENTS;"
    "uv = os.path.join(os.path.dirname(s.paths.HOME), 'uv', 'uv.exe'); assert os.path.isfile(uv), uv;"
    "print('ok')"
)
THIRD_PARTY = """AIナカワリ の zip に同梱している物

- Python 3.10.19（python-build-standalone {pbs}）: Python Software Foundation License ほか。python\\LICENSE.txt
- numpy・psutil・pywin32・pydantic・pydantic-core・annotated-types・typing-extensions・typing-inspection:
  各ライセンスは python\\Lib\\site-packages\\*.dist-info の中
- mmd-mcp（https://github.com/BeamManP/mmd-mcp）: MIT-0（DLL の中の Microsoft のランタイムは THIRD_PARTY_NOTICES.md）。
  python\\Lib\\site-packages\\mmd_mcp-*.dist-info の中
- uv {uv}（https://github.com/astral-sh/uv）: MIT OR Apache-2.0
- MMDPlugin 0.41 x64（おいがみ）: 転載は非商用に限り連絡不要。mmdplugin\\MMDPlugin_readme.txt
  d3dx9_43.dll も MMDPlugin の物（中で Windows の d3dx9_43.dll を呼ぶ中継。Microsoft の DirectX の物ではない）

AI のモデル（Kimodo・MotionBricks・Meta Llama 3・LLM2Vec）と、それを動かす Python の部品は同梱していない。
詳細の窓の「セットアップ」が、使う人がライセンスに同意してから、それぞれの配布元から落とす:
- Kimodo（NVIDIA）: コードは Apache-2.0、モデルは NVIDIA Open Model License
- MotionBricks（NVIDIA）: コードは Apache-2.0、モデルは NVIDIA Open Model Agreement
- Meta-Llama-3-8B-Instruct（Meta）: Meta Llama 3 Community License・Acceptable Use Policy。Built with Meta Llama 3
- LLM2Vec（McGill-NLP）: MIT
"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(args, **kw):
    print("> " + " ".join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], check=True, **kw)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def repo_state(repo, allow_dirty):
    commit = git(repo, "rev-parse", "HEAD")
    dirty = bool(git(repo, "status", "--porcelain"))
    if dirty and not allow_dirty:
        raise SystemExit(f"{repo} にコミットしていない変更があります。コミットするか、試しなら --allow-dirty を付けてください")
    return {"commit": commit, "dirty": dirty}


def fetch(url, name, digest):
    """cache に落として sha256 で照らす。合わない物は消して止める。"""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if os.path.isfile(path) and sha256(path) == digest:
        return path
    print(f"落とします: {url}", flush=True)
    urllib.request.urlretrieve(url, path + ".partial")
    if sha256(path + ".partial") != digest:
        os.remove(path + ".partial")
        raise SystemExit(f"{name} の sha256 が決めた値と違います。落とし直すか、版の決まりを確かめてください")
    os.replace(path + ".partial", path)
    return path


def put_python(plugin_dir, mmd_mcp):
    archive = fetch(PYTHON_URL, PYTHON_FILE, PYTHON_SHA256)
    with tarfile.open(archive) as tar:
        tar.extractall(plugin_dir, filter="data")   # 中身は python\ の下
    python = os.path.join(plugin_dir, "python", "python.exe")
    for exe in (python, os.path.join(plugin_dir, "python", "pythonw.exe")):
        if not os.path.isfile(exe):
            raise SystemExit(f"{exe} がありません（{PYTHON_FILE} の形が変わった？）")
    requirements = os.path.join(ROOT, "tools", "release", "requirements.txt")
    run(["uv", "pip", "install", "--python", python, "--require-hashes", "--no-deps", "-r", requirements])
    # mmd-mcp の依存（MCP のサーバー・画面の撮影）は窓で使わないので入れない。要る物は requirements.txt にある
    run(["uv", "pip", "install", "--python", python, "--no-deps", "--reinstall-package", "mmd-mcp", mmd_mcp])
    return python


def put_app(app_dir, allow_dirty):
    tracked = git(ROOT, "ls-files", "-z", "--", *APP_FILES).split("\0")
    files = [f for f in tracked if f]
    for want in APP_FILES:
        if not any(f == want or (want.endswith("/") and f.startswith(want)) for f in files):
            raise SystemExit(f"{want} が git で管理されていません（新しいファイルなら git add してください）")
    for f in files:
        dst = os.path.join(app_dir, *f.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, *f.split("/")), dst)
    return len(files)


def put_uv(plugin_dir):
    archive = fetch(UV_URL, UV_FILE, UV_SHA256)
    out = os.path.join(plugin_dir, "uv")
    os.makedirs(out)
    with zipfile.ZipFile(archive) as z:
        names = [n for n in z.namelist() if os.path.basename(n) == "uv.exe"]
        if len(names) != 1:
            raise SystemExit(f"{UV_FILE} の中に uv.exe が 1 つではありません: {names}")
        with z.open(names[0]) as src, open(os.path.join(out, "uv.exe"), "wb") as dst:
            shutil.copyfileobj(src, dst)


def put_mmdplugin(plugin_dir, zip_path):
    out = os.path.join(plugin_dir, "mmdplugin")
    os.makedirs(out)
    with zipfile.ZipFile(zip_path) as z:
        for name, digest in MMDPLUGIN_FILES.items():
            data = z.read(name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise SystemExit(f"{zip_path} の {name} が MMDPlugin 0.41 x64 の物と違います")
            with open(os.path.join(out, name), "wb") as f:
                f.write(data)


def write_zip(path):
    tmp = path + ".partial"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(STAGE):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                z.write(full, os.path.relpath(full, STAGE).replace(os.sep, "/"))   # 日本語の名前は UTF-8 の印つきになる
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mmdplugin", required=True, help="MMDPlugin_v0.41_x64.zip（おいがみさんの配布物）")
    parser.add_argument("--mmd-mcp", default=os.path.join(os.path.dirname(ROOT), "mmd-mcp"), help="mmd-mcp のリポジトリ")
    parser.add_argument("--allow-dirty", action="store_true", help="コミットしていない変更があっても作る（試し用。zip の名前に dirty が付く）")
    args = parser.parse_args()
    if sys.version_info < (3, 10, 12):
        raise SystemExit("Python 3.10.12 以上で回してください（tar の展開の安全な読み方を使う）")
    mmd_mcp = os.path.abspath(args.mmd_mcp)
    state = {"ainakawari": repo_state(ROOT, args.allow_dirty), "mmd_mcp": repo_state(mmd_mcp, args.allow_dirty)}

    run(["cmd", "/c", os.path.join(ROOT, "mmd_plugin", "build.cmd")])
    run(["cmd", "/c", os.path.join(mmd_mcp, "scripts", "build_native.cmd")])

    shutil.rmtree(STAGE, ignore_errors=True)
    if os.path.exists(STAGE):
        raise SystemExit(f"{STAGE} を消せませんでした（開いているプログラムが無いか確かめてください）")
    mmd_plugin_dir = os.path.join(STAGE, "plugin", NAME)   # MMDPlugin が読む所。DLL と ini だけ
    plugin_dir = os.path.join(STAGE, NAME)                  # Python などの置き場
    os.makedirs(mmd_plugin_dir)
    os.makedirs(plugin_dir)
    shutil.copyfile(os.path.join(ROOT, "tools", "release", "install.cmd"), os.path.join(STAGE, INSTALL_CMD))
    shutil.copyfile(os.path.join(ROOT, "mmd_plugin", "bin", f"{NAME}.dll"), os.path.join(mmd_plugin_dir, f"{NAME}.dll"))
    shutil.copyfile(os.path.join(ROOT, "tools", "release", f"{NAME}.ini"), os.path.join(mmd_plugin_dir, f"{NAME}.ini"))
    python = put_python(plugin_dir, mmd_mcp)
    count = put_app(os.path.join(plugin_dir, "app"), args.allow_dirty)
    put_uv(plugin_dir)
    put_mmdplugin(plugin_dir, args.mmdplugin)

    stray = [os.path.join(r, f) for r, _, fs in os.walk(os.path.join(STAGE, "plugin")) for f in fs if f.lower() != f"{NAME}.ini".lower()
             and f.lower() != f"{NAME}.dll".lower()]
    if stray:
        raise SystemExit(f"plugin\\ の下に DLL と ini のほかの物があります（MMDPlugin が読み込んで MMD が落ちる）: {stray[:5]}")
    print("確かめています: 同梱の Python で窓の部品を読み込む", flush=True)
    run([python, "-B", "-c", SMOKE], cwd=os.path.join(plugin_dir, "app"))

    sys.path.insert(0, ROOT)
    from mmd_ainakawari import __version__
    dirty = state["ainakawari"]["dirty"] or state["mmd_mcp"]["dirty"]
    build = {
        "version": __version__,
        "built": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        **state,
        "python": PYTHON_FILE,
        "uv": UV_VERSION,
        "mmdplugin": "0.41 x64",
    }
    with open(os.path.join(plugin_dir, "BUILD.json"), "w", encoding="utf-8") as f:
        json.dump(build, f, indent=1, ensure_ascii=False)
    with open(os.path.join(plugin_dir, "THIRD_PARTY.txt"), "w", encoding="utf-8") as f:
        f.write(THIRD_PARTY.format(pbs=PYTHON_FILE.split("+")[1].split("-")[0], uv=UV_VERSION))

    name = f"{NAME}-{__version__}" + (f"-dirty-{state['ainakawari']['commit'][:7]}" if dirty else "") + ".zip"
    out = os.path.join(RELEASE, name)
    write_zip(out)
    print(f"できました: {out}（{os.path.getsize(out) / 1e6:.0f} MB・app のファイル {count} 個）")


if __name__ == "__main__":
    main()
