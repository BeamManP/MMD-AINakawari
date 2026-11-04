"""MMD の右下の「Kimodo操作」パネル（mmd_plugin/kimodo_panel.cpp）を読み書きする。

パネルはプラグイン（MMD のプロセスの中）が作る MMD の窓の子で、部品を並べるだけ。中身は窓（app.py の App）が 0.5 秒ごとに
読み書きして、窓の設定と同期する（プロンプト・Kimodo か中割りか・選んだキーの間）。ボタンが押されるとプラグインが Hub に知らせる。
別のプロセスの部品なので、WM_GETTEXT・WM_SETTEXT などは Windows が中身を写してくれる。
MMD が VMD の読み込みなどで忙しい間に窓まで固まらないよう、送る時は期限を付ける（SendMessageTimeout）。
"""
import ctypes
import re
from ctypes import wintypes

import win32gui

CLASS = "MMDKimodo.Panel"
# 部品の番号（kimodo_panel.cpp と同じ）
ENGINE, RANGE, PROMPT, GENERATE, UNDO, DETAILS, STATUS = 101, 102, 103, 104, 105, 106, 107

WM_GETTEXT, WM_SETTEXT, WM_GETTEXTLENGTH = 0x000D, 0x000C, 0x000E
BM_GETCHECK, BM_SETCHECK = 0x00F0, 0x00F1
CB_GETCURSEL, CB_SETCURSEL = 0x0147, 0x014E
SMTO_ABORTIFHUNG = 0x0002
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
    def __init__(self, mmd_hwnd):
        self.mmd = mmd_hwnd
        self.hwnd = None

    def find(self):
        """パネルを探す（無い時は None。プラグインが古い・空き地が無くて作っていない）。"""
        if not (self.hwnd and win32gui.IsWindow(self.hwnd)):
            self.hwnd = win32gui.FindWindowEx(self.mmd, 0, CLASS, None) or None
        return self.hwnd

    def visible(self):
        return bool(self.hwnd and win32gui.IsWindowVisible(self.hwnd))

    def _item(self, item):
        return win32gui.GetDlgItem(self.hwnd, item)

    def _call(self, item, message, wparam=0, lparam=0):
        result = ctypes.c_size_t()
        if not _send(self._item(item), message, wparam, lparam, SMTO_ABORTIFHUNG, TIMEOUT_MS, ctypes.byref(result)):
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

    def checked(self, item):
        return self._call(item, BM_GETCHECK) == 1

    def set_checked(self, item, on):
        self._call(item, BM_SETCHECK, 1 if on else 0)

    def selection(self, item):
        return self._call(item, CB_GETCURSEL)

    def select(self, item, index):
        self._call(item, CB_SETCURSEL, index)

    def enable(self, item, on):
        win32gui.EnableWindow(self._item(item), bool(on))
