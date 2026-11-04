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

from . import gpu, runner, smooth_stop
from .message_window import MessageWindow, register_message
from .mmd_link import MMDLink
from .widgets import Fold, PromptRows, ScrollFrame

APP_MUTEX = "Local\\MMDKimodo.App.v1"
HUB_CLASS = "MMDKimodo.Hub"           # プラグインと 2 回目の起動が探す目印（kimodo_plugin.cpp と同じ）
OPEN_MESSAGE = "MMDKimodo.Open.v1"    # wparam = 開きたい MMD の窓
_set_window_long = ctypes.windll.user32.SetWindowLongPtrW
_set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
_set_window_long.restype = ctypes.c_void_p
SETTINGS_PATH = os.path.join(runner.WORK_DIR, "settings.json")
SERVER_CMD = r"F:\kimodo\start_textencoder.cmd"
DEFAULTS = {
    "tab": "kimodo", "mode": "fill", "range_mode": "all", "length": "",
    "prompt": "A person moves naturally between poses.",
    "steps": 100, "seed": -1, "post_processing": True, "cfg_text": 2.0, "cfg_key": 2.0, "use_center": False,
    "stop_at_last_key": True, "smooth_stop": True, "key_stop": False, "wrist_lerp": False,
    "perf_mode": "low",
}
OLD_KEYS = ("use_keys", "range_start", "range_end", "pmx")   # 前の窓の保存にあった項目（読む時に変換して捨てる）
TABS = [("kimodo", "プロンプトで作る"), ("nakawari", "中割り")]
# 動作モード（pipeline.PERF_MODES）。既定は低負荷（VRAM 8GB の GPU でも動く）。高速は GPU 診断で使える時だけ
PERF_MODES = [("low", "低負荷モード"), ("fast", "高速モード")]
MODES = [("fill", "キーの間を埋める"), ("extend", "続きを足す"), ("fresh", "プロンプトだけで作る")]
MODE_NOTES = {
    "fill": "打ったキーのポーズを守って、キーとキーの間を作ります（長さは最後のキーまで）",
    "extend": "打ったキーのポーズを守って、最後のキーの後ろに続きを作ります",
    "fresh": "キーのポーズは使わず、最初のキーの場所と向きからプロンプトだけで作ります",
}
NAKAWARI_NOTE = ("打ったキーとキーの間を、MotionBricks でつなぎます。プロンプトは使いません。\n"
                 "キーの間が 17〜57 フレームの所だけ作り、それより短い・長い所は MMD の補間のまま残します。")
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
        root.minsize(560, 0)   # 高さの下限は _build で決める（上と下の段が必ず見える高さ）
        root.attributes("-topmost", False)
        self.cfg = dict(DEFAULTS)
        try:
            saved = json.load(open(SETTINGS_PATH, encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
        if "mode" not in saved and saved.get("use_keys") is False:   # 前の窓の「打ったキーのポーズを守る」オフ
            saved["mode"] = "fresh" if saved.get("length") else "fill"
        self.cfg.update({k: v for k, v in saved.items() if k not in OLD_KEYS})
        if self.cfg["mode"] == "nakawari":   # 中割りがモードの 1 つだった時の保存（11-04 の昼）
            self.cfg.update(tab="nakawari", mode="fill")
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
        """上（モデル・サーバー）と下（範囲・生成・状態）は固定し、真ん中のタブだけを伸び縮みさせる。

        tkinter は入りきらない分を下から黙って切るので、生成を一番下寄りに積んでいた前の並びでは、窓を低くすると生成が消えていた。
        タブの中身は ScrollFrame に入れ、入りきらなければスクロールする。タブを切り替えても窓の大きさは変えない。
        """
        pad = {"padx": 10, "pady": 4}
        f = ttk.Frame(self.root)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        # 上: MMD のモデル欄で選んだモデルに効く。テキスト読み取りサーバーの印（Kimodo だけが使う）
        head = ttk.Frame(f)
        head.grid(row=0, column=0, sticky="we", **pad)
        self.model_text = tk.StringVar(value="選択中のモデル：（読み取り中）")
        ttk.Label(head, textvariable=self.model_text).pack(side="left")
        # 動作モード。高速モードの時だけ、テキスト読み取りサーバーの印を横に出す
        self.head_server = ttk.Label(head, text="")
        self.head_server.pack(side="right", padx=(6, 0))
        self.diagnosis = gpu.diagnose()
        names = dict(PERF_MODES)
        mode = self.cfg["perf_mode"] if self.cfg["perf_mode"] in names else "low"
        if mode == "fast" and not self.diagnosis.fast_ok:   # 保存は高速でも、この PC では使えない
            mode = "low"
        self.perf = tk.StringVar(value=names[mode])
        box = ttk.Combobox(head, textvariable=self.perf, values=[n for _, n in PERF_MODES], state="readonly", width=12)
        box.pack(side="right")
        box.bind("<<ComboboxSelected>>", lambda _e: self._perf_changed())

        # 真ん中: やり方ごとのタブ
        self.tabs = ttk.Notebook(f)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=10, pady=(2, 4))
        pages = []
        for _, text in TABS:
            page = ScrollFrame(self.tabs)
            self.tabs.add(page, text=text)
            pages.append(page.inner)
        self._build_kimodo(pages[0])
        self._build_nakawari(pages[1])
        self.tabs.select(1 if self.cfg["tab"] == "nakawari" else 0)

        # 下: どちらのタブにも効く範囲・生成・状態
        foot = ttk.Frame(f)
        foot.grid(row=2, column=0, sticky="we", padx=10, pady=(0, 8))
        rf = ttk.Frame(foot)
        rf.pack(fill="x", pady=(0, 4))
        ttk.Label(rf, text="範囲", width=10).pack(side="left")
        self.range_mode = tk.StringVar(value=self.cfg["range_mode"])
        self.range_text = tk.StringVar(value="MMD の範囲選択")
        ttk.Radiobutton(rf, text="全部", value="all", variable=self.range_mode).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(rf, textvariable=self.range_text, value="mmd", variable=self.range_mode).pack(side="left")
        bf = ttk.Frame(foot)
        bf.pack(fill="x")
        self.gen_btn = ttk.Button(bf, text="生成", command=self._generate)
        self.gen_btn.pack(side="left", fill="x", expand=True, ipady=8)
        self.undo_btn = ttk.Button(bf, text="元に戻す", command=self._undo, state="disabled")
        self.undo_btn.pack(side="left", padx=(6, 0), ipady=8)
        sf = ttk.Frame(foot)
        sf.pack(fill="x", pady=(4, 0))
        ttk.Button(sf, text="ログ", width=6, command=self._toggle_log).pack(side="right")
        # 状態は 1 行（下の段の高さを変えない）。長い失敗の文はログと失敗の窓に全文が出る
        self.status = tk.StringVar(value="MMD でキーを打ってから「生成」を押してください")
        ttk.Label(sf, textvariable=self.status, foreground="#335").pack(side="left", fill="x", expand=True)

        # ログは別の小さな窓（本体の並びを押し出さない）。× は隠すだけ
        self.log_win = tk.Toplevel(self.root)
        self.log_win.title("MMDKimodo のログ")
        self.log_win.withdraw()
        self.log_win.protocol("WM_DELETE_WINDOW", self.log_win.withdraw)
        bar = ttk.Scrollbar(self.log_win, orient="vertical")
        bar.pack(side="right", fill="y")
        self.log = tk.Text(self.log_win, width=90, height=24, wrap="word", state="disabled", background="#f6f6f6",
                           yscrollcommand=bar.set)
        self.log.pack(fill="both", expand=True)
        bar.configure(command=self.log.yview)
        self._mode_changed()
        self._perf_changed()

        # 窓の高さの下限: 上と下の段と、タブの見出し＋中身 3 行ほど。これより低くできないので、生成と状態は必ず見える
        self.root.update_idletasks()
        self.root.minsize(560, head.winfo_reqheight() + foot.winfo_reqheight() + 150)

    def _toggle_log(self):
        if self.log_win.winfo_viewable():
            self.log_win.withdraw()
        else:
            self.log_win.deiconify()
            self.log_win.lift()

    def _build_kimodo(self, t):
        """「プロンプトで作る」タブ（Kimodo）。"""
        # やりたいこと・長さ。行ごとに別の並びにする（表の列を共有すると、説明の長さが変わった時にボタンが横にずれる）
        def line(title, pady=(0, 0)):
            row = ttk.Frame(t)
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
                 wraplength=420, height=2, anchor="nw", justify="left").pack(side="left", fill="x")
        length_row = line("長さ", pady=(4, 0))
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
        ttk.Separator(t).pack(fill="x", pady=(8, 6))

        # プロンプト（区間ごとの行）
        ttk.Label(t, text="プロンプト（英語・行ごとに、そのフレームから次の行までの動き）").pack(anchor="w")
        self.prompt_rows = PromptRows(t)
        self.prompt_rows.pack(fill="x", pady=(4, 0))
        self.prompt_rows.load(self.cfg["prompt"])
        self.split_text = tk.StringVar(value="＋ 今のフレームで区切る")
        ttk.Button(t, textvariable=self.split_text, command=self._split_here).pack(anchor="w", pady=(4, 0))

        details = Fold(t, "詳しい設定")
        details.pack(fill="x", pady=(8, 0))
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
        # GPU 診断と動作モードの説明。テキスト読み取りサーバーは高速モードの Kimodo だけが使うので、このタブの中に置く
        d = self.diagnosis
        tk.Label(t, text=f"{d.summary()} → {d.note}" if d.gpu else d.note, foreground="#556",
                 background=ttk.Style().lookup("TFrame", "background"), wraplength=500, anchor="w", justify="left").pack(fill="x", pady=(8, 0))
        self.perf_note = tk.StringVar()
        tk.Label(t, textvariable=self.perf_note, foreground="#556", background=ttk.Style().lookup("TFrame", "background"),
                 wraplength=500, anchor="w", justify="left").pack(fill="x")
        sf = ttk.Frame(t)
        sf.pack(fill="x", pady=(4, 0))
        self.server_dot = ttk.Label(sf, text="")
        self.server_dot.pack(side="left")
        self.server_label = ttk.Label(sf, text="", foreground="#556")
        self.server_label.pack(side="left", padx=(6, 0))
        self.server_btn = ttk.Button(sf, text="サーバーを起動", command=self._start_server)
        self.server_btn.pack(side="right")

    def _build_nakawari(self, t):
        """「中割り」タブ（MotionBricks）。"""
        tk.Label(t, text=NAKAWARI_NOTE, foreground="#556", background=ttk.Style().lookup("TFrame", "background"),
                 wraplength=500, anchor="w", justify="left").pack(fill="x")
        self.key_stop = tk.BooleanVar(value=self.cfg["key_stop"])
        self.wrist_lerp = tk.BooleanVar(value=self.cfg["wrist_lerp"])
        state = "normal" if smooth_stop.available() else "disabled"
        ttk.Checkbutton(t, text="キーごとに止まる（外すと、次のキーへ向かう勢いのまま通る）", variable=self.key_stop,
                        state=state).pack(anchor="w", pady=(10, 0))
        ttk.Checkbutton(t, text="手首は普通の補間（MotionBricks は手首を回しすぎることがある）", variable=self.wrist_lerp,
                        state=state).pack(anchor="w", pady=(4, 0))
        if not smooth_stop.available():
            ttk.Label(t, text=f"MotionBricks が入っていません（{smooth_stop.MB_PYTHON}）", foreground="#a33").pack(anchor="w", pady=(10, 0))

    def _perf_mode(self):
        return next(k for k, n in PERF_MODES if n == self.perf.get())

    def _perf_changed(self):
        if self._perf_mode() == "fast" and not self.diagnosis.fast_ok:
            messagebox.showinfo("MMDKimodo", f"この PC では高速モードは使えません（{self.diagnosis.note}）。低負荷モードで作ります",
                                parent=self.root)
            self.perf.set(dict(PERF_MODES)["low"])
        self.perf_note.set("低負荷モード: 文の読み取りを CPU で行います（VRAM 約 1.3GB・メインメモリ約 15GB。1 文 3 秒ほど。同じ文は 2 回目から速い）"
                           if self._perf_mode() == "low" else
                           "高速モード: 文の読み取りを GPU のサーバーで行います（VRAM 約 18GB。下の「サーバーを起動」が必要）")

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
        self.server_dot.configure(text="●" if up else "○", foreground="#2a7" if up else "#a33")
        fast = self._perf_mode() == "fast"
        self.head_server.configure(text=("● サーバー" if up else "○ サーバー停止中") if fast else "",
                                   foreground="#2a7" if up else "#a33")
        self.server_label.configure(text="テキスト読み取りサーバー起動中" if up else "テキスト読み取りサーバー停止中（無いと毎回 Llama を読み込むので遅い）")
        self.server_btn.configure(state="disabled" if up else "normal")
        self.gen_btn.configure(state="disabled" if self.busy else "normal")
        self.undo_btn.configure(state="normal" if (self.last_backup and not self.busy) else "disabled")
        self.root.after(500, self._tick)

    # ---------------- 操作 ----------------

    def _settings(self):
        def opt_int(s):
            s = s.strip()
            return int(s) if s else None
        tab = TABS[self.tabs.index("current")][0]
        mode = self.mode.get()
        nakawari = tab == "nakawari"
        length = opt_int(self.length.get()) if mode != "fill" and not nakawari else None
        if nakawari and not smooth_stop.available():
            raise ValueError(f"中割りには MotionBricks が要ります（{smooth_stop.MB_PYTHON} がありません）")
        if not nakawari and mode != "fill" and length is None:
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
                            length=length, use_keys=nakawari or mode != "fresh",
                            use_center=bool(self.use_center.get()) and not nakawari,
                            stop_at_last_key=mode != "fresh" and bool(self.stop.get()),
                            smooth_stop=bool(self.smooth.get()) and smooth_stop.available(),
                            engine="motionbricks" if nakawari else "kimodo",
                            key_stop=bool(self.key_stop.get()), wrist_lerp=bool(self.wrist_lerp.get()),
                            perf_mode=self._perf_mode())
        self.cfg.update(tab=tab, mode=mode, range_mode=self.range_mode.get(), length=self.length.get(), prompt=s.prompt,
                        steps=s.steps, seed=s.seed, post_processing=s.post_processing,
                        cfg_text=s.cfg_text, cfg_key=s.cfg_key, use_center=bool(self.use_center.get()),
                        stop_at_last_key=bool(self.stop.get()), smooth_stop=bool(self.smooth.get()),
                        key_stop=s.key_stop, wrist_lerp=s.wrist_lerp, perf_mode=s.perf_mode)
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
