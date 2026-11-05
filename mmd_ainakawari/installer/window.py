"""セットアップの画面（詳細の窓の「セットアップ」）。入れる場所を選んで、ボタン一つで steps.Setup を裏で回す。

窓はプロセスに 1 つだけ（SetupWindow.current）。持ち主は Hub の見えない親の窓なので、MMD を閉じても消えない。
この窓が出ている間（裏で回っている間も）は Hub が終わらない（app.py の Hub._finish が is_open() を見る）。
途中で止まっても、もう一度押せば続きから進む。
"""
import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from .. import applog, paths
from . import steps

LICENSES = [
    ("Meta Llama 3 Community License（文の読み取りに使う Llama 3）",
     "https://huggingface.co/NousResearch/Meta-Llama-3-8B-Instruct/blob/main/LICENSE"),
    ("Llama 3 の使い方の決まり（Acceptable Use Policy）",
     "https://huggingface.co/NousResearch/Meta-Llama-3-8B-Instruct/blob/main/USE_POLICY.md"),
    ("NVIDIA Open Model License（Kimodo のモデル）", "https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2"),
    ("NVIDIA Open Model Agreement（MotionBricks のモデル）", "https://github.com/NVlabs/motionbricks"),
]
MARKS = {"todo": "・", "skip": "✓", "done": "✓", "run": "▶", "fail": "✗"}
COLORS = {"todo": "#888", "skip": "#2a7", "done": "#2a7", "run": "#15c", "fail": "#c33"}


def is_open():
    """セットアップの窓が出ているか（回っている間も含む）。Hub は、これが閉じるまでプロセスを終わらせない。"""
    return SetupWindow.current is not None


def open_window(root, diagnosis=None, on_done=None):
    """セットアップの窓を出す（もう出ていれば手前に）。on_done(): セットアップが最後まで済んだ時（窓の印の作り直し）。"""
    if SetupWindow.current is None:
        SetupWindow.current = SetupWindow(root, diagnosis)
    window = SetupWindow.current
    if on_done is not None and on_done not in window.on_done:
        window.on_done.append(on_done)
    window.win.deiconify()
    window.win.lift()
    window.win.focus_force()
    return window


class SetupWindow:
    current = None

    def __init__(self, root, diagnosis):
        self.root = root
        self.on_done = []
        self.thread = None
        self.setup = None
        self.q = queue.Queue()
        win = self.win = tk.Toplevel(root)
        win.title("AIナカワリ のセットアップ")
        win.protocol("WM_DELETE_WINDOW", self.close)
        f = ttk.Frame(win, padding=12)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="AI のモデル（Kimodo・MotionBricks）と、それを動かす Python をまとめて入れます。\n"
                          "git や Python を自分で入れる必要はありません。Hugging Face のアカウントも要りません。",
                  justify="left").pack(anchor="w")

        # 入れる場所と空き
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text="入れる場所").pack(side="left")
        self.dest = tk.StringVar(value=self._initial_folder())
        entry = ttk.Entry(row, textvariable=self.dest, width=44)
        entry.pack(side="left", padx=(8, 4), fill="x", expand=True)
        ttk.Button(row, text="選ぶ…", command=self._browse).pack(side="left")
        self.space = tk.StringVar()
        ttk.Label(f, textvariable=self.space, foreground="#555").pack(anchor="w", pady=(2, 0))
        if diagnosis is not None:
            ttk.Label(f, text=f"この PC: {diagnosis.summary()} → {diagnosis.note}", foreground="#555").pack(anchor="w", pady=(6, 0))
        self.dest.trace_add("write", lambda *_a: self._refresh())

        # 規約
        lf = ttk.LabelFrame(f, text="ライセンス（入れる前に読んでください）", padding=8)
        lf.pack(fill="x", pady=(10, 0))
        for text, url in LICENSES:
            link = tk.Label(lf, text=text, foreground="#15c", cursor="hand2", anchor="w")
            link.pack(anchor="w")
            link.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
        self.agree = tk.BooleanVar(value=False)
        ttk.Checkbutton(lf, text="上のライセンスに同意して入れます（Llama 3 で作った物を公開する時は「Built with Meta Llama 3」の表示が要ります）",
                        variable=self.agree, command=self._refresh).pack(anchor="w", pady=(6, 0))

        # 段の一覧
        self.step_box = ttk.Frame(f)
        self.step_box.pack(fill="x", pady=(10, 0))
        self.step_labels = {}
        self.progress = tk.StringVar()
        ttk.Label(f, textvariable=self.progress, foreground="#15c").pack(anchor="w", pady=(6, 0))

        # ログ（後から送ってもらえるように、記録 work\app.log にも書く）
        lg = ttk.Frame(f)
        lg.pack(fill="both", expand=True, pady=(6, 0))
        bar = ttk.Scrollbar(lg, orient="vertical")
        bar.pack(side="right", fill="y")
        self.log = tk.Text(lg, height=10, width=96, wrap="word", state="disabled", background="#f6f6f6", yscrollcommand=bar.set)
        self.log.pack(fill="both", expand=True)
        bar.configure(command=self.log.yview)

        bf = ttk.Frame(f)
        bf.pack(fill="x", pady=(8, 0))
        self.start_btn = ttk.Button(bf, text="セットアップを始める", command=self._start)
        self.start_btn.pack(side="left", ipady=4)
        self.cancel_btn = ttk.Button(bf, text="中止", command=self._cancel, state="disabled")
        self.cancel_btn.pack(side="left", padx=(6, 0), ipady=4)
        ttk.Button(bf, text="閉じる", command=self.close).pack(side="right", ipady=4)
        self.status = tk.StringVar()
        ttk.Label(f, textvariable=self.status, wraplength=640, justify="left").pack(anchor="w", pady=(6, 0))
        self._refresh()
        self._poll()

    # ---- 表示 ----
    def _initial_folder(self):
        """前に入れた場所（paths.json の Kimodo の 1 つ上）があればそこ。無ければ空きのいちばん多いドライブ。"""
        try:
            kimodo = paths.load().get("kimodo")
        except paths.NotSetUp:
            kimodo = None
        if kimodo and os.path.basename(kimodo.rstrip("\\")).lower() == "kimodo" and \
                os.path.isfile(os.path.join(os.path.dirname(kimodo.rstrip("\\")), steps.STATE_FILE)):
            return os.path.dirname(kimodo.rstrip("\\"))
        return steps.default_folder()

    def _browse(self):
        folder = filedialog.askdirectory(parent=self.win, title="入れる場所（半角の英数字だけのフォルダ）")
        if folder:
            self.dest.set(os.path.normpath(folder))

    def _make_setup(self):
        return steps.Setup(self.dest.get().strip(), log=lambda line: self.q.put(("log", line)),
                           progress=lambda text: self.q.put(("progress", text)),
                           on_step=lambda key, state: self.q.put(("step", (key, state))))

    def _refresh(self):
        """入れる場所・同意が変わった時: 空きと段の一覧を出し直し、始めるボタンの可否を決める。"""
        if self.thread is not None:
            return
        try:
            setup = self._make_setup()
        except steps.Failed as e:
            self.space.set(str(e).splitlines()[0])
            self._show_steps([])
            self.start_btn.configure(state="disabled")
            return
        state = setup.load_state()
        listed = [(key, title, "skip" if state.get(key) == version else "todo") for key, _g, title, version, _gb, _fn in setup.steps()]
        self._show_steps(listed)
        need = setup.remaining_gb()
        try:
            free = f"{steps.free_gb(setup.dest):.0f}GB"
        except OSError:
            free = "（読めません）"
        done = sum(1 for _k, _t, mark in listed if mark == "skip")
        self.space.set(f"空き {free}／これから使う量 約 {need:.0f}GB" + (f"（済んだ段 {done} 個の分は除く）" if done else ""))
        self.start_btn.configure(text="続きから始める" if done else "セットアップを始める",
                                 state="normal" if self.agree.get() else "disabled")

    def _show_steps(self, listed):
        for child in self.step_box.winfo_children():
            child.destroy()
        self.step_labels = {}
        for key, title, mark in listed:
            label = tk.Label(self.step_box, text=f"{MARKS[mark]} {title}", foreground=COLORS[mark], anchor="w")
            label.pack(anchor="w")
            self.step_labels[key] = (label, title)

    def _write_log(self, line):
        applog.write(f"[セットアップ] {line}")
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # ---- 動かす ----
    def _start(self):
        try:
            setup = self._make_setup()
        except steps.Failed as e:
            messagebox.showerror("AIナカワリ のセットアップ", str(e), parent=self.win)
            return
        if not self.agree.get():
            return
        self.setup = setup
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.status.set("入れています（落とす量は約 20GB）。この窓は閉じても裏で進みます")

        def work():
            try:
                setup.run()
                self.q.put(("end", None))
            except steps.Cancelled:
                self.q.put(("end", "中止しました。もう一度押すと続きから進みます"))
            except steps.Failed as e:
                self.q.put(("end", f"止まりました: {e}\nもう一度押すと、止まった段から進みます"))
            except Exception as e:   # 思っていない失敗。記録に traceback を残して、画面には一言
                applog.exception("セットアップの思っていない失敗:")
                self.q.put(("end", f"止まりました（思っていない失敗: {e}）。ログの「記録のフォルダを開く」の app.log を送ってください"))
        self.thread = threading.Thread(target=work, name="セットアップ", daemon=True)
        self.thread.start()

    def _cancel(self):
        if self.setup is not None and messagebox.askyesno("AIナカワリ のセットアップ", "中止しますか？（済んだ段はそのまま残ります）",
                                                          parent=self.win):
            self.cancel_btn.configure(state="disabled")
            self.status.set("止めています…")
            threading.Thread(target=self.setup.cancel, daemon=True).start()

    def _poll(self):
        try:
            self._drain()
        finally:   # 1 つの処理が例外になっても、次の更新は止めない（例外は tk が記録に回す。applog.hook_tk）
            if self.win.winfo_exists():
                self.win.after(100, self._poll)

    def _drain(self):
        try:
            while True:
                kind, value = self.q.get_nowait()
                if kind == "log":
                    self._write_log(value)
                elif kind == "progress":
                    self.progress.set(value)
                elif kind == "step":
                    key, mark = value
                    if key in self.step_labels:
                        label, title = self.step_labels[key]
                        label.configure(text=f"{MARKS[mark]} {title}", foreground=COLORS[mark])
                elif kind == "end":
                    self._finished(value)
        except queue.Empty:
            pass

    def _finished(self, error):
        self.thread = None
        self.setup = None
        self.cancel_btn.configure(state="disabled")
        self.progress.set("")
        self._refresh()
        if error:
            self.status.set(error)
            self._write_log(error)
            self.win.deiconify()
            return
        self.status.set("できました。詳細の窓の「生成」で使えます")
        for callback in self.on_done:
            try:
                callback()
            except Exception:   # 閉じた MMD の窓など。セットアップは済んでいる
                applog.exception("セットアップ後の窓の更新の失敗:")
        self.win.deiconify()
        messagebox.showinfo("AIナカワリ のセットアップ", "できました。詳細の窓の「生成」で使えます", parent=self.win)

    def close(self):
        if self.thread is not None:
            self.win.withdraw()   # 裏で進める（もう一度「セットアップ」を押すと出る）
            return
        self.win.destroy()
        SetupWindow.current = None
