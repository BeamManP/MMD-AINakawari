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

MikuMikuMoving（MikuMikuMoving64.exe のある所）に展開した時は、MMM 版として入れる（11-12 マスター「同フォルダに MMD があれば MMD 版、MMM があれば MMM 版」）:
    - MMD-AINakawari\\（Python・app など。MMD 版と同じ物）を置く
    - Plugins\\ に MMM-AINakawari.dll・.ini（ボタンとパネル）と MmmBridge.dll・MmmBridgeCore\\MmmBridge.Core.dll（MMM の中の橋渡し）を置く
    - MMD 用の物（MMDPlugin・plugin\\MMD-AINakawari）は置かない。zip をそのまま展開してできた plugin\\MMD-AINakawari は片付ける
同じフォルダに MMD と MMM が両方あれば、どちらに入れるかを聞く。
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

MMM_EXE = "MikuMikuMoving64.exe"
# MikuMikuMoving 1.2.9.2 64bit（2018-06-03 の最終版）。MMM 版を確かめたのはこの exe だけ（11-11）
MMM_SHA256 = "1dde973d548714539e31561a0ab6a2a7074131479a248950e931cac34dd95ddc"
MMM_SRC = os.path.join(HERE, "mmm")   # （zip の中の）MMD-AINakawari\mmm。中身を MMM の Plugins\ に同じ並びで写す
MMM_FILES = ("MMM-AINakawari.dll", "MMM-AINakawari.ini", "MmmBridge.dll", os.path.join("MmmBridgeCore", "MmmBridge.Core.dll"))
HOSTS = {"mmd": (EXE, "MMD（MikuMikuDance）"), "mmm": (MMM_EXE, "MMM（MikuMikuMoving）")}


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


def hosts_in(folder):
    """folder にある相手（"mmd"・"mmm"）の一覧。"""
    return [kind for kind, (exe, _label) in HOSTS.items() if os.path.isfile(os.path.join(folder, exe))]


def ask_host(folder, ask=input):
    """MMD と MMM が同じフォルダにある時に、どちらに入れるかを聞く。"""
    print(f"{folder} には MikuMikuDance.exe と {MMM_EXE} の両方があります。どちらに AIナカワリ を入れますか？")
    while True:
        answer = ask("  1: MMD（MikuMikuDance）   2: MMM（MikuMikuMoving）   番号を入れて Enter > ").strip()
        if answer in ("1", "１"):
            return "mmd"
        if answer in ("2", "２"):
            return "mmm"
        if not answer:
            raise Stop("選ばれなかったので、何もせずに終わります。")
        print("1 か 2 を入れてください。")


def choose_target(start):
    """(入れる先のフォルダ, "mmd" か "mmm")。展開した所に無ければ、フォルダを選んでもらう。"""
    kinds = hosts_in(start)
    if kinds:
        return start, kinds[0] if len(kinds) == 1 else ask_host(start)
    print("この zip は MMD・MMM のフォルダの外に展開されています。")
    print(f"MikuMikuDance.exe か {MMM_EXE} のあるフォルダを選んでください（選んだフォルダに AIナカワリ を写します）。")
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    try:
        while True:
            folder = filedialog.askdirectory(title=f"MikuMikuDance.exe か {MMM_EXE} のあるフォルダを選んでください", mustexist=True)
            if not folder:
                raise Stop("フォルダが選ばれなかったので、何もせずに終わります。")
            folder = os.path.normpath(folder)
            kinds = hosts_in(folder)
            if kinds:
                return folder, kinds[0] if len(kinds) == 1 else ask_host(folder)
            print(f"{folder} に MikuMikuDance.exe も {MMM_EXE} もありません。選び直してください。")
    finally:
        root.destroy()


def check_version(mmd):
    from mmd_mcp.bone_state import VERIFIED_SHA256
    if sha256(os.path.join(mmd, EXE)) != VERIFIED_SHA256:
        raise Stop("AIナカワリ が使えるのは MikuMikuDance 9.32 x64（日本語版）だけです。\n"
                   "この MikuMikuDance.exe は別の版なので、ファイルは何も変えずに終わります。")


def check_mmm_version(mmm):
    if sha256(os.path.join(mmm, MMM_EXE)) != MMM_SHA256:
        raise Stop("AIナカワリ の MMM 版が使えるのは MikuMikuMoving 1.2.9.2（64bit）だけです。\n"
                   f"この {MMM_EXE} は別の版なので、ファイルは何も変えずに終わります。")


def check_not_running(folder, exe_name=EXE, label="MMD"):
    import psutil
    exe = os.path.normcase(os.path.join(folder, exe_name))
    for p in psutil.process_iter(["name", "exe"]):
        if (p.info["name"] or "").lower() != exe_name.lower():
            continue
        # exe の場所が読めない時は、この MMD（MMM）かもしれないので止める
        if not p.info["exe"] or os.path.normcase(p.info["exe"]) == exe:
            raise Stop(f"{label} が開いています。{label} を閉じてから、もう一度ダブルクリックしてください。")


def copy_app(target):
    """zip を MMD（MMM）の外に展開した時だけ、MMD-AINakawari を写す。前に入れた物の設定（app\\work）は残す。"""
    dest = os.path.join(target, NAME)
    if os.path.isdir(dest) and os.path.samefile(dest, HERE):
        return
    print(f"写しています: {dest}（1〜2 分かかります）", flush=True)
    shutil.copytree(HERE, dest, dirs_exist_ok=True,
                    ignore=lambda folder, names: [n for n in names if n in ("work", "__pycache__")])


def copy_plugin(mmd):
    """zip を MMD の外に展開した時だけ、MMD-AINakawari と plugin\\MMD-AINakawari を MMD へ写す。"""
    dest = os.path.join(mmd, NAME)
    if os.path.isdir(dest) and os.path.samefile(dest, HERE):
        return
    if not os.path.isfile(os.path.join(PLUGIN_SRC, f"{NAME}.dll")):
        raise Stop(f"{PLUGIN_SRC} に {NAME}.dll がありません。zip の中身を全部展開し直してください。")
    copy_app(mmd)
    shutil.copytree(PLUGIN_SRC, os.path.join(mmd, "plugin", NAME), dirs_exist_ok=True)


def place_mmm(mmm):
    """MMM の Plugins\\ に、ボタン・パネルと橋渡しの DLL を置く。足りない物があれば何も置かずに止める。"""
    missing = [name for name in MMM_FILES if not os.path.isfile(os.path.join(MMM_SRC, name))]
    if missing:
        raise Stop(f"{MMM_SRC} に {', '.join(missing)} がありません。zip の中身を全部展開し直してください。")
    plugins = os.path.join(mmm, "Plugins")
    for name in MMM_FILES:
        dst = os.path.join(plugins, name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        copy_atomic(os.path.join(MMM_SRC, name), dst)
    print("MMM の Plugins に AIナカワリ のボタン・パネルと、MMM とやり取りする橋渡し（MmmBridge）を置きました。", flush=True)


def tidy_mmd_files(mmm):
    """zip を MMM のフォルダにそのまま展開した時にできる plugin\\MMD-AINakawari（MMD 用）を片付ける。
    展開した物そのもの（PLUGIN_SRC）の時だけ消す。ほかの物は触らない。"""
    leftover = os.path.join(mmm, "plugin", NAME)
    if not (os.path.isdir(leftover) and os.path.isdir(PLUGIN_SRC) and os.path.samefile(leftover, PLUGIN_SRC)):
        return
    if any(n.lower() not in (f"{NAME}.dll".lower(), f"{NAME}.ini".lower()) for n in os.listdir(leftover)):
        return
    shutil.rmtree(leftover)
    parent = os.path.dirname(leftover)
    if not os.listdir(parent):
        os.rmdir(parent)
    print("MMD 用のファイル（plugin\\MMD-AINakawari）は MMM では使わないので片付けました。", flush=True)


FOREIGN_D3DX9 = ("MikuMikuDance.exe の横に、MMDPlugin の物ではない d3dx9_43.dll があります。\n"
                 "AIナカワリ を入れると、この d3dx9_43.dll を MMDPlugin の物と入れ替えることになるので、ファイルは何も変えずに止めます。\n"
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
                       "どちらを使えばいいか分からないので、ファイルは何も変えずに止めます。いらない方を別のフォルダへ移してから、もう一度ダブルクリックしてください。")
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
                   "上書きすると、今それを使っているツールが動かなくなるかもしれないので、ファイルは何も変えずに止めます。この d3d9.dll の配布元を確かめてください。")
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
        folder, kind = choose_target(start)
        if kind == "mmm":
            print(f"MMM のフォルダ: {folder}", flush=True)
            check_mmm_version(folder)
            check_not_running(folder, MMM_EXE, "MMM")
            copy_app(folder)
            place_mmm(folder)
            tidy_mmd_files(folder)
        else:
            print(f"MMD のフォルダ: {folder}", flush=True)
            check_version(folder)
            check_not_running(folder)
            copy_plugin(folder)
            place_mmdplugin(folder)
    except Stop as e:
        print()
        print(e)
        return 1
    print()
    if kind == "mmm":
        print("できました。MMM を起動すると、ツールバーに「AIナカワリ」のボタンが出ます"
              "（左の欄の「プラグイン」のタブにも AIナカワリ のパネルが出ます）。")
        print("最初にボタンで窓を開いて、「セットアップ」で AI のモデルを入れてください。")
    else:
        print("できました。MMD を起動すると、メニューの「ヘルプ」の右に「AIナカワリ」が出ます。")
        print("最初に「AIナカワリの窓を開く」→「セットアップ」で、AI のモデルを入れてください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
