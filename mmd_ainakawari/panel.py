"""MMD の右下の「Kimodo操作」パネル（mmd_plugin/nakawari_panel.cpp）を読み書きする。

パネルはプラグイン（MMD のプロセスの中）が作る MMD の窓の子で、部品を並べるだけ。中身は窓（app.py の App）が 0.5 秒ごとに
読み書きして、窓の設定と同期する（プロンプト・Kimodo か中割りか。範囲は字で出すだけ）。ボタンが押されるとプラグインが Hub に知らせる。
別のプロセスの部品なので、WM_GETTEXT・WM_SETTEXT などは Windows が中身を写してくれる。
MMD が VMD の読み込みなどで忙しい間に窓まで固まらないよう、送る時は期限を付ける（SendMessageTimeout）。
"""
import ctypes
import re
from ctypes import wintypes

import win32gui

CLASS = "AINakawari.Panel"
# 部品の番号（nakawari_panel.cpp と同じ）
ENGINE, RANGE, PROMPT, GENERATE, UNDO, DETAILS, STATUS, SAMPLES = 101, 102, 103, 104, 105, 106, 107, 108

WM_GETTEXT, WM_SETTEXT, WM_GETTEXTLENGTH = 0x000D, 0x000C, 0x000E
CB_GETCURSEL, CB_SETCURSEL = 0x0147, 0x014E
EM_SETREADONLY = 0x00CF   # 文の欄を打てなくする（Llama なし。プラグインを作り直さずに済むよう、窓から欄へ直接送る。11-10）
SMTO_ABORTIFHUNG = 0x0002
ENABLE_MESSAGE = 0x8000 + 2   # WM_APP + 2。パネルに部品の押せる・押せないを頼む（nakawari_panel.cpp の kEnableMessage）
ALERT_MESSAGE = 0x8000 + 3    # WM_APP + 3。状態の 1 行を赤くするかを頼む（kAlertMessage。古いプラグインは知らないので無視する）
TIMEOUT_MS = 200

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_send = _user32.SendMessageTimeoutW
_send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                  ctypes.POINTER(ctypes.c_size_t)]
_send.restype = wintypes.LPARAM


def one_line(prompt):
    """窓のプロンプト（区間ごとの行）→ パネルの 1 行。区間は「 / 」でつなぐ（例: run / 45: stop）。"""
    return " / ".join(line.strip() for line in prompt.splitlines())


def lines_of(text):
    """パネルの 1 行 → 窓のプロンプトの形（区間ごとの行）。「/」の前後の空白はあってもなくてもよい。"""
    return "\n".join(part.strip() for part in re.split(r"\s*/\s*", text))


class Busy(Exception):
    """MMD が答えない（忙しい）。次の同期でまた試す。"""


class Panel:
    def __init__(self, mmd_hwnd, nested=False):
        """nested: MMM（MikuMikuMoving）の時。MMM はプラグインのパネルを本体の窓の中のタブに入れるので、直下の子でなく奥まで探し、
        クラス名でなく窓の字（CLASS と同じ目印。mmm_plugin/AINakawariPanel.cs）で見分ける。部品の番号と読み書きは MMD のパネルと同じ。"""
        self.mmd = mmd_hwnd
        self.nested = nested
        self.hwnd = None

    def find(self):
        """パネルを探す（無い時は None。プラグインが古い・空き地が無くて作っていない）。"""
        if not (self.hwnd and win32gui.IsWindow(self.hwnd)):
            if self.nested:
                found = []
                try:
                    win32gui.EnumChildWindows(self.mmd, lambda h, _: found.append(h) if win32gui.GetWindowText(h) == CLASS else None, None)
                except win32gui.error:   # 相手の窓がちょうど閉じた
                    pass
                self.hwnd = found[0] if found else None
            else:
                self.hwnd = win32gui.FindWindowEx(self.mmd, 0, CLASS, None) or None
        return self.hwnd

    def visible(self):
        return bool(self.hwnd and win32gui.IsWindowVisible(self.hwnd))

    def _item(self, item):
        return win32gui.GetDlgItem(self.hwnd, item)

    def _call(self, item, message, wparam=0, lparam=0, to=None):
        result = ctypes.c_size_t()
        target = self._item(item) if to is None else to
        if not _send(target, message, wparam, lparam, SMTO_ABORTIFHUNG, TIMEOUT_MS, ctypes.byref(result)):
            raise Busy()
        return result.value

    def text(self, item):
        n = self._call(item, WM_GETTEXTLENGTH)
        buffer = ctypes.create_unicode_buffer(n + 1)
        self._call(item, WM_GETTEXT, n + 1, ctypes.addressof(buffer))
        return buffer.value

    def set_text(self, item, text):
        buffer = ctypes.create_unicode_buffer(text)
        self._call(item, WM_SETTEXT, 0, ctypes.addressof(buffer))

    def selection(self, item):
        return self._call(item, CB_GETCURSEL)

    def select(self, item, index):
        self._call(item, CB_SETCURSEL, index)

    def enable(self, item, on):
        # EnableWindow を直接呼ぶと、MMD が答えるまで待って期限を付けられないので、パネルに頼む（11-05 Codex のレビュー）
        self._call(item, ENABLE_MESSAGE, item, 1 if on else 0, to=self.hwnd)

    def set_readonly(self, item, on):
        """欄を打てなくする・戻す。打てなくても WM_SETTEXT（サンプル・窓からの同期）は効く。"""
        self._call(item, EM_SETREADONLY, 1 if on else 0)

    def alert(self, on):
        """状態の 1 行を赤で描くか（セットアップ前の案内など）。"""
        self._call(STATUS, ALERT_MESSAGE, 0, 1 if on else 0, to=self.hwnd)
