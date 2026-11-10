"""セットアップの画面（詳細の窓の「セットアップ」）。入れる場所を選んで、ボタン一つで steps.Setup を裏で回す。

窓はプロセスに 1 つだけ（SetupWindow.current）。持ち主は Hub の見えない親の窓なので、MMD を閉じても消えない。
この窓が出ている間（裏で回っている間も）は Hub が終わらない（app.py の Hub._finish が is_open() を見る）。
途中で止まっても、もう一度押せば続きから進む。

開いた時に、入れる場所の状態（steps.Setup.status）を見出しにする（11-07 マスター「既に環境入ってるのにセットアップできるってのが違和感」）:
まだ／途中で止まっている／更新がある → 入れる場所・ライセンス・段の一覧とボタンを出す。
全部済んでいる・手で入れた場所を使っている → それらは畳んで「別の場所に入れる…」だけを出す。
"""
import os
import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from .. import applog, paths
from . import pins, steps

_GGUF = f"https://huggingface.co/{pins.TEXT_GGUF_REPO}/blob/{pins.TEXT_GGUF_REVISION}"
LICENSES = [   # 文の読み取りは、落とす GGUF のリポジトリに付いている文（版で固定）を見せる
    ("Meta Llama 3 Community License（プロンプトの読み取りに使う Llama 3）", f"{_GGUF}/LICENSE-Llama-3.txt"),
    ("Llama 3 の使い方の決まり（Acceptable Use Policy）", f"{_GGUF}/USE_POLICY-Llama-3.md"),
    ("NVIDIA Open Model License（Kimodo のモデル）", "https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2"),
    ("NVIDIA Open Model Agreement（MotionBricks のモデル）", "https://github.com/NVlabs/motionbricks"),
    ("MIT（プロンプトの読み取りを動かす llama.cpp）", "https://github.com/ggml-org/llama.cpp/blob/master/LICENSE"),
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

        if diagnosis is not None:
            self._show_environment(f, diagnosis)
        # 見出し（この場所の状態）と、その説明
        self.headline = tk.StringVar()
        self.subline = tk.StringVar()
        ttk.Label(f, textvariable=self.headline, font=("", 11, "bold")).pack(anchor="w", pady=(10 if diagnosis is not None else 0, 0))
        ttk.Label(f, textvariable=self.subline, foreground="#444", wraplength=680, justify="left").pack(anchor="w", pady=(2, 0))
        self.more_btn = ttk.Button(f, text="別の場所に入れる…", command=self._expand)
        self.manual = self._manual_place()   # 手で入れた場所（セットアップの印が無い）を使っている時、その Kimodo の場所
        self.expanded = False                # 済んでいる時も、入れる場所などを出している（「別の場所に入れる…」・回した後）

        # ここから下（入れる場所〜ボタン）は、済んでいる時は畳む
        form = self.form = ttk.Frame(f)
        form.pack(fill="both", expand=True)
        f, outer = form, f

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
        self.dest.trace_add("write", lambda *_a: self._refresh())

        # 規約
        lf = ttk.LabelFrame(f, text="ライセンス（入れる前に読んでください）", padding=8)
        lf.pack(fill="x", pady=(10, 0))
        for text, url in LICENSES:
            link = tk.Label(lf, text=text, foreground="#15c", cursor="hand2", anchor="w")
            link.pack(anchor="w")
            link.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
        self.agree = tk.BooleanVar(value=False)
        ttk.Checkbutton(lf, text="上のライセンスに同意して入れます",
                        variable=self.agree, command=self._refresh).pack(anchor="w", pady=(6, 0))
        ttk.Label(lf, text="Llama 3 で作った物を公開する時は、「Built with Meta Llama 3」の表示が要ります",
                  foreground="#555").pack(anchor="w", padx=(22, 0))

        # プロンプトの読み取り（Llama 3）を入れるか（11-10 マスター）。外すとサンプルの文だけで作る（読み取り結果を同梱している）。
        # 入れ終わった後に足せる・外せるように、畳む欄（form）の外の、見出しのすぐ下に置く
        self.with_text = tk.BooleanVar(value=True)
        self._text_dest = None   # with_text をどの場所の印から読んだか（場所を変えたら、その場所で前に選んだ方に戻す）
        box = self.text_box = ttk.Frame(outer)
        box.pack(fill="x", before=self.form)
        ttk.Checkbutton(box, text="プロンプトを自由に書けるようにする（Llama 3 を入れる・約 8GB・生成中にメインメモリを約 8GB 使う）",
                        variable=self.with_text, command=self._refresh).pack(anchor="w", pady=(10, 0))
        ttk.Label(box, text="外すと「サンプルから選ぶ」の文だけで作ります（メインメモリの少ない PC 向け）。後からここで入れたり外したりできます",
                  foreground="#555").pack(anchor="w", padx=(22, 0))

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
        bottom = ttk.Frame(outer)
        bottom.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(bottom, text="閉じる", command=self.close).pack(side="right", ipady=4)
        self.status = tk.StringVar()
        ttk.Label(bottom, textvariable=self.status, wraplength=560, justify="left").pack(side="left", anchor="w")
        self._refresh()
        self._poll()

    # ---- 表示 ----
    @staticmethod
    def _show_environment(f, d):
        """一番上の「現在の環境: GPU・メインメモリ → MotionBricks ○ Kimodo ○」（11-06 マスター。11-07 に動作モードの 2 つを 1 つに）。
        使える物は緑の ○、使えない物は赤の ×。GPU を調べられなかった時は、どれも橙の ？（試せる。gpu.diagnose）。
        赤がある時は、理由（gpu.diagnose の一言）を下に小さく出す。"""
        no_gpu = d.backend == "cpu" and not d.gpu   # GPU を使わずに作る（遅いが動く。11-10）
        unknown = not d.gpu and d.ok and not no_gpu
        row = ttk.Frame(f)
        row.pack(anchor="w", fill="x")
        missing = "GPU なし" if no_gpu else "GPU を調べられませんでした" if unknown else "NVIDIA の GPU が見つかりません"
        hardware = d.summary() if d.gpu else f"{missing}・メインメモリ {d.ram_gb:.0f}GB"
        ttk.Label(row, text=f"現在の環境：{hardware}　→").pack(side="left")
        marks = [("MotionBricks", bool(d.gpu) or no_gpu), ("Kimodo", d.ok and (bool(d.gpu) or no_gpu))]
        for name, ok in marks:
            mark, color = ("？", "#c70") if unknown else ("○", "#2a7") if ok else ("×", "#c33")
            tk.Label(row, text=f"{name} {mark}", foreground=color, font=("", 9, "bold"),
                     background=ttk.Style().lookup("TFrame", "background")).pack(side="left", padx=(8, 0))
        # CUDA 以外（DirectML・GPU なし）は、どう動かすかの一言も出す
        if unknown or d.backend != "cuda" or not all(ok for _n, ok in marks):
            ttk.Label(f, text=d.note, foreground="#555").pack(anchor="w", pady=(2, 0))

    @staticmethod
    def _manual_place():
        """paths.json の Kimodo が使える場所にあり、その 1 つ上にセットアップの印が無い（手で入れた）時、その場所。無ければ None。"""
        try:
            kimodo = paths.kimodo_dir()
        except paths.NotSetUp:
            return None
        if os.path.isfile(os.path.join(os.path.dirname(kimodo.rstrip("\\")), steps.STATE_FILE)):
            return None
        return kimodo

    def _expand(self):
        self.expanded = True
        self._refresh()

    def _show_form(self, show, text_box=True):
        """入れる場所〜ボタン（form）を出すか。text_box: Llama のチェックを出すか（手で入れた環境では効かないので隠す）。"""
        if show and not self.form.winfo_manager():
            self.more_btn.pack_forget()
            self.form.pack(fill="both", expand=True)
        elif not show and self.form.winfo_manager():
            self.form.pack_forget()
        if not show and not self.more_btn.winfo_manager():
            self.more_btn.pack(anchor="w", pady=(8, 0))
        if not text_box:
            self.text_box.pack_forget()
        elif not self.text_box.winfo_manager():
            self.text_box.pack(fill="x", before=self.form if show else self.more_btn)

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
        dest = self.dest.get().strip()
        if dest != self._text_dest:   # 場所が変わった（開いた時も）: その場所で前に選んだ方にする
            self._text_dest = dest
            try:
                self.with_text.set(steps.Setup(dest).chosen_text())
            except steps.Failed:
                pass
        return steps.Setup(dest, log=lambda line: self.q.put(("log", line)),
                           progress=lambda text: self.q.put(("progress", text)),
                           on_step=lambda key, state: self.q.put(("step", (key, state))), with_text=self.with_text.get())

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
        done = setup.finished_steps(state)
        listed = [(key, title, "skip" if key in done else "todo") for key, _g, title, _version, _gb, _fn in setup.steps()]
        self._show_steps(listed)
        need = setup.remaining_gb()
        try:
            free = f"{steps.free_gb(setup.dest):.0f}GB"
        except OSError:
            free = "（読めません）"
        done = sum(1 for _k, _t, mark in listed if mark == "skip")
        self.space.set(f"空き {free}／これから使う量 約 {need:.0f}GB" + (f"（済んだ {done} 手順の分を除く）" if done else ""))
        kind, pending = setup.status()
        if self.manual and not self.expanded:
            mb = paths.motionbricks_dir()
            self.headline.set("別の方法で入れた環境を使っています")
            self.subline.set(f"Kimodo: {self.manual}" + (f"・MotionBricks: {mb}" if mb else "")
                             + "\n入れ直したい時は、「別の場所に入れる…」で場所を選んでください")
            self._show_form(False, text_box=False)
            return
        if kind == "done":
            used = setup.in_use()
            self.headline.set("入っています" if used else "この場所に入っています（まだ使っていません）")
            self.subline.set(f"場所: {setup.dest}" + ("" if used else "\n「この場所を使う」を押すと、すぐ使えます"))
            self._show_form(self.expanded or not used)
            self.start_btn.configure(text="この場所を使う" if not used else "セットアップ済み", state="disabled" if used else "normal")
            return
        names = "・".join(title.split("（")[0] for _k, title, _gb in pending[:4]) + ("…" if len(pending) > 4 else "")
        if kind == "update":
            self.headline.set(f"更新があります（{len(pending)} 手順・約 {need:.0f}GB）")
            self.subline.set(f"場所: {setup.dest}\n変わる手順: {names}")
            text = "更新する"
        elif kind == "partial":
            self.headline.set(f"途中で止まっています（あと {len(pending)} 手順・約 {need:.0f}GB）")
            self.subline.set(f"場所: {setup.dest}\n押すと、止まった手順から進みます")
            text = "続きから始める"
        else:
            self.headline.set("AI のモデルを入れます")
            self.subline.set(f"Kimodo・MotionBricks と、それを動かす Python をまとめて入れます（落とす量は約 {'12' if setup.with_text else '4'}GB）")
            text = "セットアップを始める"
        self._show_form(True)
        self.start_btn.configure(text=text, state="normal" if self.agree.get() else "disabled")

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
        kind, pending = setup.status()
        if kind != "done" and not self.agree.get():
            return
        if any(key == "text_remove" for key, _t, _gb in pending) and not messagebox.askyesno(
                "AIナカワリ のセットアップ", "入れてあるプロンプトの読み取り（Llama 3・約 8GB）を消します。\n"
                "消した後は「サンプルから選ぶ」の文だけで作ります（また入れる時は約 8GB 落とし直します）。よろしいですか？",
                parent=self.win):
            return
        self.setup = setup
        self.expanded = True   # 回した後も、入れる場所・段の一覧・ログを出したままにする
        self.headline.set("入れています…")
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.status.set(f"入れています（落とす量は約 {setup.remaining_gb():.0f}GB）。この窓は閉じても裏で進みます")

        def work():
            try:
                setup.run()
                self.q.put(("end", None))
            except steps.Cancelled:
                self.q.put(("end", "中止しました。もう一度押すと続きから進みます"))
            except steps.Failed as e:
                self.q.put(("end", f"止まりました: {e}\nもう一度押すと、止まった手順から進みます"))
            except Exception as e:   # 思っていない失敗。記録に traceback を残して、画面には一言
                applog.exception("セットアップの思っていない失敗:")
                self.q.put(("end", f"思わぬエラーで止まりました（{e}）。詳細の窓の「ログ」→「記録のフォルダを開く」にある app.log を送ってください"))
        self.thread = threading.Thread(target=work, name="セットアップ", daemon=True)
        self.thread.start()

    def _cancel(self):
        if self.setup is not None and messagebox.askyesno("AIナカワリ のセットアップ", "中止しますか？（済んだ手順はそのまま残ります）",
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
        self.manual = self._manual_place()   # 済んだら paths.json が新しい場所を指す
        self._refresh()
        if error:
            self.status.set(error)
            self._write_log(error)
            self.win.deiconify()
            return
        self.status.set("できました。「生成」で使えます")
        for callback in self.on_done:
            try:
                callback()
            except Exception:   # 閉じた MMD の窓など。セットアップは済んでいる
                applog.exception("セットアップ後の窓の更新の失敗:")
        self.win.deiconify()
        messagebox.showinfo("AIナカワリ のセットアップ", "できました。「生成」で使えます", parent=self.win)

    def close(self):
        if self.thread is not None:
            self.win.withdraw()   # 裏で進める（もう一度「セットアップ」を押すと出る）
            return
        self.win.destroy()
        SetupWindow.current = None
