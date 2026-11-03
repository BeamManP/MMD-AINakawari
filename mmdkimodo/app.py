"""MMDKimodo の窓。MMD のメニュー「MMDKimodo」→「Kimodo の窓を開く」から開く（MMDPlugin のプラグイン mmd_plugin/kimodo_plugin.cpp）。

使い方: MMD でモデルを選び、いつもどおりポーズを付けてキーを打つ → ここでプロンプトを入れて「生成」。
生成は裏で回すので窓は固まらない。「元に戻す」で生成前のモーションに戻せる。
窓は MMD ごとに 1 つで、その MMD の持ち物（MMD の上に出て、MMD と一緒に隠れる）。× は隠すだけで、MMD のメニューからまた開ける。
プロセスは 1 つだけ。プラグインは、動いていれば見えない窓（MMDKimodo.Hub）に「この MMD の窓を開いて」と知らせ、
動いていなければ --open <MMD の窓> 付きで起動する。全部の MMD が閉じたら終わる。
"""
import argparse
import ctypes
import json
import os
import queue
import socket
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import win32api
import win32con
import win32event
import win32gui
import winerror

from mmd_mcp.windows import list_windows

from . import runner
from .message_window import MessageWindow, register_message
from .mmd_link import MMDLink

APP_MUTEX = "Local\\MMDKimodo.App.v1"
HUB_CLASS = "MMDKimodo.Hub"           # プラグインと 2 回目の起動が探す目印（kimodo_plugin.cpp と同じ）
OPEN_MESSAGE = "MMDKimodo.Open.v1"    # wparam = 開きたい MMD の窓
_set_window_long = ctypes.windll.user32.SetWindowLongPtrW
_set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
_set_window_long.restype = ctypes.c_void_p
SETTINGS_PATH = os.path.join(runner.WORK_DIR, "settings.json")
SERVER_CMD = r"F:\kimodo\start_textencoder.cmd"
DEFAULTS = {
    "pmx": r"E:\oldC_0427\Users\beamman\Desktop\MikuMikuDance_v932x64\UserFile\Model\Tda式初音ミクV4X_Ver1.00\Tda式初音ミクV4X_Ver1.00.pmx",
    "prompt": "A person moves naturally between poses.",
    "steps": 100, "seed": -1, "post_processing": True, "range_start": "", "range_end": "",
    "cfg_text": 2.0, "cfg_key": 2.0, "length": "", "use_keys": True, "use_center": False,
}


def server_up(port=9550):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.05):
            return True
    except OSError:
        return False


def front_mmd():
    """一番手前の MMD の窓。無ければ None。"""
    mmds = {w.hwnd for w in list_windows()}
    order = []
    win32gui.EnumWindows(lambda hwnd, _: order.append(hwnd), None)  # 手前から順に並ぶ
    return next((h for h in order if h in mmds), None)


class Hub:
    """MMD ごとの窓（App）をまとめる。見えない tk の親の窓と、プラグインからの知らせを受ける窓を持つ。"""

    def __init__(self, root):
        self.root = root
        self.apps = {}   # MMD の窓 → App
        self.alive = True
        self.requests = queue.Queue()
        self.listener = MessageWindow(HUB_CLASS, {OPEN_MESSAGE: lambda w, _l: self.requests.put(int(w))})
        self.listener.start()
        self._poll()

    def open(self, hwnd):
        """その MMD の窓を出す（まだ無ければ作る）。"""
        mmd = next((w for w in list_windows() if w.hwnd == hwnd), None)
        if mmd is None:
            messagebox.showerror("MMDKimodo", "開こうとした MMD が見つかりません（閉じられた？）")
        else:
            if hwnd not in self.apps:
                self.apps[hwnd] = App(tk.Toplevel(self.root), self, mmd)
            self.apps[hwnd].show()
        if not self.apps:
            self._finish()

    def forget(self, app):
        self.apps.pop(app.mmd.hwnd, None)
        if not self.apps:
            self._finish()

    def _finish(self):
        """相手の MMD が 1 つも無くなったら終わる。"""
        self.alive = False
        self.root.destroy()

    def close(self):
        self.listener.stop()

    def _poll(self):
        while not self.requests.empty():
            self.open(self.requests.get())
        if self.alive:
            self.root.after(100, self._poll)


class App:
    """MMD 1 つ分の窓。root はその MMD 用の Toplevel。"""

    def __init__(self, root, hub, mmd):
        self.root = root
        self.hub = hub
        self.mmd = mmd
        self.link = MMDLink(mmd.hwnd)
        root.withdraw()  # 出すのは Hub が決める
        root.title("MMDKimodo")
        root.geometry("520x690")
        root.attributes("-topmost", False)
        self.cfg = dict(DEFAULTS)
        try:
            self.cfg.update(json.load(open(SETTINGS_PATH, encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self.q = queue.Queue()
        self.busy = False
        self.last_run = runner.load_last_run(self.link)   # この MMD での前回の生成（作り直しと「元に戻す」に使う）。窓を開き直しても残る
        self.last_backup = self.last_run["backup"] if self.last_run else None
        self._build()
        root.protocol("WM_DELETE_WINDOW", root.withdraw)
        self._tick()

    def show(self):
        """窓を出す。持ち主（MMD）は出すたびに付け直す（隠したまま作った窓は、出すまで枠の窓が決まらないため）。"""
        self.root.deiconify()
        self.root.update_idletasks()
        frame = int(self.root.wm_frame(), 16)
        _set_window_long(frame, -8, self.mmd.hwnd)  # GWLP_HWNDPARENT（トップレベルの窓では持ち主）
        self.root.lift()
        self.root.focus_force()

    def close(self):
        """この MMD の窓を片付ける。"""
        self.root.destroy()
        self.hub.forget(self)

    # ---------------- 画面 ----------------

    def _build(self):
        pad = {"padx": 8, "pady": 3}
        f = ttk.Frame(self.root)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="モデル（PMX）").grid(row=0, column=0, sticky="w", **pad)
        self.pmx = tk.StringVar(value=self.cfg["pmx"])
        ttk.Entry(f, textvariable=self.pmx).grid(row=1, column=0, columnspan=3, sticky="we", **pad)
        ttk.Button(f, text="選ぶ…", command=self._pick_pmx).grid(row=1, column=3, **pad)

        ttk.Label(f, text="プロンプト（英語・キーの間をどう動くか。「45: …」の行で区間ごとに分けられる）").grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        self.prompt = tk.Text(f, height=7, wrap="word")
        self.prompt.insert("1.0", self.cfg["prompt"])
        self.prompt.grid(row=3, column=0, columnspan=4, sticky="we", **pad)

        ttk.Label(f, text="手数（少ないほど速い）").grid(row=4, column=0, sticky="w", **pad)
        self.steps = tk.IntVar(value=self.cfg["steps"])
        ttk.Spinbox(f, from_=10, to=100, increment=10, textvariable=self.steps, width=6).grid(row=4, column=1, sticky="w", **pad)
        ttk.Label(f, text="seed（-1 で毎回変える）").grid(row=5, column=0, sticky="w", **pad)
        self.seed = tk.IntVar(value=self.cfg["seed"])
        ttk.Entry(f, textvariable=self.seed, width=8).grid(row=5, column=1, sticky="w", **pad)
        # Kimodo の CFG の重み。テキストを上げるとプロンプトの動きが強く出る（回転なら 8・1 で振り向くほど）
        ttk.Label(f, text="テキストの効き").grid(row=4, column=2, sticky="e", **pad)
        self.cfg_text = tk.DoubleVar(value=self.cfg["cfg_text"])
        ttk.Spinbox(f, from_=0.5, to=10, increment=0.5, textvariable=self.cfg_text, width=5).grid(row=4, column=3, sticky="w", **pad)
        ttk.Label(f, text="キーの効き").grid(row=5, column=2, sticky="e", **pad)
        self.cfg_key = tk.DoubleVar(value=self.cfg["cfg_key"])
        ttk.Spinbox(f, from_=0.5, to=10, increment=0.5, textvariable=self.cfg_key, width=5).grid(row=5, column=3, sticky="w", **pad)
        self.post = tk.BooleanVar(value=self.cfg["post_processing"])
        ttk.Checkbutton(f, text="キーに合わせる後処理", variable=self.post).grid(row=6, column=0, columnspan=2, sticky="w", **pad)
        # 外すと完全新規（体のキーのポーズは使わず、最初のキーの場所と向きだけ使う）。全ての親のキーはどちらでも使う
        self.use_keys = tk.BooleanVar(value=self.cfg["use_keys"])
        ttk.Checkbutton(f, text="打ったキーのポーズを守る", variable=self.use_keys).grid(row=6, column=2, columnspan=2, sticky="w", **pad)
        # センターの上下などを毎フレームの腰の目印にする（リズムを残して動きを作る。完全新規と組み合わせる想定）
        self.use_center = tk.BooleanVar(value=self.cfg["use_center"])
        ttk.Checkbutton(f, text="センターの動きを使う", variable=self.use_center).grid(row=7, column=2, columnspan=2, sticky="w", **pad)

        ttk.Label(f, text="使うキーの範囲（空なら全部・最大 300 フレーム）").grid(row=7, column=0, columnspan=2, sticky="w", **pad)
        rf = ttk.Frame(f)
        rf.grid(row=8, column=0, columnspan=4, sticky="w", **pad)
        self.r0 = tk.StringVar(value=str(self.cfg["range_start"]))
        self.r1 = tk.StringVar(value=str(self.cfg["range_end"]))
        ttk.Entry(rf, textvariable=self.r0, width=7).pack(side="left")
        ttk.Label(rf, text=" F 〜 ").pack(side="left")
        ttk.Entry(rf, textvariable=self.r1, width=7).pack(side="left")
        ttk.Label(rf, text=" F　　長さ ").pack(side="left")
        self.length = tk.StringVar(value=str(self.cfg["length"]))
        ttk.Entry(rf, textvariable=self.length, width=6).pack(side="left")
        ttk.Label(rf, text=" F（空なら最後のキーまで）").pack(side="left")

        sf = ttk.Frame(f)
        sf.grid(row=9, column=0, columnspan=4, sticky="we", **pad)
        self.server_label = ttk.Label(sf, text="")
        self.server_label.pack(side="left")
        self.server_btn = ttk.Button(sf, text="サーバーを起動", command=self._start_server)
        self.server_btn.pack(side="right")

        bf = ttk.Frame(f)
        bf.grid(row=10, column=0, columnspan=4, sticky="we", **pad)
        self.gen_btn = ttk.Button(bf, text="生成（Kimodo で間を埋める）", command=self._generate)
        self.gen_btn.pack(side="left", fill="x", expand=True, ipady=6)
        self.undo_btn = ttk.Button(bf, text="元に戻す", command=self._undo, state="disabled")
        self.undo_btn.pack(side="left", padx=(6, 0), ipady=6)

        self.status = tk.StringVar(value="MMD でモデルを選び、キーを打ってから「生成」を押してください")
        ttk.Label(f, textvariable=self.status, foreground="#335", wraplength=490).grid(row=11, column=0, columnspan=4, sticky="w", **pad)
        self.log = tk.Text(f, height=12, wrap="word", state="disabled", background="#f6f6f6")
        self.log.grid(row=12, column=0, columnspan=4, sticky="nsew", **pad)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(12, weight=1)

    def _pick_pmx(self):
        p = filedialog.askopenfilename(parent=self.root, filetypes=[("PMX", "*.pmx"), ("すべて", "*.*")])
        if p:
            self.pmx.set(p)

    def _write_log(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _tick(self):
        if not win32gui.IsWindow(self.mmd.hwnd):  # MMD が閉じたら、その MMD の分は一緒に終わる
            self.close()
            return
        scene = win32gui.GetWindowText(self.mmd.hwnd).partition("[")[2].rstrip("]")
        title = f"MMDKimodo - {os.path.basename(scene)}" if scene else "MMDKimodo"
        if self.root.title() != title:
            self.root.title(title)
        while not self.q.empty():
            kind, payload = self.q.get()
            if kind == "log":
                self._write_log(payload)
            elif kind == "done":
                self.busy = False
                ok, msg = payload
                self.status.set(msg)
                if not ok:
                    messagebox.showerror("MMDKimodo", msg, parent=self.root)
        up = server_up()
        self.server_label.configure(text="● テキスト読み取りサーバー起動中" if up else "○ サーバー停止中（無いと毎回 Llama を読み込むので遅い）")
        self.server_btn.configure(state="disabled" if up else "normal")
        self.gen_btn.configure(state="disabled" if self.busy else "normal")
        self.undo_btn.configure(state="normal" if (self.last_backup and not self.busy) else "disabled")
        self.root.after(500, self._tick)

    # ---------------- 操作 ----------------

    def _settings(self):
        def opt_int(s):
            s = s.strip()
            return int(s) if s else None
        s = runner.Settings(pmx=self.pmx.get().strip(), prompt=self.prompt.get("1.0", "end").strip(),
                            steps=int(self.steps.get()), seed=int(self.seed.get()), post_processing=bool(self.post.get()),
                            range_start=opt_int(self.r0.get()), range_end=opt_int(self.r1.get()),
                            cfg_text=float(self.cfg_text.get()), cfg_key=float(self.cfg_key.get()),
                            length=opt_int(self.length.get()), use_keys=bool(self.use_keys.get()),
                            use_center=bool(self.use_center.get()))
        if (s.range_start is None) != (s.range_end is None):
            raise ValueError("範囲は始めと終わりの両方を入れてください（全部使うなら両方空）")
        self.cfg.update(pmx=s.pmx, prompt=s.prompt, steps=s.steps, seed=s.seed, post_processing=s.post_processing,
                        range_start=self.r0.get(), range_end=self.r1.get(), cfg_text=s.cfg_text, cfg_key=s.cfg_key,
                        length=self.length.get(), use_keys=s.use_keys, use_center=s.use_center)
        os.makedirs(runner.WORK_DIR, exist_ok=True)
        json.dump(self.cfg, open(SETTINGS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return s

    def _run(self, fn, ok_message):
        if self.busy:
            return
        self.busy = True

        def work():
            try:
                r = fn(lambda line: self.q.put(("log", line)))
                if isinstance(r, dict) and r.get("backup"):
                    self.last_backup = r["backup"]
                    self.last_run = r
                self.q.put(("done", (True, ok_message)))
            except Exception as e:  # 窓に出して止める（握りつぶさない）
                self.q.put(("log", f"失敗: {e}"))
                self.q.put(("done", (False, f"失敗: {e}")))
        threading.Thread(target=work, daemon=True).start()

    def _generate(self):
        try:
            s = self._settings()
        except ValueError as e:
            messagebox.showerror("MMDKimodo", str(e), parent=self.root)
            return
        self._write_log("―" * 20)
        self.status.set("生成中…")
        previous = self.last_run
        self._run(lambda log: runner.generate(s, log, link=self.link, previous=previous),
                  "できました。MMD で再生して確かめてください（気に入らなければ「元に戻す」か、プロンプト・seed を変えてもう一度）")

    def _undo(self):
        backup = self.last_backup
        self.status.set("元に戻し中…")
        self._run(lambda log: runner.undo(backup, log, link=self.link), "生成前のモーションに戻しました")

    def _start_server(self):
        if not os.path.exists(SERVER_CMD):
            messagebox.showerror("MMDKimodo", f"サーバーの起動バッチがありません: {SERVER_CMD}", parent=self.root)
            return
        subprocess.Popen(["cmd.exe", "/c", SERVER_CMD], creationflags=subprocess.CREATE_NEW_CONSOLE)
        self.status.set("サーバーを起動しました（黒い窓）。10〜20 秒で ● になります")


def _notify_running(hwnd):
    """もう動いている MMDKimodo に「この MMD の窓を開いて」と知らせる。起動直後で目印がまだ無ければ少し待つ。"""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        hub = win32gui.FindWindowEx(win32con.HWND_MESSAGE, 0, HUB_CLASS, None)
        if hub:
            win32gui.PostMessage(hub, register_message(OPEN_MESSAGE), hwnd, 0)
            return True
        time.sleep(0.1)
    return False


def main():
    ap = argparse.ArgumentParser(description="MMDKimodo の窓（ふつうは MMD のメニューから開く）")
    ap.add_argument("--open", type=int, help="窓を開く MMD の窓（省くと一番手前の MMD）")
    args = ap.parse_args()
    hwnd = args.open or front_mmd()
    if not hwnd:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("MMDKimodo", "MMD が起動していません。MMD を起動してから開いてください")
        root.destroy()
        return
    mutex = win32event.CreateMutex(None, False, APP_MUTEX)  # 終わるまで持っておく
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        if not _notify_running(hwnd):
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("MMDKimodo", "MMDKimodo はもう起動中ですが、知らせる先が見つかりません。少し待ってからもう一度開いてください")
            root.destroy()
        return
    root = tk.Tk()
    root.withdraw()  # 親の窓は見せない。MMD ごとの窓（Toplevel）だけ出す
    hub = Hub(root)
    try:
        hub.open(hwnd)
        if hub.alive:
            root.mainloop()
    finally:
        hub.close()
        del mutex


if __name__ == "__main__":
    main()
