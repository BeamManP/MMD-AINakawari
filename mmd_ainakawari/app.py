"""AIナカワリ の窓。MMD のメニュー「AIナカワリ」→「AIナカワリの窓を開く」から開く（MMDPlugin のプラグイン mmd_plugin/nakawari_plugin.cpp）。

使い方: MMD でモデルを選び、いつもどおりポーズを付けてキーを打つ → ここでプロンプトを入れて「生成」。
生成は裏で回すので窓は固まらない。「元に戻す」で生成前のモーションに戻せる。
窓は MMD ごとに 1 つで、その MMD の持ち物（MMD の上に出て、MMD と一緒に隠れる）。× は隠すだけで、MMD のメニューからまた開ける。
プロセスは 1 つだけ。プラグインは、動いていれば見えない窓（AINakawari.Hub）に「この MMD の窓を開いて」と知らせ、
動いていなければ --open <MMD の窓> 付きで起動する。全部の MMD が閉じたら終わる。
"""
import argparse
import ctypes
import json
import os
import queue
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

from . import applog, gpu, panel, paths, runner, samples, smooth_stop
from .installer import window as setup_window
from .message_window import MessageWindow, register_message
from .mmd_link import MMDLink
from .widgets import Fold, PromptRows, ScrollFrame

APP_MUTEX = "Local\\AINakawari.App.v1"
HUB_CLASS = "AINakawari.Hub"           # プラグインと 2 回目の起動が探す目印（nakawari_plugin.cpp と同じ）
OPEN_MESSAGE = "AINakawari.Open.v1"    # wparam = 開きたい MMD の窓
ATTACH_MESSAGE = "AINakawari.Attach.v1"   # wparam = MMD の窓。窓を隠したまま作る（MMD の右下のパネル用。nakawari_plugin.cpp）
ATTACH_WAIT = 30   # 隠したまま作る時に、起動の途中の MMD の窓が見えるようになるまで待つ秒数
PANEL_MESSAGE = "AINakawari.Panel.v1"     # wparam = MMD の窓・lparam = 押されたパネルのボタン（panel.GENERATE など）
_set_window_long = ctypes.windll.user32.SetWindowLongPtrW
_set_window_long.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
_set_window_long.restype = ctypes.c_void_p
SETTINGS_PATH = os.path.join(runner.WORK_DIR, "settings.json")
DEFAULTS = {
    "tab": "kimodo", "mode": "fill", "range_mode": "keys", "length": "",   # 範囲は選んだキーの間から（11-05 マスター）
    "prompt": "A person moves naturally between poses.",
    "steps": 100, "seed": -1, "post_processing": True, "cfg_text": 2.0, "cfg_key": 2.0, "use_center": False,
    "stop_at_last_key": True, "smooth_stop": True, "key_stop": False, "wrist_lerp": False,
}
OLD_KEYS = ("use_keys", "range_start", "range_end", "pmx", "perf_mode")   # 前の窓の保存にあった項目（読む時に変換して捨てる。perf_mode は 11-07 まであった動作モード）
TABS = [("kimodo", "Kimodo"), ("nakawari", "MotionBricks")]   # 右下のパネルの選び方と同じ名前（11-06 マスター。前は「プロンプトで作る／中割り」）
MODES = [("fill", "キーの間を埋める"), ("extend", "続きを足す"), ("fresh", "プロンプトだけで作る")]
MODE_NOTES = {
    "fill": "打ったキーのポーズを守って、キーとキーの間を作ります（長さは最後のキーまで）",
    "extend": "打ったキーのポーズを守って、最後のキーの後ろに続きを作ります",
    "fresh": "最初のキーの場所と向きから、プロンプトだけで動きを作ります",
}
NAKAWARI_NOTE = ("打ったキーとキーの間を、プロンプト無しで MotionBricks がつなぎます。\n"
                 "作るのはキーの間が 17〜57 フレームの所で、それ以外は MMD の補間を使います。")

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
        self.waiting = {}   # 隠したまま作るのを待っている MMD の窓 → 待つ期限（見えるようになったら作る）
        self.alive = True
        self.requests = queue.Queue()
        self.listener = MessageWindow(HUB_CLASS, {
            OPEN_MESSAGE: lambda w, _l: self.requests.put(("open", int(w), 0)),
            ATTACH_MESSAGE: lambda w, _l: self.requests.put(("attach", int(w), 0)),
            PANEL_MESSAGE: lambda w, l: self.requests.put(("panel", int(w), int(l))),
        })
        self.listener.start()
        self._poll()

    def open(self, hwnd, show=True):
        """その MMD の窓を出す（まだ無ければ作る）。show=False なら隠したまま作る（MMD の右下のパネルから使う）。

        隠したまま作るのは MMD の起動の途中（プラグインの start）に頼まれるので、MMD の窓がまだ見えておらず、
        list_windows に出てこない（11-04、それで Python がすぐ終わっていた）。なので見えるまで ATTACH_WAIT 秒待つ。
        """
        mmd = next((w for w in list_windows() if w.hwnd == hwnd), None)
        if mmd is None:
            if show:
                messagebox.showerror("AIナカワリ", "開こうとした MMD が見つかりません。MMD が開いているか確かめてください")
            elif win32gui.IsWindow(hwnd):
                self.waiting.setdefault(hwnd, time.monotonic() + ATTACH_WAIT)
        else:
            self.waiting.pop(hwnd, None)
            if hwnd not in self.apps:
                self.apps[hwnd] = App(tk.Toplevel(self.root), self, mmd)
            if show:
                self.apps[hwnd].show()
        if not self.apps and not self.waiting:
            self._finish()

    def forget(self, app):
        self.apps.pop(app.mmd.hwnd, None)
        if not self.apps and not self.waiting:   # 起動の途中の MMD を待っている間は終わらない（11-05 Codex のレビュー）
            self._finish()

    def _finish(self):
        """相手の MMD が 1 つも無くなったら終わる。セットアップの窓が出ている間は、閉じられるまで待つ（裏の uv などを置き去りにしない）。"""
        if setup_window.is_open():
            self.root.after(1000, lambda: self._finish() if not self.apps and not self.waiting and self.alive else None)
            return
        self.alive = False
        self.root.destroy()

    def close(self):
        self.listener.stop()

    def _poll(self):
        while not self.requests.empty():
            kind, hwnd, button = self.requests.get()
            if kind == "panel":
                if hwnd not in self.apps:
                    self.open(hwnd, show=False)
                if hwnd in self.apps:
                    self.apps[hwnd].panel_pressed(button)
            else:
                self.open(hwnd, show=kind == "open")
        for hwnd, deadline in list(self.waiting.items()):   # 起動の途中の MMD が見えるようになったら作る
            if time.monotonic() > deadline or not win32gui.IsWindow(hwnd):
                self.waiting.pop(hwnd)
                if not self.apps and not self.waiting:
                    self._finish()
            elif self.alive:
                self.open(hwnd, show=False)
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
        root.title("AIナカワリ")
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
        self.selected_keys = None    # MMD のタイムラインで選んでいるキーのフレーム（_read_mmd が 1 秒ごとに読む。読めなければ None）
        self._status_before = None   # 生成できない知らせ（GPU が無い・キーを選んでいない）を出す前の 1 行（出していない時は None）
        self._model_ticks = 1   # MMD の読み取り（モデル・今のフレーム・範囲選択）は 2 回に 1 回（1 秒ごと）。最初はすぐ読む
        self.last_run = runner.load_last_run(self.link)   # この MMD での前回の生成（作り直しと「元に戻す」に使う）。窓を開き直しても残る
        self.last_backup = self.last_run["backup"] if self.last_run else None
        self._build()
        # MMD の右下のパネル。窓と同じ設定を、変わった方からもう一方へ写す（_sync_panel）
        self.panel = panel.Panel(mmd.hwnd)
        self._seen = {}   # 最後に同期した時の値 {("panel"|"window", 項目): 値}
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
        """上（モデル）と下（範囲・生成・状態）は固定し、真ん中のタブだけを伸び縮みさせる。

        tkinter は入りきらない分を下から黙って切るので、生成を一番下寄りに積んでいた前の並びでは、窓を低くすると生成が消えていた。
        タブの中身は ScrollFrame に入れ、入りきらなければスクロールする。タブを切り替えても窓の大きさは変えない。
        """
        pad = {"padx": 10, "pady": 4}
        f = ttk.Frame(self.root)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        # 上: MMD のモデル欄で選んだモデルに効く
        head = ttk.Frame(f)
        head.grid(row=0, column=0, sticky="we", **pad)
        self.model_text = tk.StringVar(value="選択中のモデル：（読み取り中）")
        ttk.Label(head, textvariable=self.model_text).pack(side="left")
        self.diagnosis = gpu.diagnose()

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
        # 前の保存の "mmd"（MMD の範囲選択の欄を読んでいた形）は、選んだキーの間に置き換える
        self.range_mode = tk.StringVar(value="keys" if self.cfg["range_mode"] in ("keys", "mmd") else "all")
        self.range_text = tk.StringVar(value="選んだキーの間")
        ttk.Radiobutton(rf, text="全部", value="all", variable=self.range_mode, command=self._mode_changed).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(rf, textvariable=self.range_text, value="keys", variable=self.range_mode,
                        command=self._mode_changed).pack(side="left")
        bf = ttk.Frame(foot)
        bf.pack(fill="x")
        self.gen_btn = ttk.Button(bf, text="生成", command=self._generate)
        self.gen_btn.pack(side="left", fill="x", expand=True, ipady=8)
        self.undo_btn = ttk.Button(bf, text="元に戻す", command=self._undo, state="disabled")
        self.undo_btn.pack(side="left", padx=(6, 0), ipady=8)
        sf = ttk.Frame(foot)
        sf.pack(fill="x", pady=(4, 0))
        ttk.Button(sf, text="ログ", width=6, command=self._toggle_log).pack(side="right")
        ttk.Button(sf, text="セットアップ", command=self._open_setup).pack(side="right", padx=(0, 4))
        # 状態は 1 行（下の段の高さを変えない）。長い失敗の文はログと失敗の窓に全文が出る
        self.status = tk.StringVar(value="MMD でキーを打ってから「生成」を押してください")
        ttk.Label(sf, textvariable=self.status, foreground="#335").pack(side="left", fill="x", expand=True)

        # ログは別の小さな窓（本体の並びを押し出さない）。× は隠すだけ
        self.log_win = tk.Toplevel(self.root)
        self.log_win.title("AIナカワリ のログ")
        self.log_win.withdraw()
        self.log_win.protocol("WM_DELETE_WINDOW", self.log_win.withdraw)
        # 困った時に送ってもらう記録（app.log・*_server.log）のある所を開く（README の「困った時は」）
        lf = ttk.Frame(self.log_win)
        lf.pack(side="bottom", fill="x", padx=4, pady=4)
        ttk.Button(lf, text="記録のフォルダを開く", command=lambda: os.startfile(paths.WORK_DIR)).pack(side="left")
        ttk.Label(lf, text="困った時は、このフォルダの app.log と、名前が _server.log で終わるファイルを GitHub の Issues に添えてください", foreground="#555").pack(
            side="left", padx=(8, 0))
        bar = ttk.Scrollbar(self.log_win, orient="vertical")
        bar.pack(side="right", fill="y")
        self.log = tk.Text(self.log_win, width=90, height=24, wrap="word", state="disabled", background="#f6f6f6",
                           yscrollcommand=bar.set)
        self.log.pack(fill="both", expand=True)
        bar.configure(command=self.log.yview)
        self._mode_changed()
        self.refresh_setup()

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
        """「Kimodo」タブ（プロンプトで作る）。"""
        # やりたいこと・長さ。行ごとに別の並びにする（表の列を共有すると、説明の長さが変わった時にボタンが横にずれる）
        def line(title, pady=(0, 0)):
            row = ttk.Frame(t)
            row.pack(fill="x", pady=pady)
            ttk.Label(row, text=title, width=10).pack(side="left")
            return row

        # Kimodo が入っていない時だけ、タブの一番上に出す（refresh_setup。MotionBricks のタブの nakawari_missing と同じ。11-06 マスター）
        self.kimodo_missing = ttk.Label(t, text="Kimodo がまだ入っていません。下の「セットアップ」で入れてください", foreground="#a33")
        mode_row = line("やりたいこと")
        self.kimodo_top = mode_row
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
        self.stop_check = ttk.Checkbutton(stop_row, text="最後のキーで止まる", variable=self.stop,
                                          command=self._stop_changed)
        self.stop_check.pack(side="left")
        # Kimodo だけだとキーの直前で急に止まるので、止まる所を MotionBricks で作り直す（smooth_stop.py）
        self.smooth = tk.BooleanVar(value=self.cfg["smooth_stop"] and smooth_stop.available())
        self.smooth_check = ttk.Checkbutton(stop_row, text="なめらかに止まる", variable=self.smooth)
        self.smooth_check.pack(side="left", padx=(12, 0))
        ttk.Separator(t).pack(fill="x", pady=(8, 6))

        # プロンプト（区間ごとの行）
        ttk.Label(t, text="プロンプト（英語。1 行が 1 区間の動き）").pack(anchor="w")
        self.prompt_rows = PromptRows(t)
        self.prompt_rows.pack(fill="x", pady=(4, 0))
        self.prompt_rows.load(self.cfg["prompt"])
        self.split_text = tk.StringVar(value="＋ 今のフレームで区切る")
        prompt_bar = ttk.Frame(t)
        prompt_bar.pack(anchor="w", pady=(4, 0))
        ttk.Button(prompt_bar, textvariable=self.split_text, command=self._split_here).pack(side="left")
        # 英語が苦手な人向けに「動作：英語」の一覧から選ぶ（MMD の右下のパネルと同じ一覧。11-05 マスター）
        sample_button = ttk.Button(prompt_bar, text="サンプルから選ぶ ▼")
        sample_button.configure(command=lambda: self._show_samples(sample_button))
        sample_button.pack(side="left", padx=(8, 0))

        details = Fold(t, "詳しい設定")
        details.pack(fill="x", pady=(8, 0))
        d, g = details.body, {"padx": 4, "pady": 2}
        ttk.Label(d, text="計算の回数（少ないほど速い）").grid(row=0, column=0, sticky="w", **g)
        self.steps = tk.IntVar(value=self.cfg["steps"])
        ttk.Spinbox(d, from_=10, to=100, increment=10, textvariable=self.steps, width=6).grid(row=0, column=1, sticky="w", **g)
        ttk.Label(d, text="seed（-1 で毎回違う動き）").grid(row=1, column=0, sticky="w", **g)
        self.seed = tk.IntVar(value=self.cfg["seed"])
        ttk.Entry(d, textvariable=self.seed, width=8).grid(row=1, column=1, sticky="w", **g)
        # Kimodo の CFG の重み。テキストを上げるとプロンプトの動きが強く出る（回転なら 8・1 で振り向くほど）
        ttk.Label(d, text="プロンプトの効き").grid(row=0, column=2, sticky="e", **g)
        self.cfg_text = tk.DoubleVar(value=self.cfg["cfg_text"])
        ttk.Spinbox(d, from_=0.5, to=10, increment=0.5, textvariable=self.cfg_text, width=5).grid(row=0, column=3, sticky="w", **g)
        ttk.Label(d, text="キーの効き").grid(row=1, column=2, sticky="e", **g)
        self.cfg_key = tk.DoubleVar(value=self.cfg["cfg_key"])
        ttk.Spinbox(d, from_=0.5, to=10, increment=0.5, textvariable=self.cfg_key, width=5).grid(row=1, column=3, sticky="w", **g)
        self.post = tk.BooleanVar(value=self.cfg["post_processing"])
        ttk.Checkbutton(d, text="生成した動きをキーに合わせる", variable=self.post).grid(row=2, column=0, columnspan=2, sticky="w", **g)
        # センターの上下などを毎フレームの腰の目印にする（リズムを残して動きを作る。プロンプトだけで作る時と組み合わせる想定）
        self.use_center = tk.BooleanVar(value=self.cfg["use_center"])
        ttk.Checkbutton(d, text="センターの動きを使う", variable=self.use_center).grid(row=2, column=2, columnspan=2, sticky="w", **g)
        # GPU 診断（この PC で足りるか）
        d = self.diagnosis
        bg = ttk.Style().lookup("TFrame", "background")
        if d.gpu:   # GPU の情報と判定は行を分ける（1 行にすると判定の途中で折り返していた）
            tk.Label(t, text=d.summary(), foreground="#556", background=bg, anchor="w").pack(fill="x", pady=(8, 0))
        # 足りない・GPU が無い時は赤で目立たせる（普段の説明と同じ灰色だと読み飛ばす）
        tk.Label(t, text=("→ " if d.gpu else "") + d.note, foreground="#556" if d.ok else "#c22", background=bg,
                 wraplength=500, anchor="w", justify="left").pack(fill="x", pady=(0 if d.gpu else 8, 0))

    def _build_nakawari(self, t):
        """「MotionBricks」タブ（プロンプト無しの中割り）。"""
        tk.Label(t, text=NAKAWARI_NOTE, foreground="#556", background=ttk.Style().lookup("TFrame", "background"),
                 wraplength=500, anchor="w", justify="left").pack(fill="x")
        self.key_stop = tk.BooleanVar(value=self.cfg["key_stop"])
        self.wrist_lerp = tk.BooleanVar(value=self.cfg["wrist_lerp"])
        self.nakawari_checks = [
            ttk.Checkbutton(t, text="キーごとに止まる（外すと、勢いを保って通る）", variable=self.key_stop),
            ttk.Checkbutton(t, text="手首は MMD の補間にする（回りすぎを抑える）", variable=self.wrist_lerp),
        ]
        self.nakawari_checks[0].pack(anchor="w", pady=(10, 0))
        self.nakawari_checks[1].pack(anchor="w", pady=(4, 0))
        self.nakawari_missing = ttk.Label(t, text="MotionBricks がまだ入っていません。下の「セットアップ」で入れてください", foreground="#a33")

    def _open_setup(self):
        setup_window.open_window(self.hub.root, self.diagnosis, on_done=self.refresh_setup)

    def refresh_setup(self):
        """入っている物（Kimodo・MotionBricks）に合わせて、窓の部品と状態の 1 行を出し直す。作った時と、セットアップが済んだ時に呼ぶ。"""
        mb = smooth_stop.available()
        for check in self.nakawari_checks:
            check.configure(state="normal" if mb else "disabled")
        if mb:
            self.nakawari_missing.pack_forget()
        else:
            self.nakawari_missing.pack(anchor="w", pady=(10, 0))
        if mb and self.cfg["smooth_stop"]:
            self.smooth.set(True)
        self._stop_changed()
        try:
            paths.kimodo_dir()
            self.kimodo_ready = True
        except paths.NotSetUp:
            self.kimodo_ready = False   # パネルの状態の 1 行も赤い案内にする（_sync_panel）
            self.kimodo_missing.pack(anchor="w", pady=(0, 8), before=self.kimodo_top)
            self.status.set("AI のモデルがまだ入っていません。下の「セットアップ」で入れてください")
            return
        self.kimodo_missing.pack_forget()
        if self.status.get().startswith("AI のモデルがまだ入っていません"):
            self.status.set("MMD でキーを打ってから「生成」を押してください")

    def _mode_changed(self):
        mode = self.mode.get()
        self.mode_note.set(MODE_NOTES[mode])
        if self.range_mode.get() == "keys":
            self.length_entry.configure(state="disabled")
            self.length_note.set("F（範囲の終わりまで）")
        elif mode == "fill":
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

    def _show_samples(self, button):
        """「サンプルから選ぶ」: 種類ごとの「動作：英語」の一覧を出し、選んだ英語の文を最後に打っていた行に入れる。
        一覧は押すたびに読む（prompt_samples.txt を書き換えればすぐ反映される）。"""
        try:
            groups = samples.load()
        except OSError as e:
            messagebox.showerror("AIナカワリ", f"サンプルの一覧が読めません: {e}", parent=self.root)
            return
        if getattr(self, "_sample_menu", None) is not None:   # 前に開いた一覧は消す（開くたびに増えていた。11-05 Codex のレビュー）
            self._sample_menu.destroy()
        menu = self._sample_menu = tk.Menu(self.root, tearoff=0)
        for name, items in groups:
            sub = tk.Menu(menu, tearoff=0) if name else menu
            for label, prompt in items:
                sub.add_command(label=f"{label}：{prompt}", command=lambda p=prompt: self.prompt_rows.set_current(p))
            if name:
                menu.add_cascade(label=name, menu=sub)
        menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())

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
        """MMD の選択中のモデル・今のフレーム・選んだキーを読んで表示する（1 秒ごと）。生成中は MMD を操作しているので読みに行かない。"""
        self._model_ticks += 1
        if self.busy or self._model_ticks % 2:
            return
        frame = model = None
        try:
            model = self.link.selected_model()
            frame = self.link.current_frame()
        except Exception as e:  # 読めない理由をそのまま出す（MMD の版が違う・選び替えの途中など）
            text = f"選択中のモデル：（読み取れません: {e}）"
        else:
            text = f"選択中のモデル：{model['name']}" if model else "選択中のモデル：（なし。MMD のモデル欄でモデルを選んでください）"
        try:
            keys = self.link.selected_key_frames() if model else []
            picked = (f"選んだキーの間（{keys[0]}〜{keys[-1]}F）" if len(keys) > 1 else
                      f"選んだキーの間（{keys[0]}F だけ。2 つ以上選んでください）" if keys else "選んだキーの間（キーを選んでいません）")
            self.selected_keys = keys
        except Exception:   # 選び替えの途中などで鎖が読めない時は、次の読み取りで直る
            picked = "選んだキーの間（読み取れません）"
            self.selected_keys = None
        updates = [(self.model_text, text),
                   (self.split_text, f"＋ 今のフレーム（{frame}F）で区切る" if frame is not None else "＋ 今のフレームで区切る"),
                   (self.range_text, picked)]
        for var, value in updates:
            if var.get() != value:
                var.set(value)

    def _write_log(self, line):
        applog.write(line)
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _tick(self):
        if not win32gui.IsWindow(self.mmd.hwnd):  # MMD が閉じたら、その MMD の分は一緒に終わる
            self.close()
            return
        # 次の予約は先に入れる（途中で例外が出ると、パネルとの同期も表示の更新も止まっていた。11-05 Codex のレビュー）
        self.root.after(500, self._tick)
        scene =win32gui.GetWindowText(self.mmd.hwnd).partition("[")[2].rstrip("]")
        title = f"AIナカワリ - {os.path.basename(scene)}" if scene else "AIナカワリ"
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
                    messagebox.showerror("AIナカワリ", msg, parent=self.root)
        # 生成できない時は、押してからエラーにせず、押せなくして下の 1 行で知らせる。
        # GPU が無い時はどちらのタブも（MotionBricks も GPU が要る）
        # 「選んだキーの間」でキーを 2 つ以上選んでいない時も（11-05 マスター。選んでいない時に全部を作り直さないように）
        block = None
        keys = self.selected_keys
        if not self.diagnosis.usable:
            block = self.diagnosis.note
        elif self.range_mode.get() == "keys" and keys is None and not self.busy:   # 読めない時も止める（11-05 Codex のレビュー）
            block = "選んだキーを読めません。MMD の操作を終えてから選び直してください"
        elif self.range_mode.get() == "keys" and keys is not None and len(keys) < 2 and not self.busy:
            block = "範囲の最初と最後のキーを選んでください"   # パネルの 1 行に収まる長さ
        if block and self._status_before is not None and self.status.get() != block:   # 止める理由が変わった
            self.status.set(block)
        if block and self._status_before is None:
            self._status_before = self.status.get()
            self.status.set(block)
        elif not block and self._status_before is not None:
            self.status.set(self._status_before)
            self._status_before = None
        self.gen_btn.configure(state="disabled" if self.busy or block else "normal")
        self.undo_btn.configure(state="normal" if (self.last_backup and not self.busy) else "disabled")
        self._sync_panel()

    # ---------------- MMD の右下のパネル ----------------

    def _sync_panel(self):
        """パネルと窓の設定をそろえる。入力（プロンプト・Kimodo か MotionBricks か）は変わった方からもう一方へ、
        表示（状態の 1 行・範囲の字・ボタンの押せる押せない）は窓からパネルへ。そろえられたら True（パネルが無い時も）。"""
        p = self.panel
        before = p.hwnd
        if not p.find():
            return True   # パネルが無い（隠れているのとは別。プラグインが古い等）。そろえる物が無い
        if p.hwnd != before:   # 新しいパネル（MMD を起動し直した等）。中身を全部写し直す
            self._seen = {}
        seen = self._seen

        def window_prompt():
            try:
                return self.prompt_rows.text()
            except ValueError:   # 区間のフレームが数字でない・重なる（打っている途中か、パネルで重ねて書いた）
                return None

        try:
            # プロンプト: パネルで変えた → 窓へ（窓の区間がおかしい時も、パネルで直せば写るように）。窓で変えた → パネルへ。
            # パネルへ書いた時は、読み返した値でなく書いた値を覚える（書いた直後に打った分を、次に「パネルで変えた」と分かるように。
            # 読み返した値を覚えると、その分は窓に写らないままだった。11-05 Codex のレビュー）
            # 書いた値は、パネルから読んだ時と同じ形にそろえて覚える（空の区間「45: 」はパネルを通ると「45:」になるので、
            # 窓の形のまま覚えると、次に「パネルで変えた」と思って窓の直しを巻き戻していた。11-05 Codex のレビュー 2 回目）
            got = panel.lines_of(p.text(panel.PROMPT))
            mine = window_prompt()
            if ("panel", "prompt") not in seen:   # 最初（パネルを作り直した時も）は窓の設定をパネルへ
                if mine is not None:
                    p.set_text(panel.PROMPT, panel.one_line(mine))
                    got = panel.lines_of(panel.one_line(mine))
            elif got != seen[("panel", "prompt")]:
                if got != mine:
                    self.prompt_rows.load(got)
                    mine = window_prompt()
            elif mine is not None and mine != seen.get(("window", "prompt")):
                p.set_text(panel.PROMPT, panel.one_line(mine))
                got = panel.lines_of(panel.one_line(mine))
            seen[("panel", "prompt")], seen[("window", "prompt")] = got, mine
            # Kimodo か MotionBricks か（窓のタブ）
            got, mine = p.selection(panel.ENGINE), self.tabs.index("current")
            if ("panel", "engine") not in seen or (got == seen[("panel", "engine")] and mine != seen[("window", "engine")]):
                p.select(panel.ENGINE, mine)
                got = mine
            elif got != seen[("panel", "engine")] and got != mine:
                self.tabs.select(1 if got == 1 else 0)
                mine = self.tabs.index("current")
            seen[("panel", "engine")], seen[("window", "engine")] = got, mine
            # 範囲はパネルでは切り替えない（11-05 マスター。チェックを外した）。窓の設定と、選んでいるキーを字で出す
            keys = self.selected_keys
            if self.range_mode.get() != "keys":
                range_text = "全部のキー"
            elif keys is None:
                range_text = "選んだキー（読めません）"
            else:
                range_text = (f"選んだキー {keys[0]}〜{keys[-1]}F" if len(keys) > 1 else
                              f"選んだキー {keys[0]}F だけ" if keys else "キーを選んでいません")
            # AI のモデル（Kimodo）が入っていない時は、状態の 1 行を赤い案内にする（11-06 マスター）
            missing = not self.kimodo_ready
            shown = {
                panel.RANGE: range_text,
                panel.STATUS: "詳細の窓で「セットアップ」を押してください" if missing else self.status.get(),
            }
            for item, text in shown.items():
                if self._seen.get(("text", item)) != text:
                    p.set_text(item, text)
                    self._seen[("text", item)] = text
            if self._seen.get("alert") != missing:
                p.alert(missing)
                self._seen["alert"] = missing
            states = {panel.GENERATE: str(self.gen_btn.cget("state")) == "normal",
                      panel.UNDO: str(self.undo_btn.cget("state")) == "normal",
                      # 中割りはプロンプトを使わないので、欄を灰色にする（字は消さない。11-05 マスター）
                      panel.PROMPT: self.tabs.index("current") == 0,
                      panel.SAMPLES: self.tabs.index("current") == 0}
            for item, on in states.items():
                if self._seen.get(("enabled", item)) != on:
                    p.enable(item, on)
                    self._seen[("enabled", item)] = on
        except (panel.Busy, win32gui.error):   # MMD が忙しい・パネルがちょうど消えた。次にまた
            return False
        return True

    def panel_pressed(self, button):
        """パネルの「生成」「元に戻す」。押す前に、パネルで打った途中のプロンプトなどを窓に写す。"""
        if not self._sync_panel():   # 写せないまま進むと、窓に残った古いプロンプトで作っていた（11-05 Codex のレビュー）
            self.status.set("MMD が応答しませんでした。もう一度押してください")
            return
        if button == panel.GENERATE and str(self.gen_btn.cget("state")) == "normal":
            self._generate(fill=True)
        elif button == panel.UNDO and str(self.undo_btn.cget("state")) == "normal":
            self._undo()

    # ---------------- 操作 ----------------

    def _settings(self, fill=False):
        """窓の設定から runner.Settings を作り、設定を保存する。

        fill: MMD の右下のパネルから。やりたいことは窓の選び方にかかわらず「キーの間を埋める」（11-05 マスター。
        パネルにはやりたいことが出ないので、窓で「プロンプトだけで作る」にしたのを忘れて、キーを通らないのに戸惑わないように）。
        窓の選び方（やりたいこと・長さ）は保存し直さない。seed・効き・止まり方などは窓の値を使う。
        """
        def opt_int(s):
            s = s.strip()
            return int(s) if s else None
        tab = TABS[self.tabs.index("current")][0]
        mode = "fill" if fill else self.mode.get()
        nakawari = tab == "nakawari"
        in_range = self.range_mode.get() == "keys"   # 範囲を使う時は範囲の終わりまで作るので、長さは使わない
        length = opt_int(self.length.get()) if mode != "fill" and not nakawari and not in_range else None
        if nakawari and not smooth_stop.available():
            raise ValueError("MotionBricks がまだ入っていません。詳細の窓の下の「セットアップ」で入れてください")
        if not nakawari and mode != "fill" and length is None and not in_range:
            raise ValueError("「続きを足す」「プロンプトだけで作る」では長さを入れてください")
        selection = None
        if in_range:
            # 選んだキーの最初から最後までを作り直す（どのボーンのキーでも。範囲の中のキーは選んでいなくても通る）
            keys = self.link.selected_key_frames()
            if len(keys) < 2:
                raise ValueError("MMD のタイムラインで、作り直す範囲の最初と最後のキーを選んでください（2 つ以上のフレーム）")
            selection = (keys[0], keys[-1])
        common = dict(range_start=selection[0] if selection else None, range_end=selection[1] if selection else None,
                      key_stop=bool(self.key_stop.get()), wrist_lerp=bool(self.wrist_lerp.get()))
        self.cfg.update(tab=tab, range_mode=self.range_mode.get(), key_stop=common["key_stop"], wrist_lerp=common["wrist_lerp"])
        if nakawari:
            # 中割りは、隠れている「Kimodo」タブの欄を読まない（入力の途中や誤りで中割りが止まっていた。11-04 Codex のレビュー）
            s = runner.Settings(prompt="", engine="motionbricks", **common)
        else:
            s = runner.Settings(prompt=self.prompt_rows.text(),
                                steps=int(self.steps.get()), seed=int(self.seed.get()), post_processing=bool(self.post.get()),
                                cfg_text=float(self.cfg_text.get()), cfg_key=float(self.cfg_key.get()),
                                length=length, use_keys=mode != "fresh", use_center=bool(self.use_center.get()),
                                stop_at_last_key=mode != "fresh" and bool(self.stop.get()),
                                smooth_stop=bool(self.smooth.get()) and smooth_stop.available(), engine="kimodo", **common)
            self.cfg.update(mode=self.mode.get(), length=self.length.get(), prompt=s.prompt, steps=s.steps, seed=s.seed,
                            post_processing=s.post_processing, cfg_text=s.cfg_text, cfg_key=s.cfg_key,
                            use_center=bool(self.use_center.get()), stop_at_last_key=bool(self.stop.get()),
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
            except Exception as e:  # 窓に出して止める（握りつぶさない）。どこで落ちたかは記録にだけ書く
                applog.exception("失敗した時の traceback:")
                try:   # 読み込みで止まった時も「元に戻す」で戻せるように、読み込みの前に残した記録を読み直す（11-07 Codex のレビュー）
                    r = runner.load_last_run(self.link)
                    if r:
                        self.last_run, self.last_backup = r, r["backup"]
                except Exception:   # MMD が閉じられたなど。失敗の知らせはそのまま出す
                    applog.exception("失敗の後の前回の記録の読み直し:")
                self.q.put(("log", f"失敗: {e}"))
                self.q.put(("done", (False, f"失敗: {e}")))
        threading.Thread(target=work, daemon=True).start()

    def _generate(self, fill=False):
        try:
            s = self._settings(fill=fill)
        except (ValueError, RuntimeError) as e:
            messagebox.showerror("AIナカワリ", str(e), parent=self.root)
            return
        except tk.TclError:   # 数字の欄（計算の回数・seed・効き）に数字でないものが入っている
            messagebox.showerror("AIナカワリ", "「詳しい設定」の計算の回数・seed・効きには数字を入れてください", parent=self.root)
            return
        self._write_log("―" * 20)
        self.status.set("生成中…")
        previous = self.last_run
        self._run(lambda log: runner.generate(s, log, link=self.link, previous=previous),
                  "できました。MMD で再生して確かめてください")

    def _undo(self):
        backup = self.last_backup
        model = (self.last_run or {}).get("model")   # バックアップを取ったモデル（違うモデルが選ばれていたら止める）
        self.status.set("元に戻し中…")
        self._run(lambda log: runner.undo(backup, log, link=self.link, model=model), "生成前のモーションに戻しました")


def _notify_running(hwnd, message=OPEN_MESSAGE):
    """もう動いている AIナカワリ に「この MMD の窓を開いて」（隠したまま作って）と知らせる。起動直後で目印がまだ無ければ少し待つ。"""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        hub = win32gui.FindWindowEx(win32con.HWND_MESSAGE, 0, HUB_CLASS, None)
        if hub:
            win32gui.PostMessage(hub, register_message(message), hwnd, 0)
            return True
        time.sleep(0.1)
    return False


ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MMD-AINakawari.ico")   # tools/make_icon.py が描く
APP_ID = "BeamManP.MMD-AINakawari"   # タスクバーで、pythonw.exe ではなく AIナカワリ としてまとめる名乗り


def _new_root():
    """tk の親の窓を作り、全部の窓（MMD ごとの窓・セットアップ・ログ・知らせの窓）の既定のアイコンを AIナカワリ にする。
    前は tkinter の既定の羽根だった（11-06 マスター）。"""
    root = tk.Tk()
    root.iconbitmap(default=ICON)
    return root


def main():
    ap = argparse.ArgumentParser(description="AIナカワリ の窓（ふつうは MMD のメニューから開く）")
    ap.add_argument("--open", type=int, help="窓を開く MMD の窓（省くと一番手前の MMD）")
    ap.add_argument("--attach", type=int, help="窓を隠したまま作る MMD の窓（MMD の起動時にプラグインが、右下のパネル用に渡す）")
    args = ap.parse_args()
    # 窓を作る前に名乗る（タスクバーのアイコンが Python の物でなく、窓のアイコンになる）
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    show = args.attach is None
    hwnd = args.open or args.attach or front_mmd()
    if not hwnd:
        root = _new_root()
        root.withdraw()
        messagebox.showerror("AIナカワリ", "MMD が起動していません。MMD を起動してから開いてください")
        root.destroy()
        return
    mutex = win32event.CreateMutex(None, False, APP_MUTEX)  # 終わるまで持っておく
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        if not _notify_running(hwnd, OPEN_MESSAGE if show else ATTACH_MESSAGE) and show:
            root = _new_root()
            root.withdraw()
            messagebox.showerror("AIナカワリ", "AIナカワリ の起動がまだ終わっていません。少し待ってから、もう一度開いてください")
            root.destroy()
        return
    applog.setup()   # mutex を取ってから（記録を書くのは 1 つのプロセスだけ）
    root = _new_root()
    applog.hook_tk(root)
    root.withdraw()  # 親の窓は見せない。MMD ごとの窓（Toplevel）だけ出す
    hub = Hub(root)
    try:
        hub.open(hwnd, show=show)
        if hub.alive:
            root.mainloop()
    finally:
        hub.close()
        del mutex


if __name__ == "__main__":
    main()
