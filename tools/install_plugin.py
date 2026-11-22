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

出す文は Windows の表示言語で、日本語・中国語（簡体字）・英語のどれか（11-22 マスター「日本語モード時は日本語、英語モード時は英語、
中国モード時は中国語」。導入は MMD を開く前なので、MMD のモードではなく Windows の言葉で選ぶ）。本体の訳の表（mmd_ainakawari.i18n）は
展開した直後には使えないので、文は T(日本語, 英語, 中国語) でここに並べる。
"""
import ctypes
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


def windows_language():
    """Windows の表示言語: "ja"・"zh"・"en"（日本語・中国語でなければ英語）。"""
    try:
        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
    except (AttributeError, OSError):
        return "ja"
    return {0x11: "ja", 0x04: "zh"}.get(primary, "en")


LANG = windows_language()


def T(ja, en, zh):
    """今の言葉（LANG）の文。"""
    return {"ja": ja, "en": en, "zh": zh}[LANG]


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
    print(T(f"{folder} には MikuMikuDance.exe と {MMM_EXE} の両方があります。どちらに AIナカワリ を入れますか？",
            f"{folder} has both MikuMikuDance.exe and {MMM_EXE}. Which one should AI Nakawari be installed for?",
            f"{folder} 中同时有 MikuMikuDance.exe 和 {MMM_EXE}。要把 AI Nakawari 安装到哪一个？"))
    while True:
        answer = ask(T("  1: MMD（MikuMikuDance）   2: MMM（MikuMikuMoving）   番号を入れて Enter > ",
                       "  1: MMD (MikuMikuDance)   2: MMM (MikuMikuMoving)   Type the number and press Enter > ",
                       "  1: MMD（MikuMikuDance）   2: MMM（MikuMikuMoving）   输入编号后按 Enter > ")).strip()
        if answer in ("1", "１"):
            return "mmd"
        if answer in ("2", "２"):
            return "mmm"
        if not answer:
            raise Stop(T("選ばれなかったので、何もせずに終わります。", "Nothing was chosen, so nothing was changed.",
                         "没有选择，因此不做任何更改并退出。"))
        print(T("1 か 2 を入れてください。", "Type 1 or 2.", "请输入 1 或 2。"))


def choose_target(start):
    """(入れる先のフォルダ, "mmd" か "mmm")。展開した所に無ければ、フォルダを選んでもらう。"""
    kinds = hosts_in(start)
    if kinds:
        return start, kinds[0] if len(kinds) == 1 else ask_host(start)
    print(T("この zip は MMD・MMM のフォルダの外に展開されています。", "This zip was extracted outside the MMD / MMM folder.",
            "此压缩包被解压到了 MMD、MMM 的文件夹之外。"))
    print(T(f"MikuMikuDance.exe か {MMM_EXE} のあるフォルダを選んでください（選んだフォルダに AIナカワリ を写します）。",
            f"Choose the folder that has MikuMikuDance.exe or {MMM_EXE} (AI Nakawari will be copied there).",
            f"请选择 MikuMikuDance.exe 或 {MMM_EXE} 所在的文件夹（会把 AI Nakawari 复制到所选文件夹）。"))
    import tkinter as tk
    from tkinter import filedialog
    root = tk.Tk()
    root.withdraw()
    try:
        while True:
            folder = filedialog.askdirectory(title=T(f"MikuMikuDance.exe か {MMM_EXE} のあるフォルダを選んでください",
                                                     f"Choose the folder that has MikuMikuDance.exe or {MMM_EXE}",
                                                     f"请选择 MikuMikuDance.exe 或 {MMM_EXE} 所在的文件夹"), mustexist=True)
            if not folder:
                raise Stop(T("フォルダが選ばれなかったので、何もせずに終わります。", "No folder was chosen, so nothing was changed.",
                             "没有选择文件夹，因此不做任何更改并退出。"))
            folder = os.path.normpath(folder)
            kinds = hosts_in(folder)
            if kinds:
                return folder, kinds[0] if len(kinds) == 1 else ask_host(folder)
            print(T(f"{folder} に MikuMikuDance.exe も {MMM_EXE} もありません。選び直してください。",
                    f"{folder} has neither MikuMikuDance.exe nor {MMM_EXE}. Choose again.",
                    f"{folder} 中既没有 MikuMikuDance.exe 也没有 {MMM_EXE}。请重新选择。"))
    finally:
        root.destroy()


def check_version(mmd):
    # 確かめた exe の一覧は mmd-mcp の bone_state.PROFILES（日本語版 9.32 x64 と、中国語版 MMD932・11-18）
    from mmd_mcp.bone_state import PROFILES
    if sha256(os.path.join(mmd, EXE)) not in PROFILES:
        raise Stop(T("AIナカワリ が使えるのは MikuMikuDance 9.32 x64（日本語版・中国語版 MMD932）だけです。\n"
                     "この MikuMikuDance.exe は別の版なので、ファイルは何も変えずに終わります。",
                     "AI Nakawari works only with MikuMikuDance 9.32 x64 (the Japanese version, or the Chinese version MMD932).\n"
                     "This MikuMikuDance.exe is a different version, so nothing was changed.",
                     "AI Nakawari 只能用于 MikuMikuDance 9.32 x64（日文版、中文版 MMD932）。\n"
                     "这个 MikuMikuDance.exe 是其他版本，因此没有更改任何文件。"))


def check_mmm_version(mmm):
    if sha256(os.path.join(mmm, MMM_EXE)) != MMM_SHA256:
        raise Stop(T("AIナカワリ の MMM 版が使えるのは MikuMikuMoving 1.2.9.2（64bit）だけです。\n"
                     f"この {MMM_EXE} は別の版なので、ファイルは何も変えずに終わります。",
                     "The MMM version of AI Nakawari works only with MikuMikuMoving 1.2.9.2 (64-bit).\n"
                     f"This {MMM_EXE} is a different version, so nothing was changed.",
                     "AI Nakawari 的 MMM 版只能用于 MikuMikuMoving 1.2.9.2（64 位）。\n"
                     f"这个 {MMM_EXE} 是其他版本，因此没有更改任何文件。"))


def check_not_running(folder, exe_name=EXE, label="MMD"):
    import psutil
    exe = os.path.normcase(os.path.join(folder, exe_name))
    for p in psutil.process_iter(["name", "exe"]):
        if (p.info["name"] or "").lower() != exe_name.lower():
            continue
        # exe の場所が読めない時は、この MMD（MMM）かもしれないので止める
        if not p.info["exe"] or os.path.normcase(p.info["exe"]) == exe:
            raise Stop(T(f"{label} が開いています。{label} を閉じてから、もう一度ダブルクリックしてください。",
                         f"{label} is open. Close {label}, then double-click it again.",
                         f"{label} 正在运行。请关闭 {label} 后再双击一次。"))


def copy_app(target):
    """zip を MMD（MMM）の外に展開した時だけ、MMD-AINakawari を写す。前に入れた物の設定（app\\work）は残す。"""
    dest = os.path.join(target, NAME)
    if os.path.isdir(dest) and os.path.samefile(dest, HERE):
        return
    print(T(f"写しています: {dest}（1〜2 分かかります）", f"Copying: {dest} (takes 1-2 minutes)", f"正在复制：{dest}（需要 1～2 分钟）"),
          flush=True)
    shutil.copytree(HERE, dest, dirs_exist_ok=True,
                    ignore=lambda folder, names: [n for n in names if n in ("work", "__pycache__")])


def copy_plugin(mmd):
    """zip を MMD の外に展開した時だけ、MMD-AINakawari と plugin\\MMD-AINakawari を MMD へ写す。"""
    dest = os.path.join(mmd, NAME)
    if os.path.isdir(dest) and os.path.samefile(dest, HERE):
        return
    if not os.path.isfile(os.path.join(PLUGIN_SRC, f"{NAME}.dll")):
        raise Stop(T(f"{PLUGIN_SRC} に {NAME}.dll がありません。zip の中身を全部展開し直してください。",
                     f"{NAME}.dll is missing from {PLUGIN_SRC}. Extract the whole zip again.",
                     f"{PLUGIN_SRC} 中没有 {NAME}.dll。请重新解压压缩包的全部内容。"))
    copy_app(mmd)
    shutil.copytree(PLUGIN_SRC, os.path.join(mmd, "plugin", NAME), dirs_exist_ok=True)


def place_mmm(mmm):
    """MMM の Plugins\\ に、ボタン・パネルと橋渡しの DLL を置く。足りない物があれば何も置かずに止める。"""
    missing = [name for name in MMM_FILES if not os.path.isfile(os.path.join(MMM_SRC, name))]
    if missing:
        raise Stop(T(f"{MMM_SRC} に {', '.join(missing)} がありません。zip の中身を全部展開し直してください。",
                     f"{', '.join(missing)} is missing from {MMM_SRC}. Extract the whole zip again.",
                     f"{MMM_SRC} 中没有 {', '.join(missing)}。请重新解压压缩包的全部内容。"))
    plugins = os.path.join(mmm, "Plugins")
    for name in MMM_FILES:
        dst = os.path.join(plugins, name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        copy_atomic(os.path.join(MMM_SRC, name), dst)
    print(T("MMM の Plugins に AIナカワリ のボタン・パネルと、MMM とやり取りする橋渡し（MmmBridge）を置きました。",
            "Placed the AI Nakawari button and panel, and the bridge to MMM (MmmBridge), in MMM's Plugins folder.",
            "已在 MMM 的 Plugins 中放置 AI Nakawari 的按钮、面板，以及与 MMM 通信的桥接程序（MmmBridge）。"), flush=True)


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
    print(T("MMD 用のファイル（plugin\\MMD-AINakawari）は MMM では使わないので片付けました。",
            "Removed the MMD files (plugin\\MMD-AINakawari), which MMM does not use.",
            "MMM 不使用 MMD 用的文件（plugin\\MMD-AINakawari），已将其清理。"), flush=True)


FOREIGN_D3DX9 = T("MikuMikuDance.exe の横に、MMDPlugin の物ではない d3dx9_43.dll があります。\n"
                  "AIナカワリ を入れると、この d3dx9_43.dll を MMDPlugin の物と入れ替えることになるので、ファイルは何も変えずに止めます。\n"
                  "今の d3dx9_43.dll を別のフォルダへ移してから、もう一度ダブルクリックしてください。",
                  "There is a d3dx9_43.dll next to MikuMikuDance.exe that is not MMDPlugin's.\n"
                  "Installing AI Nakawari would replace it with MMDPlugin's, so nothing was changed.\n"
                  "Move the current d3dx9_43.dll to another folder, then double-click it again.",
                  "MikuMikuDance.exe 旁边有一个不是 MMDPlugin 的 d3dx9_43.dll。\n"
                  "安装 AI Nakawari 会把它替换成 MMDPlugin 的文件，因此没有更改任何文件。\n"
                  "请把现在的 d3dx9_43.dll 移到其他文件夹后，再双击一次。")
# Microsoft の DirectX（June 2010）の x64 の d3dx9_43.dll 9.29.952.3111。中国語版 MMD932 の配布物が exe の横に同梱している
# （11-18。署名は Microsoft で、この PC の System32 の物と同じ中身）。MMDPlugin の中継は System32 の物を呼ぶので、
# System32 に同じ物があれば、exe の横の物は控えに移して中継と入れ替えてよい
MS_D3DX9_SHA256 = "84b900dbd7fa978d6e0caee26fc54f2f61d92c9c75d10b35f00e3e82cd1d67b4"
MS_D3DX9_KEEP = os.path.join("plugin", "MMDPlugin", "d3dx9_43_microsoft.dll")   # 控えの置き場（MMD のフォルダから）
NO_SYSTEM_D3DX9 = T("MikuMikuDance.exe の横に Microsoft の d3dx9_43.dll がありますが、Windows（System32）には入っていません。\n"
                    "MMDPlugin は Windows の d3dx9_43.dll を呼ぶので、このまま入れると MMD が起動しなくなります。ファイルは何も変えずに止めます。\n"
                    "Microsoft の「DirectX End-User Runtime」を入れてから、もう一度ダブルクリックしてください。",
                    "There is Microsoft's d3dx9_43.dll next to MikuMikuDance.exe, but Windows (System32) does not have it.\n"
                    "MMDPlugin calls the one in Windows, so installing now would stop MMD from starting. Nothing was changed.\n"
                    "Install Microsoft's DirectX End-User Runtime, then double-click it again.",
                    "MikuMikuDance.exe 旁边有 Microsoft 的 d3dx9_43.dll，但 Windows（System32）中没有。\n"
                    "MMDPlugin 会调用 Windows 中的 d3dx9_43.dll，直接安装会导致 MMD 无法启动。因此没有更改任何文件。\n"
                    "请先安装 Microsoft 的“DirectX End-User Runtime”，然后再双击一次。")


def microsoft_d3dx9(path):
    """path が Microsoft の d3dx9_43.dll（MS_D3DX9_SHA256）なら、System32 に同じ物があるか（True/False）。違う物なら None。"""
    if sha256(path) != MS_D3DX9_SHA256:
        return None
    system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "d3dx9_43.dll")
    return os.path.isfile(system) and sha256(system) == MS_D3DX9_SHA256


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
            raise Stop(T(f"MME を plugin\\mme に移そうとしましたが、{dst} に中身の違う {name} があります。\n"
                         "どちらを使えばいいか分からないので、ファイルは何も変えずに止めます。いらない方を別のフォルダへ移してから、もう一度ダブルクリックしてください。",
                         f"Tried to move MME to plugin\\mme, but {dst} has a different {name}.\n"
                         "It is unclear which one to use, so nothing was changed. Move the one you do not need to another folder, then double-click it again.",
                         f"尝试把 MME 移到 plugin\\mme，但 {dst} 中有内容不同的 {name}。\n"
                         "无法判断该用哪一个，因此没有更改任何文件。请把不需要的那个移到其他文件夹后，再双击一次。"))
        moves.append((src, dst, same))
    return moves


def move_mme(moves):
    for src, dst, same in moves:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if same:
            os.remove(src)   # 移す先に同じ中身がある（前に途中まで移した時など）
        else:
            os.replace(src, dst)
        print(T(f"MME を移しました: {os.path.basename(src)} → plugin\\mme\\", f"Moved MME: {os.path.basename(src)} → plugin\\mme\\",
                f"已移动 MME：{os.path.basename(src)} → plugin\\mme\\"), flush=True)


def place_mmdplugin(mmd):
    """確かめることを全部確かめてから、MME を移して MMDPlugin を置く（止まる時は何も変えていない）。"""
    root = lambda name: os.path.join(mmd, name)
    is_ours = lambda name: sha256(root(name)) == MMDPLUGIN_FILES[name]
    for name, digest in MMDPLUGIN_FILES.items():
        if sha256(os.path.join(MMDPLUGIN_SRC, name)) != digest:
            raise Stop(T(f"同梱の {name} が壊れています。zip を落とし直して、展開し直してください。",
                         f"The bundled {name} is damaged. Download the zip again and extract it again.",
                         f"附带的 {name} 已损坏。请重新下载压缩包并重新解压。"))
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
                print(T("MMDPlugin 0.41 に足りなかった d3dx9_43.dll を置きました。", "Placed d3dx9_43.dll, which MMDPlugin 0.41 was missing.",
                        "已放置 MMDPlugin 0.41 缺少的 d3dx9_43.dll。"), flush=True)
        print(T("MMDPlugin は入っています（そのまま使います）。", "MMDPlugin is already installed (using it as is).",
                "MMDPlugin 已安装（直接使用）。"))
        return
    moves = plan_mme(mmd) if os.path.isfile(root("MMEffect.dll")) else []
    moving = {os.path.basename(src).lower() for src, _dst, _same in moves}
    if os.path.isfile(root("d3d9.dll")) and "d3d9.dll" not in moving and not is_ours("d3d9.dll"):
        raise Stop(T("MikuMikuDance.exe の横に、MME でも MMDPlugin でもない d3d9.dll があります。\n"
                     "上書きすると、今それを使っているツールが動かなくなるかもしれないので、ファイルは何も変えずに止めます。この d3d9.dll の配布元を確かめてください。",
                     "There is a d3d9.dll next to MikuMikuDance.exe that is neither MME's nor MMDPlugin's.\n"
                     "Overwriting it could break the tool that uses it, so nothing was changed. Check where this d3d9.dll came from.",
                     "MikuMikuDance.exe 旁边有一个既不是 MME 也不是 MMDPlugin 的 d3d9.dll。\n"
                     "覆盖它可能导致正在使用它的工具无法运行，因此没有更改任何文件。请确认这个 d3d9.dll 的来源。"))
    keep_d3dx9 = False
    if os.path.isfile(d3dx9) and not is_ours("d3dx9_43.dll"):
        system = microsoft_d3dx9(d3dx9)
        if system is None:
            raise Stop(FOREIGN_D3DX9)
        if not system:
            raise Stop(NO_SYSTEM_D3DX9)
        if os.path.exists(root(MS_D3DX9_KEEP)) and sha256(root(MS_D3DX9_KEEP)) != MS_D3DX9_SHA256:
            raise Stop(T(f"{root(MS_D3DX9_KEEP)} に、Microsoft の物ではない d3dx9_43_microsoft.dll があります。ファイルは何も変えずに止めます。",
                         f"{root(MS_D3DX9_KEEP)} has a d3dx9_43_microsoft.dll that is not Microsoft's. Nothing was changed.",
                         f"{root(MS_D3DX9_KEEP)} 中有一个不是 Microsoft 的 d3dx9_43_microsoft.dll。因此没有更改任何文件。"))
        keep_d3dx9 = True
    # ここから先が変える所
    move_mme(moves)
    if keep_d3dx9:
        os.makedirs(os.path.dirname(root(MS_D3DX9_KEEP)), exist_ok=True)
        os.replace(d3dx9, root(MS_D3DX9_KEEP))
        print(T(f"Microsoft の d3dx9_43.dll を控えに移しました: {MS_D3DX9_KEEP}（Windows に同じ物があるので、MMD はそちらを使います）",
                f"Moved Microsoft's d3dx9_43.dll to a backup: {MS_D3DX9_KEEP} (Windows has the same file, so MMD uses that one)",
                f"已把 Microsoft 的 d3dx9_43.dll 移作备份：{MS_D3DX9_KEEP}（Windows 中有相同的文件，MMD 会使用那个）"), flush=True)
    for name in MMDPLUGIN_FILES:
        copy_atomic(os.path.join(MMDPLUGIN_SRC, name), root(name))
    readme_dir = os.path.join(mmd, "plugin", "MMDPlugin")
    os.makedirs(readme_dir, exist_ok=True)
    copy_atomic(os.path.join(MMDPLUGIN_SRC, MMDPLUGIN_README), os.path.join(readme_dir, MMDPLUGIN_README))
    print(T("MMDPlugin を置きました（MikuMikuDance.exe の横）。", "Placed MMDPlugin (next to MikuMikuDance.exe).",
            "已放置 MMDPlugin（MikuMikuDance.exe 旁边）。"), flush=True)


def main():
    start = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.dirname(HERE)
    try:
        folder, kind = choose_target(start)
        if kind == "mmm":
            print(T(f"MMM のフォルダ: {folder}", f"MMM folder: {folder}", f"MMM 文件夹：{folder}"), flush=True)
            check_mmm_version(folder)
            check_not_running(folder, MMM_EXE, "MMM")
            copy_app(folder)
            place_mmm(folder)
            tidy_mmd_files(folder)
        else:
            print(T(f"MMD のフォルダ: {folder}", f"MMD folder: {folder}", f"MMD 文件夹：{folder}"), flush=True)
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
        print(T("できました。MMM を起動すると、ツールバーに「AIナカワリ」のボタンが出ます"
                "（左の欄の「プラグイン」のタブにも AIナカワリ のパネルが出ます）。",
                "Done. When you start MMM, an AI Nakawari button appears on the toolbar "
                "(the AI Nakawari panel also appears on the Plugins tab on the left).",
                "完成。启动 MMM 后，工具栏上会出现“AIナカワリ”按钮（左侧“插件”标签页中也会出现 AI Nakawari 的面板）。"))
        print(T("最初にボタンで窓を開いて、「セットアップ」で AI のモデルを入れてください。",
                "First open the window with the button, and install the AI models with Setup.",
                "请先用按钮打开窗口，再在“安装”中安装 AI 模型。"))
    else:
        print(T("できました。MMD を起動すると、メニューの「ヘルプ」の右に「AIナカワリ」が出ます。",
                "Done. When you start MMD, AI Nakawari appears to the right of Help in the menu bar.",
                "完成。启动 MMD 后，菜单栏“帮助”的右边会出现“AI Nakawari”。"))
        print(T("最初に「AIナカワリの窓を開く」→「セットアップ」で、AI のモデルを入れてください。",
                "First choose Open AI Nakawari window, then install the AI models with Setup.",
                "请先点击“打开 AI Nakawari 窗口”，再在“安装”中安装 AI 模型。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
