"""MMDKimodo の窓。起動すると MMD のメニューバー（ヘルプの右）に「MMDKimodo」が出る。

使い方: MMD でモデルを選び、いつもどおりポーズを付けてキーを打つ → ここでプロンプトを入れて「生成」。
生成は裏で回すので窓は固まらない。「元に戻す」で生成前のモーションに戻せる。
窓は MMD の持ち物（MMD の上に出て、MMD と一緒に隠れる）。× は隠すだけで、MMD のメニューからまた開ける。
"""
import ctypes
import json
import os
import queue
import socket
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import win32gui

from mmd_plugin.menu_host import MenuBridge

from . import runner

MENU_OPEN, MENU_QUIT = 0, 2
MENU_ITEMS = ["Kimodo の窓を開く", "-", "MMDKimodo を終了"]
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


class App:
    def __init__(self, root):
        self.root = root
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
        self.last_run = runner.load_last_run()   # 前回の生成（作り直しと「元に戻す」に使う）。開き直しても残る
        self.last_backup = self.last_run["backup"] if self.last_run else None
        self.menu = MenuBridge(MENU_ITEMS)
        self._build()
        self._attach_to_mmd()
        self._tick()
        self._poll_menu()

    # ---------------- MMD のメニュー ----------------

    def _attach_to_mmd(self):
        """MMD にメニューを出し、この窓の持ち主を MMD にする。"""
        self.menu.attach()
        self.root.update_idletasks()
        frame = int(self.root.wm_frame(), 16)
        _set_window_long(frame, -8, self.menu.window.hwnd)  # GWLP_HWNDPARENT（トップレベルの窓では持ち主）
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)

    def _poll_menu(self):
        """MMD のメニューで押された項目を拾う（通知は別スレッドに届くので、ここで取りに行く）。"""
        while not self.menu.commands.empty():
            index, _how = self.menu.commands.get()
            if index == MENU_OPEN:
                self.root.deiconify()
                self.root.lift()
                self.root.focus_force()
            elif index == MENU_QUIT:
                self.quit()
                return
        self.root.after(50, self._poll_menu)

    def quit(self):
        self.menu.detach()
        self.root.destroy()

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
        p = filedialog.askopenfilename(filetypes=[("PMX", "*.pmx"), ("すべて", "*.*")])
        if p:
            self.pmx.set(p)

    def _write_log(self, line):
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _tick(self):
        if not win32gui.IsWindow(self.menu.window.hwnd):  # MMD が閉じたら一緒に終わる
            self.quit()
            return
        while not self.q.empty():
            kind, payload = self.q.get()
            if kind == "log":
                self._write_log(payload)
            elif kind == "done":
                self.busy = False
                ok, msg = payload
                self.status.set(msg)
                if not ok:
                    messagebox.showerror("MMDKimodo", msg)
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
            messagebox.showerror("MMDKimodo", str(e))
            return
        self._write_log("―" * 20)
        self.status.set("生成中…")
        previous = self.last_run
        self._run(lambda log: runner.generate(s, log, previous=previous),
                  "できました。MMD で再生して確かめてください（気に入らなければ「元に戻す」か、プロンプト・seed を変えてもう一度）")

    def _undo(self):
        backup = self.last_backup
        self.status.set("元に戻し中…")
        self._run(lambda log: runner.undo(backup, log), "生成前のモーションに戻しました")

    def _start_server(self):
        if not os.path.exists(SERVER_CMD):
            messagebox.showerror("MMDKimodo", f"サーバーの起動バッチがありません: {SERVER_CMD}")
            return
        subprocess.Popen(["cmd.exe", "/c", SERVER_CMD], creationflags=subprocess.CREATE_NEW_CONSOLE)
        self.status.set("サーバーを起動しました（黒い窓）。10〜20 秒で ● になります")


def main():
    root = tk.Tk()
    try:
        app = App(root)
    except RuntimeError as e:  # MMD が無い・メニューを付けられない
        root.withdraw()
        messagebox.showerror("MMDKimodo", f"MMD にメニューを出せませんでした: {e}")
        root.destroy()
        return
    try:
        root.mainloop()
    finally:
        app.menu.detach()


if __name__ == "__main__":
    main()
