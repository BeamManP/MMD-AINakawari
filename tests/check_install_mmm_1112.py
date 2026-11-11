"""11-12: AIナカワリ導入.cmd（tools/install_plugin.py）の MMM 版の分かれ道を、一時フォルダで確かめる。窓の Python で回す。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_install_mmm_1112.py

本物の MMD・MMM のフォルダは触らない。MMM の exe は版の照らしのために一時フォルダへ写す（--mmm で場所を変えられる）。
1. MMM のフォルダにそのまま展開 → Plugins\\ に 4 つ置き、MMD 用の plugin\\MMD-AINakawari を片付ける。MMDPlugin は置かない
2. MMM のフォルダの外に展開 → MMD-AINakawari を写して Plugins\\ に置く。展開した所の plugin\\ は触らない
3. 版の違う MikuMikuMoving64.exe → 何も変えずに止まる
4. MMD と MMM が両方ある → 聞く（1 で MMD・2 で MMM・空で止まる）
5. MikuMikuDance.exe だけ → MMD の道（今までどおり）
6. plugin\\MMD-AINakawari に知らない物がある → 片付けない
7. 同梱の ini の場所が、Plugins から見て Python と app を指す
8. MMD の道を最後まで（本物の MikuMikuDance.exe を写して。MMDPlugin を置く・Plugins\\ は作らない）
"""
import argparse
import configparser
import contextlib
import io
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import install_plugin as ip  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--mmm", default=r"E:\Projects\MMM\MikuMikuMoving64\MikuMikuMoving64.exe")
parser.add_argument("--mmd", default=r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\MikuMikuDance.exe")
parser.add_argument("--mmdplugin", default=os.path.join(ROOT, "work", "release", "stage", "MMD-AINakawari", "mmdplugin"),
                    help="MMDPlugin 0.41 の同梱物（前に作った zip の中身）")
args = parser.parse_args()

failed = []


def check(name, ok, detail=""):
    print(("OK  " if ok else "NG  ") + name + ("" if ok else f"  {detail}"))
    if not ok:
        failed.append(name)


def make_zip(folder):
    """展開した zip の形（MMD-AINakawari\\mmm・plugin\\MMD-AINakawari）を folder に作り、install_plugin をそこへ向ける。"""
    here = os.path.join(folder, ip.NAME)
    for name in ip.MMM_FILES:
        path = os.path.join(here, "mmm", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(name)
    os.makedirs(os.path.join(here, "app", "work"))
    with open(os.path.join(here, "app", "app.txt"), "w") as f:
        f.write("app")
    plugin = os.path.join(folder, "plugin", ip.NAME)
    os.makedirs(plugin)
    for n in (f"{ip.NAME}.dll", f"{ip.NAME}.ini"):
        with open(os.path.join(plugin, n), "w") as f:
            f.write(n)
    ip.HERE, ip.MMM_SRC, ip.PLUGIN_SRC = here, os.path.join(here, "mmm"), plugin


def run(start):
    out = io.StringIO()
    old = sys.argv
    sys.argv = ["install_plugin.py", start]
    try:
        with contextlib.redirect_stdout(out):
            code = ip.main()
    finally:
        sys.argv = old
    return code, out.getvalue()


def placed(mmm):
    return all(os.path.isfile(os.path.join(mmm, "Plugins", n)) for n in ip.MMM_FILES)


tmp = tempfile.mkdtemp(prefix="ainakawari_install_mmm_")
try:
    # 1. MMM のフォルダにそのまま展開
    mmm = os.path.join(tmp, "MMM 1")
    os.makedirs(os.path.join(mmm, "Plugins"))
    shutil.copyfile(args.mmm, os.path.join(mmm, ip.MMM_EXE))
    make_zip(mmm)
    code, out = run(mmm)
    check("1. 成功する", code == 0, out)
    check("1. Plugins に 4 つ置く（橋渡しの中身は MmmBridgeCore の下）", placed(mmm), os.listdir(os.path.join(mmm, "Plugins")))
    check("1. MMD 用の plugin\\MMD-AINakawari を片付ける（空になった plugin も）", not os.path.exists(os.path.join(mmm, "plugin")), out)
    check("1. MMDPlugin は置かない", not any(os.path.exists(os.path.join(mmm, n)) for n in ip.MMDPLUGIN_FILES), os.listdir(mmm))
    check("1. MMM の案内で終わる", "ツールバーに「AIナカワリ」" in out, out)
    code, out = run(mmm)
    check("1. もう一度回しても通る（更新の時）", code == 0 and placed(mmm), out)

    # 2. MMM のフォルダの外に展開
    outside = os.path.join(tmp, "zip")
    mmm2 = os.path.join(tmp, "MMM 2")
    os.makedirs(mmm2)   # Plugins が無くても作る
    shutil.copyfile(args.mmm, os.path.join(mmm2, ip.MMM_EXE))
    make_zip(outside)
    code, out = run(mmm2)
    check("2. 成功する", code == 0, out)
    check("2. MMD-AINakawari を写す（work は写さない）", os.path.isfile(os.path.join(mmm2, ip.NAME, "app", "app.txt"))
          and not os.path.exists(os.path.join(mmm2, ip.NAME, "app", "work")), out)
    check("2. Plugins に 4 つ置く", placed(mmm2))
    check("2. MMM に plugin\\ を作らない・展開した所の plugin\\ は残す",
          not os.path.exists(os.path.join(mmm2, "plugin")) and os.path.isdir(os.path.join(outside, "plugin", ip.NAME)))

    # 3. 版の違う exe
    mmm3 = os.path.join(tmp, "MMM 3")
    os.makedirs(mmm3)
    with open(os.path.join(mmm3, ip.MMM_EXE), "wb") as f:
        f.write(b"MZ not 1.2.9.2")
    make_zip(mmm3)
    code, out = run(mmm3)
    check("3. 止まる", code == 1 and "1.2.9.2" in out, out)
    check("3. 何も変えない", not os.path.exists(os.path.join(mmm3, "Plugins")) and os.path.isdir(os.path.join(mmm3, "plugin", ip.NAME)))

    # 4. 両方ある
    both = os.path.join(tmp, "both")
    os.makedirs(both)
    for exe in (ip.EXE, ip.MMM_EXE):
        open(os.path.join(both, exe), "w").close()
    answers = iter(["3", "2"])
    with contextlib.redirect_stdout(io.StringIO()):
        kind = ip.ask_host(both, ask=lambda _p: next(answers))
    check("4. 違う答えは聞き直し、2 で MMM", kind == "mmm", kind)
    with contextlib.redirect_stdout(io.StringIO()):
        kind = ip.ask_host(both, ask=lambda _p: "１")
    check("4. 全角の 1 でも MMD", kind == "mmd", kind)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            ip.ask_host(both, ask=lambda _p: "")
        check("4. 空なら止まる", False)
    except ip.Stop:
        check("4. 空なら止まる", True)
    ip_ask = ip.ask_host
    ip.ask_host = lambda folder, ask=input: "mmm"
    check("4. choose_target が聞いた方を使う", ip.choose_target(both) == (both, "mmm"))
    ip.ask_host = ip_ask

    # 5. MMD だけ
    mmd = os.path.join(tmp, "mmd")
    os.makedirs(mmd)
    open(os.path.join(mmd, ip.EXE), "w").close()
    check("5. MikuMikuDance.exe だけなら MMD の道", ip.choose_target(mmd) == (mmd, "mmd"))

    # 6. plugin\MMD-AINakawari に知らない物
    mmm6 = os.path.join(tmp, "MMM 6")
    os.makedirs(mmm6)
    shutil.copyfile(args.mmm, os.path.join(mmm6, ip.MMM_EXE))
    make_zip(mmm6)
    open(os.path.join(mmm6, "plugin", ip.NAME, "自分の.txt"), "w").close()
    code, out = run(mmm6)
    check("6. 知らない物があれば plugin\\MMD-AINakawari は片付けない",
          code == 0 and os.path.isfile(os.path.join(mmm6, "plugin", ip.NAME, "自分の.txt")), out)

    # 8. MMD の道を最後まで（分かれ道で今までの導入を壊していないか）
    if os.path.isfile(args.mmd) and os.path.isdir(args.mmdplugin):
        mmd8 = os.path.join(tmp, "MMD 8")
        os.makedirs(mmd8)
        shutil.copyfile(args.mmd, os.path.join(mmd8, ip.EXE))
        make_zip(mmd8)
        shutil.copytree(args.mmdplugin, os.path.join(ip.HERE, "mmdplugin"))
        ip.MMDPLUGIN_SRC = os.path.join(ip.HERE, "mmdplugin")
        code, out = run(mmd8)
        check("8. MMD の道が通る", code == 0 and "メニューの「ヘルプ」の右" in out, out)
        check("8. MMDPlugin を exe の横に置き、plugin\\MMD-AINakawari は残す、Plugins は作らない",
              all(os.path.isfile(os.path.join(mmd8, n)) for n in ("MMDPlugin.dll", "d3d9.dll", "d3dx9_43.dll"))
              and os.path.isdir(os.path.join(mmd8, "plugin", ip.NAME)) and not os.path.exists(os.path.join(mmd8, "Plugins")), os.listdir(mmd8))
    else:
        print("--  8. MMD の exe か MMDPlugin の同梱物が無いので飛ばしました（--mmd・--mmdplugin）")

    # 7. 同梱の ini
    ini = configparser.ConfigParser()
    ini.read(os.path.join(ROOT, "tools", "release", "MMM-AINakawari.ini"), encoding="utf-8")
    sec = ini["MMM-AINakawari"]
    plugins = os.path.join("X", "Plugins")
    check("7. python は MMD-AINakawari\\python\\pythonw.exe",
          os.path.normpath(os.path.join(plugins, sec["python"])) == os.path.join("X", ip.NAME, "python", "pythonw.exe"), sec["python"])
    check("7. home は MMD-AINakawari\\app", os.path.normpath(os.path.join(plugins, sec["home"])) == os.path.join("X", ip.NAME, "app"), sec["home"])
    check("7. instance を書かない（配布版）", "instance" not in sec)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("全部 OK" if not failed else f"NG {len(failed)} 件: {failed}")
sys.exit(1 if failed else 0)
