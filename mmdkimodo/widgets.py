"""窓の部品（区間ごとのプロンプトの行・畳める欄）。"""
import re
import tkinter as tk
from tkinter import ttk

_SEGMENT = re.compile(r"\s*(\d+)\s*[:：]\s*(.*)")


class PromptRows(ttk.Frame):
    """区間ごとのプロンプトの行。

    最初の行は範囲の始まりから（pipeline.prompt_segments が始まりに置き換える）なので、フレームの欄を出さない。
    text() で pipeline が読む形（2 行目から「45: …」）にする。load() は同じ形の文字列から行を作る（前の窓の保存もこの形）。
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(1, weight=1)
        self.rows = []   # [{"frame": StringVar か None, "text": StringVar, "widgets": [...]}]（変数も持っておく。手放すと tk 側の値が消える）

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
        lines = [first["text"].get().strip()] + [f"{f}: {t}" for f, t in sorted(segments)]
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
        entry = ttk.Entry(self, textvariable=text_var)
        row = {"frame": frame_var, "text": text_var, "widgets": head + [entry]}
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
