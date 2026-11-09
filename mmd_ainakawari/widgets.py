"""窓の部品（区間ごとのプロンプトの行・畳める欄）。"""
import re
import tkinter as tk
from tkinter import ttk

_SEGMENT = re.compile(r"\s*(\d+)\s*[:：]\s*(.*)")


def set_enabled(widget, on):
    """ttk の部品を押せる／押せなくする。今と同じなら何もしない。変えたら True。

    ttk の部品は state を同じ値で設定し直すだけで、マウスオーバーの印（active）が消え、マウスが入り直すまで戻らない
    （11-08 マスター。詳細の窓の 0.5 秒ごとの更新で「生成」の青いマウスオーバーが一瞬で消えていた。Tk 8.6.12 で確かめた）。
    押せるように戻した時にマウスが上にあれば、印を付け直す。
    """
    state = "normal" if on else "disabled"
    if str(widget.cget("state")) == state:
        return False
    widget.configure(state=state)
    try:
        under = widget.winfo_containing(*widget.winfo_pointerxy()) if on else None
    except (KeyError, tk.TclError):   # マウスの下が tkinter の知らない部品（コンボボックスの一覧など）
        under = None
    if under is widget:
        widget.state(["active"])
    return True


class PromptRows(ttk.Frame):
    """区間ごとのプロンプトの行。

    最初の行は範囲の始まりから（pipeline.prompt_segments が始まりに置き換える）なので、フレームの欄を出さない。
    text() で pipeline が読む形（2 行目から「45: …」）にする。load() は同じ形の文字列から行を作る（前の窓の保存もこの形）。
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(1, weight=1)
        self.rows = []   # [{"frame": StringVar か None, "text": StringVar, "entry": 文の欄, "widgets": [...]}]（変数も持っておく。手放すと tk 側の値が消える）
        self.readonly = False   # 文の欄を打てなくする（Llama なし。サンプルからだけ選ぶ。11-10 マスター）

    def set_readonly(self, on):
        """文の欄を打てなくする・戻す。区間のフレームの欄はそのまま打てる。打てなくても、行を押せばサンプルの入れ先になる。"""
        self.readonly = bool(on)
        for row in self.rows:
            row["entry"].configure(state="readonly" if self.readonly else "normal")

    def load(self, prompt):
        for row in self.rows:
            for w in row["widgets"]:
                w.destroy()
        self.rows = []
        for line in prompt.splitlines():
            m = _SEGMENT.match(line)
            if m and self.rows:
                self._add(int(m.group(1)), m.group(2).strip())
            elif line.strip():
                text = (m.group(2) if m else line).strip()
                if self.rows:   # 区切りの無い行は、直前の区間の続きの文
                    last = self.rows[-1]["text"]
                    last.set((last.get() + " " + text).strip())
                else:
                    self._add(None, text)
        if not self.rows:
            self._add(None, "")
        self._regrid()

    def set_current(self, text):
        """最後に打っていた行の文を text にする（まだどの行も触っていない・その行を消した時は「始め」の行）。サンプル用。"""
        row = getattr(self, "current", None)
        (row if row in self.rows else self.rows[0])["text"].set(text)

    def add_at(self, frame):
        """frame から新しい区間の行を足す。同じフレームの行があれば False。"""
        if any(r["frame"] is not None and r["frame"].get().strip() == str(frame) for r in self.rows):
            return False
        self._add(frame, "")
        self._regrid()
        return True

    def text(self):
        """pipeline に渡すプロンプト。フレームが数字でない・重なる行は ValueError。"""
        first, *others = self.rows
        segments = []
        for r in others:
            value = r["frame"].get().strip()
            if not value.isdigit():
                raise ValueError(f"区間の開始フレーム「{value}」が数字ではありません")
            segments.append((int(value), r["text"].get().strip()))
        frames = [f for f, _ in segments]
        if len(set(frames)) != len(frames):
            raise ValueError("同じフレームから始まる区間が 2 つあります")
        head = first["text"].get().strip()
        # 最初の行が空で区間がほかにある時は「0:」（空の区間）と書く。ただの空行だと pipeline も load も読み飛ばして、
        # 2 行目の区間が範囲の始まりからになっていた（11-04 Codex のレビュー。空のプロンプトはキーだけで作る）
        lines = [head if head or not segments else "0:"] + [f"{f}: {t}" for f, t in sorted(segments)]
        return "\n".join(lines)

    def _add(self, frame, text):
        text_var = tk.StringVar(value=text)
        if frame is None:
            head = [ttk.Label(self, text="始め", width=6, anchor="e")]
            frame_var = None
        else:
            frame_var = tk.StringVar(value=str(frame))
            box = ttk.Frame(self)
            frame_entry = ttk.Entry(box, textvariable=frame_var, width=5, justify="right")
            frame_entry.pack(side="left")
            ttk.Label(box, text="F").pack(side="left")
            head = [box]
            # 打っている途中で並び替えると行が動くので、欄を離れた時だけ並べ直す
            frame_entry.bind("<FocusOut>", lambda _: self._regrid())
            frame_entry.bind("<Return>", lambda _: self._regrid())
        entry = ttk.Entry(self, textvariable=text_var, state="readonly" if self.readonly else "normal")
        row = {"frame": frame_var, "text": text_var, "entry": entry, "widgets": head + [entry]}
        entry.bind("<FocusIn>", lambda _: setattr(self, "current", row))   # サンプルを入れる先（最後に打っていた行）
        if frame is not None:
            remove = ttk.Button(self, text="×", width=3, command=lambda: self._remove(row))
            row["widgets"].append(remove)
        self.rows.append(row)

    def _remove(self, row):
        for w in row["widgets"]:
            w.destroy()
        self.rows.remove(row)
        self._regrid()

    def _regrid(self):
        def key(r):
            value = r["frame"].get().strip() if r["frame"] is not None else ""
            return (r["frame"] is not None, int(value) if value.isdigit() else 10**9)
        self.rows.sort(key=key)
        for i, row in enumerate(self.rows):
            head, entry, *rest = row["widgets"]
            head.grid(row=i, column=0, sticky="e", padx=(0, 6), pady=1)
            entry.grid(row=i, column=1, sticky="we", pady=1)
            if rest:
                rest[0].grid(row=i, column=2, padx=(4, 0), pady=1)


class Fold(ttk.Frame):
    """「▶ 見出し」を押すと開く欄。中身は body に置く。"""

    def __init__(self, parent, title, opened=False):
        super().__init__(parent)
        self.title = title
        self.opened = opened
        self.button = ttk.Button(self, command=self.toggle)
        self.button.pack(anchor="w")
        self.body = ttk.Frame(self)
        self._apply()

    def toggle(self):
        self.opened = not self.opened
        self._apply()

    def _apply(self):
        self.button.configure(text=("▼ " if self.opened else "▶ ") + self.title)
        if self.opened:
            self.body.pack(fill="both", expand=True, pady=(4, 0))
        else:
            self.body.pack_forget()


class ScrollFrame(ttk.Frame):
    """中身が入りきらない時だけ縦のスクロールバーが出る枠。中身は inner に置く。

    tkinter の枠は入りきらない分を下から黙って切るので、窓を低くすると下の部品が消えていた（11-04、576×206 の窓で「生成」が見えなかった）。
    何もしなければ中身の高さぴったりを求めるので、最初の窓は中身に合う。マウスホイールは、ポインタがこの枠の上にある時だけ効く。
    """

    _wheel_bound = False

    def __init__(self, parent, padding=(8, 6)):
        super().__init__(parent)
        bg = ttk.Style().lookup("TFrame", "background")
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=bg)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas, padding=padding)
        self._item = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._inner_changed)
        self.canvas.bind("<Configure>", self._canvas_changed)
        # Windows のホイールの合図は入力中の部品に届くので、全体で受けてポインタの下の ScrollFrame を探す
        if not ScrollFrame._wheel_bound:
            self.bind_all("<MouseWheel>", ScrollFrame._wheel, add="+")
            ScrollFrame._wheel_bound = True

    def _inner_changed(self, _event):
        # 求める大きさを中身に合わせる（窓を手で縮めていなければ、窓が中身に合う）
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()),
                              width=self.inner.winfo_reqwidth(), height=self.inner.winfo_reqheight())
        self._update_bar()

    def _canvas_changed(self, event):
        self.canvas.itemconfigure(self._item, width=event.width)   # 横は枠いっぱいに広げる
        self._update_bar()

    def _overflow(self):
        return self.inner.winfo_reqheight() > self.canvas.winfo_height() + 1

    def _update_bar(self):
        if self._overflow():
            if not self.bar.winfo_ismapped():
                self.bar.pack(side="right", fill="y", before=self.canvas)
        else:
            if self.bar.winfo_ismapped():
                self.bar.pack_forget()
            self.canvas.yview_moveto(0)

    @staticmethod
    def _wheel(event):
        w = event.widget.winfo_containing(event.x_root, event.y_root) if hasattr(event.widget, "winfo_containing") else None
        while w is not None and not isinstance(w, ScrollFrame):
            w = w.master
        if w is not None and w._overflow():
            w.canvas.yview_scroll(int(-event.delta / 120), "units")
