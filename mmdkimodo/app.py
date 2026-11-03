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
from tkinter import messagebox, ttk

import win32api
import win32con
import win32event
import win32gui
import winerror

from mmd_mcp.windows import list_windows

from . import runner, smooth_stop
from .message_window import MessageWindow, register_message
from .mmd_link import MMDLink
from .widgets import Fold, PromptRows

APP_MUTEX = "Local\\MMDKimodo.App.v1"
HUB_CLASS = "MMDKimodo.Hub"           # プラグインと 2 回目の起動が探す目印（kimodo_plugin.cpp と同じ）
OPEN_MESSAGE = "MMDKimodo.Open.v1"    # wparam = 開きたい MMD の窓
_set_window_long = ctypes.windll.user32.SetWindowLongPtrW
_set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
_set_window_long.restype = ctypes.c_void_p
SETTINGS_PATH = os.path.join(runner.WORK_DIR, "settings.json")
SERVER_CMD = r"F:\kimodo\start_textencoder.cmd"
DEFAULTS = {
    "mode": "fill", "range_mode": "all", "length": "",
    "prompt": "A person moves naturally between poses.",
    "steps": 100, "seed": -1, "post_processing": True, "cfg_text": 2.0, "cfg_key": 2.0, "use_center": False,
    "stop_at_last_key": True, "smooth_stop": True,
}
OLD_KEYS = ("use_keys", "range_start", "range_end", "pmx")   # 前の窓の保存にあった項目（読む時に変換して捨てる）
MODES = [("fill", "キーの間を埋める"), ("extend", "続きを足す"), ("fresh", "プロンプトだけで作る")]
MODE_NOTES = {
    "fill": "打ったキーのポーズを守って、キーとキーの間を作ります（長さは最後のキーまで）",
    "extend": "打ったキーのポーズを守って、最後のキーの後ろに続きを作ります",
    "fresh": "キーのポーズは使わず、最初のキーの場所と向きからプロンプトだけで作ります",
}
PARTS = ["体", "左腕", "右腕", "左脚", "右脚"]
NO_RANGE = 999999   # MMD の範囲選択の終わりの初期値（範囲を入れていない）

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
        root.minsize(560, 0)   # 高さは中身に合わせる（畳んだ欄を開くと伸びる）
        root.attributes("-topmost", False)
        self.cfg = dict(DEFAULTS)
        try:
            saved = json.load(open(SETTINGS_PATH, encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if "mode" not in saved and saved.get("use_keys") is False:   # 前の窓の「打ったキーのポーズを守る」オフ
            saved["mode"] = "fresh" if saved.get("length") else "fill"
        self.cfg.update({k: v for k, v in saved.items() if k not in OLD_KEYS})
        self.q = queue.Queue()
        self.busy = False
        self._model_ticks = 1   # MMD の読み取り（モデル・今のフレーム・範囲選択）は 2 回に 1 回（1 秒ごと）。最初はすぐ読む
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
        pad = {"padx": 10, "pady": 4}
        f = ttk.Frame(self.root)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        # MMD のモデル欄で選んだモデルに効く
        head = ttk.Frame(f)
        head.grid(row=0, column=0, sticky="we", **pad)
        self.model_text = tk.StringVar(value="選択中のモデル：（読み取り中）")
        ttk.Label(head, textvariable=self.model_text).pack(side="left")
        self.server_dot = ttk.Label(head, text="")
        self.server_dot.pack(side="right")
        ttk.Separator(f).grid(row=1, column=0, sticky="we", padx=10)

        # やりたいこと・範囲・長さ。行ごとに別の並びにする（表の列を共有すると、説明の長さが変わった時にボタンが横にずれる）
        top = ttk.Frame(f)
        top.grid(row=2, column=0, sticky="we", **pad)

        def line(title, pady=(0, 0)):
            row = ttk.Frame(top)
            row.pack(fill="x", pady=pady)
            ttk.Label(row, text=title, width=10).pack(side="left")
            return row

        mode_row = line("やりたいこと")
        self.mode = tk.StringVar(value=self.cfg["mode"] if self.cfg["mode"] in MODE_NOTES else "fill")
        for key, text in MODES:
            ttk.Radiobutton(mode_row, text=text, value=key, variable=self.mode, command=self._mode_changed).pack(side="left", padx=(0, 12))
        self.mode_note = tk.StringVar()
        # 説明が 1 行でも 2 行でも高さを変えない（変わると下の段が縦にずれる）
        tk.Label(line(""), textvariable=self.mode_note, foreground="#556", background=ttk.Style().lookup("TFrame", "background"),
                 wraplength=440, height=2, anchor="nw", justify="left").pack(side="left", fill="x")
        range_row = line("範囲", pady=(6, 0))
        self.range_mode = tk.StringVar(value=self.cfg["range_mode"])
        self.range_text = tk.StringVar(value="MMD の範囲選択")
        ttk.Radiobutton(range_row, text="全部", value="all", variable=self.range_mode).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(range_row, textvariable=self.range_text, value="mmd", variable=self.range_mode).pack(side="left")
        length_row = line("長さ", pady=(6, 0))
        self.length = tk.StringVar(value=str(self.cfg["length"]))
        self.length_entry = ttk.Entry(length_row, textvariable=self.length, width=6)
        self.length_entry.pack(side="left")
        self.length_note = tk.StringVar()
        ttk.Label(length_row, textvariable=self.length_note, foreground="#556").pack(side="left", padx=(6, 0))
        # キーは「その瞬間にこの姿勢を通る」だけなので、止めないと走りなどは最後のキーを勢いのまま通り過ぎる
        self.stop = tk.BooleanVar(value=self.cfg["stop_at_last_key"])
        stop_row = line("", pady=(4, 0))
        self.stop_check = ttk.Checkbutton(stop_row, text="最後のキーで止まる（勢いのまま通り過ぎない）", variable=self.stop,
                                          command=self._stop_changed)
        self.stop_check.pack(side="left")
        # Kimodo だけだとキーの直前で急に止まるので、止まる所を MotionBricks で作り直す（smooth_stop.py）
        self.smooth = tk.BooleanVar(value=self.cfg["smooth_stop"] and smooth_stop.available())
        self.smooth_check = ttk.Checkbutton(stop_row, text="なめらかに（MotionBricks）", variable=self.smooth)
        self.smooth_check.pack(side="left", padx=(12, 0))
        ttk.Separator(f).grid(row=3, column=0, sticky="we", padx=10)

        # プロンプト（区間ごとの行）
        pf = ttk.Frame(f)
        pf.grid(row=4, column=0, sticky="we", **pad)
        ttk.Label(pf, text="プロンプト（英語・行ごとに、そのフレームから次の行までの動き）").pack(anchor="w")
        self.prompt_rows = PromptRows(pf)
        self.prompt_rows.pack(fill="x", pady=(4, 0))
        self.prompt_rows.load(self.cfg["prompt"])
        self.split_text = tk.StringVar(value="＋ 今のフレームで区切る")
        ttk.Button(pf, textvariable=self.split_text, command=self._split_here).pack(anchor="w", pady=(4, 0))
        ttk.Separator(f).grid(row=5, column=0, sticky="we", padx=10)

        # 書き戻す部分（仕組みはまだ。置き場所だけ）・生成
        wf = ttk.Frame(f)
        wf.grid(row=6, column=0, sticky="we", **pad)
        ttk.Label(wf, text="書き戻す部分").pack(side="left")
        for part in PARTS:
            check = ttk.Checkbutton(wf, text=part, state="disabled")
            check.state(["selected", "!alternate", "disabled"])
            check.pack(side="left", padx=(8, 0))
        ttk.Label(wf, text="（準備中）", foreground="#888").pack(side="left", padx=(8, 0))
        bf = ttk.Frame(f)
        bf.grid(row=7, column=0, sticky="we", **pad)
        self.gen_btn = ttk.Button(bf, text="生成", command=self._generate)
        self.gen_btn.pack(side="left", fill="x", expand=True, ipady=8)
        self.undo_btn = ttk.Button(bf, text="元に戻す", command=self._undo, state="disabled")
        self.undo_btn.pack(side="left", padx=(6, 0), ipady=8)
        self.status = tk.StringVar(value="MMD でキーを打ってから「生成」を押してください")
        ttk.Label(f, textvariable=self.status, foreground="#335", wraplength=520).grid(row=8, column=0, sticky="w", **pad)

        # 畳む欄: 詳しい設定・ログ
        details = Fold(f, "詳しい設定")
        details.grid(row=9, column=0, sticky="we", padx=10, pady=(4, 0))
        d, g = details.body, {"padx": 4, "pady": 2}
        ttk.Label(d, text="手数（少ないほど速い）").grid(row=0, column=0, sticky="w", **g)
        self.steps = tk.IntVar(value=self.cfg["steps"])
        ttk.Spinbox(d, from_=10, to=100, increment=10, textvariable=self.steps, width=6).grid(row=0, column=1, sticky="w", **g)
        ttk.Label(d, text="seed（-1 で毎回変える）").grid(row=1, column=0, sticky="w", **g)
        self.seed = tk.IntVar(value=self.cfg["seed"])
        ttk.Entry(d, textvariable=self.seed, width=8).grid(row=1, column=1, sticky="w", **g)
        # Kimodo の CFG の重み。テキストを上げるとプロンプトの動きが強く出る（回転なら 8・1 で振り向くほど）
        ttk.Label(d, text="テキストの効き").grid(row=0, column=2, sticky="e", **g)
        self.cfg_text = tk.DoubleVar(value=self.cfg["cfg_text"])
        ttk.Spinbox(d, from_=0.5, to=10, increment=0.5, textvariable=self.cfg_text, width=5).grid(row=0, column=3, sticky="w", **g)
        ttk.Label(d, text="キーの効き").grid(row=1, column=2, sticky="e", **g)
        self.cfg_key = tk.DoubleVar(value=self.cfg["cfg_key"])
        ttk.Spinbox(d, from_=0.5, to=10, increment=0.5, textvariable=self.cfg_key, width=5).grid(row=1, column=3, sticky="w", **g)
        self.post = tk.BooleanVar(value=self.cfg["post_processing"])
        ttk.Checkbutton(d, text="キーに合わせる後処理", variable=self.post).grid(row=2, column=0, columnspan=2, sticky="w", **g)
        # センターの上下などを毎フレームの腰の目印にする（リズムを残して動きを作る。プロンプトだけで作る時と組み合わせる想定）
        self.use_center = tk.BooleanVar(value=self.cfg["use_center"])
        ttk.Checkbutton(d, text="センターの動きを使う", variable=self.use_center).grid(row=2, column=2, columnspan=2, sticky="w", **g)
        sf = ttk.Frame(d)
        sf.grid(row=3, column=0, columnspan=4, sticky="we", **g)
        self.server_label = ttk.Label(sf, text="")
        self.server_label.pack(side="left")
        self.server_btn = ttk.Button(sf, text="サーバーを起動", command=self._start_server)
        self.server_btn.pack(side="right")
        logs = Fold(f, "ログ")
        logs.grid(row=10, column=0, sticky="nsew", padx=10, pady=(4, 8))
        self.log = tk.Text(logs.body, height=12, wrap="word", state="disabled", background="#f6f6f6")
        self.log.pack(fill="both", expand=True)
        f.rowconfigure(10, weight=1)
        self._mode_changed()

    def _mode_changed(self):
        mode = self.mode.get()
        self.mode_note.set(MODE_NOTES[mode])
        if mode == "fill":
            self.length_entry.configure(state="disabled")
            self.length_note.set("F（最後のキーまで）")
        else:
            self.length_entry.configure(state="normal")
            self.length_note.set("F（最初のキーから。必須）" if mode == "fresh" else "F（最初のキーから。最後のキーより長く）")
        self.stop_check.configure(state="disabled" if mode == "fresh" else "normal")   # プロンプトだけで作る時は止める位置のキーが無い
        self._stop_changed()

    def _stop_changed(self):
        usable = self.mode.get() != "fresh" and self.stop.get() and smooth_stop.available()
        self.smooth_check.configure(state="normal" if usable else "disabled")

    def _split_here(self):
        """MMD で今いるフレームから新しい区間にする。"""
        try:
            frame = self.link.current_frame()
        except Exception as e:
            frame, error = None, e
        else:
            error = None
        if frame is None:
            self.status.set(f"MMD の今のフレームを読めませんでした{f'（{error}）' if error else ''}")
        elif not self.prompt_rows.add_at(frame):
            self.status.set(f"{frame}F から始まる区間はもうあります")

    def _read_mmd(self):
        """MMD の選択中のモデル・今のフレーム・範囲選択を読んで表示する（1 秒ごと）。生成中は MMD を操作しているので読みに行かない。"""
        self._model_ticks += 1
        if self.busy or self._model_ticks % 2:
            return
        frame = selection = None
        try:
            model = self.link.selected_model()
            frame = self.link.current_frame()
            selection = self.link.range_selection()
        except Exception as e:  # 読めない理由をそのまま出す（MMD の版が違う・選び替えの途中など）
            text = f"選択中のモデル：（読み取れません: {e}）"
        else:
            text = f"選択中のモデル：{model['name']}" if model else "選択中のモデル：（なし。MMD のモデル欄でモデルを選んでください）"
        updates = [(self.model_text, text),
                   (self.split_text, f"＋ 今のフレーム（{frame}F）で区切る" if frame is not None else "＋ 今のフレームで区切る"),
                   (self.range_text, f"MMD の範囲選択（{selection[0]}〜{selection[1]}F）"
                    if selection and selection[1] < NO_RANGE else "MMD の範囲選択（未設定）")]
        for var, value in updates:
            if var.get() != value:
                var.set(value)

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
        self._read_mmd()
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
        self.server_dot.configure(text="● サーバー" if up else "○ サーバー停止中", foreground="#2a7" if up else "#a33")
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
        mode = self.mode.get()
        length = opt_int(self.length.get()) if mode != "fill" else None
        if mode != "fill" and length is None:
            raise ValueError("「続きを足す」「プロンプトだけで作る」では長さを入れてください")
        selection = None
        if self.range_mode.get() == "mmd":
            selection = self.link.range_selection()
            if not selection or selection[1] >= NO_RANGE:
                raise ValueError("MMD の範囲選択が入っていません（タイムラインの下の開始〜終了フレーム）")
        s = runner.Settings(prompt=self.prompt_rows.text(),
                            steps=int(self.steps.get()), seed=int(self.seed.get()), post_processing=bool(self.post.get()),
                            range_start=selection[0] if selection else None, range_end=selection[1] if selection else None,
                            cfg_text=float(self.cfg_text.get()), cfg_key=float(self.cfg_key.get()),
                            length=length, use_keys=mode != "fresh", use_center=bool(self.use_center.get()),
                            stop_at_last_key=mode != "fresh" and bool(self.stop.get()),
                            smooth_stop=bool(self.smooth.get()) and smooth_stop.available())
        self.cfg.update(mode=mode, range_mode=self.range_mode.get(), length=self.length.get(), prompt=s.prompt,
                        steps=s.steps, seed=s.seed, post_processing=s.post_processing,
                        cfg_text=s.cfg_text, cfg_key=s.cfg_key, use_center=s.use_center, stop_at_last_key=bool(self.stop.get()),
                        smooth_stop=bool(self.smooth.get()))
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
        except (ValueError, RuntimeError) as e:
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
