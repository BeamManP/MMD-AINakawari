"""AIナカワリ の導入。配布の zip の「AIナカワリ導入.cmd」から、同梱の Python で動く。

MMD のフォルダ（MikuMikuDance.exe のある所）に:
    - MMD-AINakawari\\（Python・app など）と plugin\\MMD-AINakawari\\（DLL と ini だけ）を置く。
      zip を MMD のフォルダの外に展開した時は、選んでもらった MMD のフォルダへ写す。
      Python を plugin\\ の下に置かないのは、MMDPlugin が plugin\\ の下の DLL を全部読み込もうとして MMD が落ちるため
    - MMDPlugin（MMDPlugin.dll・d3d9.dll・d3dx9_43.dll。d3dx9_43.dll は MMDPlugin の中継で、Microsoft の物ではない）を
      exe の横に置く。MMDPlugin が既に入っていれば何もしない
    - MME（exe の横の d3d9.dll・MMEffect.dll・MMHack.dll・MMEffect.ini・MMEffect.txt）を plugin\\mme\\ に移す。
      MMDPlugin の説明書の「MME も使う場合」の形
自前の d3d9.dll は作らない。MME でも MMDPlugin でもない d3d9.dll が exe の横にあれば、触らずに止める。
途中で止まっても、もう一度ダブルクリックすれば続きから直る（d3d9.dll を最後に置く）。
"""
import hashlib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # （zip の中の）MMD-AINakawari
NAME = "MMD-AINakawari"
PLUGIN_SRC = os.path.join(os.path.dirname(HERE), "plugin", NAME)                         # （zip の中の）plugin\MMD-AINakawari
EXE = "MikuMikuDance.exe"
MMDPLUGIN_SRC = os.path.join(HERE, "mmdplugin")
# MMDPlugin 0.41 x64（おいがみさん。転載は非商用なら連絡不要）。同梱の物が壊れていないかを照らす
MMDPLUGIN_FILES = {
    "MMDPlugin.dll": "28154f11e24191fff6d1c014f2a9c6f83e771b0b5bedf4c94d1ca3f5ea0801ea",
    "d3dx9_43.dll": "faa934f1e82de5ef38b65efa5afc7942e6749c4688d77b524b3f80f1f1d41a86",
    "d3d9.dll": "c9bf260655294f020d73679df05247e14507fccd286aad85837e84e7b43e13d5",   # 最後に置く（置けたら導入済み）
}
MMDPLUGIN_README = "MMDPlugin_readme.txt"
MME_FILES = ("d3d9.dll", "MMEffect.dll", "MMHack.dll", "MMEffect.ini", "MMEffect.txt")


class Stop(Exception):
    """使う人に伝えて止める（何が起きたか・どうすればよいか）。"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def copy_atomic(src, dst):
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    os.replace(tmp, dst)


def is_mmd(folder):
    return os.path.isfile(os.path.join(folder, EXE))


def choose_mmd(start):
    if is_mmd(start):
        return start
    print("この zip は MMD のフォルダの外に展開されています。")
    print("MikuMikuDance.exe のあるフォルダを選んでください（選んだフォルダに AIナカワリ を写します）。")
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    try:
        while True:
            folder = filedialog.askdirectory(title="MikuMikuDance.exe のあるフォルダを選んでください", mustexist=True)
            if not folder:
                raise Stop("フォルダが選ばれなかったので、何もせずに終わります。")
            folder = os.path.normpath(folder)
            if is_mmd(folder):
                return folder
            print(f"{folder} に MikuMikuDance.exe がありません。選び直してください。")
    finally:
        root.destroy()


def check_version(mmd):
    from mmd_mcp.bone_state import VERIFIED_SHA256
    if sha256(os.path.join(mmd, EXE)) != VERIFIED_SHA256:
        raise Stop("この MikuMikuDance.exe は、AIナカワリ が対応している版（MikuMikuDance 9.32 x64・日本語版）ではありません。\n"
                   "AIナカワリ は MMD の中を読むので、ほかの版では動きません。何も変えずに終わります。")


def check_not_running(mmd):
    import psutil
    exe = os.path.normcase(os.path.join(mmd, EXE))
    for p in psutil.process_iter(["name", "exe"]):
        if (p.info["name"] or "").lower() != EXE.lower():
            continue
        # exe の場所が読めない時は、この MMD かもしれないので止める
        if not p.info["exe"] or os.path.normcase(p.info["exe"]) == exe:
            raise Stop("MMD が開いています。MMD を閉じてから、もう一度ダブルクリックしてください。")


def copy_plugin(mmd):
    """zip を MMD の外に展開した時だけ、MMD-AINakawari と plugin\\MMD-AINakawari を MMD へ写す。前に入れた物の設定（app\\work）は残す。"""
    dest = os.path.join(mmd, NAME)
    if os.path.isdir(dest) and os.path.samefile(dest, HERE):
        return
    if not os.path.isfile(os.path.join(PLUGIN_SRC, f"{NAME}.dll")):
        raise Stop(f"{PLUGIN_SRC} に {NAME}.dll がありません。zip の中身を全部展開し直してください。")
    print(f"写しています: {dest}（1〜2 分かかります）", flush=True)
    shutil.copytree(HERE, dest, dirs_exist_ok=True,
                    ignore=lambda folder, names: [n for n in names if n in ("work", "__pycache__")])
    shutil.copytree(PLUGIN_SRC, os.path.join(mmd, "plugin", NAME), dirs_exist_ok=True)


FOREIGN_D3DX9 = ("MikuMikuDance.exe の横に、MMDPlugin の物ではない d3dx9_43.dll があります。\n"
                 "MMDPlugin は自前の d3dx9_43.dll（中で Windows の物を呼びます）を同じ場所に置く必要があるので、何も変えずに止めます。\n"
                 "今の d3dx9_43.dll を別のフォルダへ移してから、もう一度ダブルクリックしてください。")


def plan_mme(mmd):
    """exe の横の MME を plugin\\mme に移す手順 [(元, 先, 先に同じ中身がある)] を、何も変えずに調べる。
    移す先に中身の違う同じ名前の物があれば Stop（どれも動かす前に止める。11-06 Codex のレビュー: 途中まで移してから止まっていた）。"""
    mme_dir = os.path.join(mmd, "plugin", "mme")
    moves = []
    for name in MME_FILES:
        src = os.path.join(mmd, name)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(mme_dir, name)
        same = os.path.exists(dst)
        if same and sha256(dst) != sha256(src):
            raise Stop(f"MME を plugin\\mme に移そうとしましたが、{dst} に中身の違う {name} があります。\n"
                       "どちらを使うか決められないので、何も変えずに止めます。どちらかを片付けてから、もう一度ダブルクリックしてください。")
        moves.append((src, dst, same))
    return moves


def move_mme(moves):
    for src, dst, same in moves:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if same:
            os.remove(src)   # 移す先に同じ中身がある（前に途中まで移した時など）
        else:
            os.replace(src, dst)
        print(f"MME を移しました: {os.path.basename(src)} → plugin\\mme\\", flush=True)


def place_mmdplugin(mmd):
    """確かめることを全部確かめてから、MME を移して MMDPlugin を置く（止まる時は何も変えていない）。"""
    root = lambda name: os.path.join(mmd, name)
    is_ours = lambda name: sha256(root(name)) == MMDPLUGIN_FILES[name]
    for name, digest in MMDPLUGIN_FILES.items():
        if sha256(os.path.join(MMDPLUGIN_SRC, name)) != digest:
            raise Stop(f"同梱の {name} が壊れています。zip を落とし直して、展開し直してください。")
    # MMDPlugin 0.41 の d3dx9_43.dll は Microsoft の物ではなく、中で Windows（System32）の物を呼ぶ MMDPlugin の中継
    # （133KB・署名なし。説明書の導入の手順は 2 つだけだが、0.41 で「d3dx9 のフック」が足された）。
    # 11-06 に検証用の MMD で、これが無いと起動直後に 0xC000041D で落ちるのを確かめた。なので別の d3dx9_43.dll があれば止める
    d3dx9 = root("d3dx9_43.dll")
    if os.path.isfile(root("MMDPlugin.dll")) and os.path.isfile(root("d3d9.dll")) and not os.path.isfile(root("MMEffect.dll")):
        # 入っている。0.41 の d3d9.dll なら、中継の d3dx9_43.dll もそろっているかを見る（11-06 Codex のレビュー）。
        # ほかの版の MMDPlugin なら、その版の作りに任せる
        if is_ours("d3d9.dll"):
            if os.path.isfile(d3dx9) and not is_ours("d3dx9_43.dll"):
                raise Stop(FOREIGN_D3DX9)
            if not os.path.isfile(d3dx9):
                copy_atomic(os.path.join(MMDPLUGIN_SRC, "d3dx9_43.dll"), d3dx9)
                print("MMDPlugin 0.41 に足りなかった d3dx9_43.dll を置きました。", flush=True)
        print("MMDPlugin は入っています（そのまま使います）。")
        return
    moves = plan_mme(mmd) if os.path.isfile(root("MMEffect.dll")) else []
    moving = {os.path.basename(src).lower() for src, _dst, _same in moves}
    if os.path.isfile(root("d3d9.dll")) and "d3d9.dll" not in moving and not is_ours("d3d9.dll"):
        raise Stop("MikuMikuDance.exe の横に、MME でも MMDPlugin でもない d3d9.dll があります。\n"
                   "上書きすると今の動きが変わるので、何も変えずに止めます。何の d3d9.dll かを確かめてください。")
    if os.path.isfile(d3dx9) and not is_ours("d3dx9_43.dll"):
        raise Stop(FOREIGN_D3DX9)
    # ここから先が変える所
    move_mme(moves)
    for name in MMDPLUGIN_FILES:
        copy_atomic(os.path.join(MMDPLUGIN_SRC, name), root(name))
    readme_dir = os.path.join(mmd, "plugin", "MMDPlugin")
    os.makedirs(readme_dir, exist_ok=True)
    copy_atomic(os.path.join(MMDPLUGIN_SRC, MMDPLUGIN_README), os.path.join(readme_dir, MMDPLUGIN_README))
    print("MMDPlugin を置きました（MikuMikuDance.exe の横）。", flush=True)


def main():
    start = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(HERE)
    try:
        mmd = choose_mmd(start)
        print(f"MMD のフォルダ: {mmd}", flush=True)
        check_version(mmd)
        check_not_running(mmd)
        copy_plugin(mmd)
        place_mmdplugin(mmd)
    except Stop as e:
        print()
        print(e)
        return 1
    print()
    print("できました。MMD を起動すると、メニューの「ヘルプ」の右に「AIナカワリ」が出ます。")
    print("最初に「AIナカワリの窓を開く」→「セットアップ」で、AI のモデルを入れてください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
