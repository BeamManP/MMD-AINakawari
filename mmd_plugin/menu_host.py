"""MMD のメニューバーに「MMDKimodo」を出し、押された項目をこちらで受け取る。

menu_bridge.cpp の DLL を、MMD の UI スレッドに限ったフックで読み込ませる（mmd-mcp のボーン選択と同じ入り方）。
d3d9.dll には触らないので、MME・MMAccel・MMDPlugin とぶつからない。フックを外せば DLL も MMD から抜ける。
"""
import ctypes
import mmap
import queue
import secrets
import struct
import sys
import threading
import time
from pathlib import Path

import win32api
import win32con
import win32gui
import win32process

from mmd_mcp.windows import list_windows

DLL_PATH = Path(__file__).resolve().parent / "bin" / "mmdkimodo_menu.dll"
MAX_ITEMS = 16
PROTOCOL = struct.Struct("<IIQQii1024sii")  # menu_bridge.cpp の Request と同じ並び
MAGIC, VERSION = 0x4E4D4B4D, 1
STATUS = {-1: "依頼の中身が合わない", -2: "MMD の窓が違う／メニューが無い", -3: "項目の数が不正",
          -4: "メニューの番号が他とぶつかる", -5: "メニューを作れなかった",
          -6: "メニューバーに「ヘルプ」が見つからない"}
WH_GETMESSAGE, WH_CALLWNDPROC = 3, 4

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32.RegisterWindowMessageW.argtypes = [ctypes.c_wchar_p]
_user32.RegisterWindowMessageW.restype = ctypes.c_uint
_user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
_user32.SetWindowsHookExW.restype = ctypes.c_void_p
_user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
_user32.UnhookWindowsHookEx.restype = ctypes.c_int
_user32.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t,
                                        ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
_user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
_kernel32.LoadLibraryW.argtypes = [ctypes.c_wchar_p]
_kernel32.LoadLibraryW.restype = ctypes.c_void_p
_kernel32.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
_kernel32.GetProcAddress.restype = ctypes.c_void_p
_kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
_kernel32.FreeLibrary.restype = ctypes.c_int


def _mmd_window():
    wins = list_windows()
    if not wins:
        raise RuntimeError("MMD が起動していません")
    if len(wins) > 1:
        raise RuntimeError(f"MMD が {len(wins)} 個起動しています。1 つにしてください")
    return wins[0]


class MenuBridge:
    """attach で MMD にメニューを出す。押されると commands に (番号, 届き方) が積まれる。届き方は "post" か "send"。

    通知を受ける窓は専用のスレッドで回す。tkinter の mainloop は待ち受け中に GIL を手放すので、
    同じスレッドに pywin32 の窓を置くと、通知が来た瞬間に Python ごと落ちる（2026-11-03 に実際に落ちた）。
    """

    def __init__(self, items):
        if not 1 <= len(items) <= MAX_ITEMS or any(len(i) > 31 for i in items):
            raise ValueError(f"項目は 1〜{MAX_ITEMS} 個、1 つ 31 文字までです")
        self.items = list(items)
        self.commands = queue.Queue()
        self.window = None
        self.thread = None
        self.module = None
        self.hooks = []
        self.notify = None
        self.notify_thread = None
        self.position = None
        self._notify_message = _user32.RegisterWindowMessageW("MMDKimodo.MenuCommand.v1")
        self._control_message = _user32.RegisterWindowMessageW("MMDKimodo.MenuControl.v1")

    @property
    def attached(self):
        return bool(self.hooks)

    def attach(self):
        if self.attached:
            return
        if not DLL_PATH.is_file():
            raise RuntimeError(f"DLL がありません。mmd_plugin/build.cmd でビルドしてください: {DLL_PATH}")
        self.window = _mmd_window()
        self.thread, pid = win32process.GetWindowThreadProcessId(self.window.hwnd)
        if pid != self.window.pid or not self.thread:
            raise RuntimeError("MMD の UI スレッドを特定できません")
        self._start_notify_thread()
        self.module = _kernel32.LoadLibraryW(str(DLL_PATH))
        if not self.module:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            for kind, name in ((WH_CALLWNDPROC, b"MenuCallWndProc"), (WH_GETMESSAGE, b"MenuGetMsgProc")):
                procedure = _kernel32.GetProcAddress(self.module, name)
                hook = _user32.SetWindowsHookExW(kind, procedure, self.module, self.thread) if procedure else None
                if not hook:
                    raise ctypes.WinError(ctypes.get_last_error())
                self.hooks.append(hook)
            self.position = self._request(1)
        except BaseException:
            self._release()
            raise

    def detach(self):
        if not self.attached:
            return
        try:
            if win32gui.IsWindow(self.window.hwnd):  # MMD が先に閉じていたら、外すメニューも無い
                self._request(2)
        finally:
            self._release()
            self._stop_notify_thread()

    def _request(self, command):
        nonce = secrets.randbits(64) or 1
        name = f"Local\\MMDKimodo.Menu.v1.{self.window.pid}.{nonce:016x}"
        labels = b"".join(i.encode("utf-16-le").ljust(64, b"\0") for i in self.items).ljust(1024, b"\0")
        with mmap.mmap(-1, PROTOCOL.size, tagname=name) as shared:
            shared[:] = PROTOCOL.pack(MAGIC, VERSION, self.window.hwnd, self.notify, command,
                                      len(self.items), labels, 0, -1)
            result = ctypes.c_size_t()
            # SMTO_BLOCK | SMTO_ABORTIFHUNG。MMD が固まっていたら待たずに諦める
            if not _user32.SendMessageTimeoutW(self.window.hwnd, self._control_message, nonce, 0,
                                               0x1 | 0x2, 3000, ctypes.byref(result)):
                raise RuntimeError("MMD が応答しません（3 秒）")
            *_, status, position = PROTOCOL.unpack(shared[:])
        if status != 2:
            raise RuntimeError(f"MMD の中での処理に失敗しました: {STATUS.get(status, status)}")
        return position

    def _start_notify_thread(self):
        if self.notify:
            return
        ready = threading.Event()
        failure = []

        def run():
            try:
                instance = win32api.GetModuleHandle(None)
                wc = win32gui.WNDCLASS()
                wc.lpszClassName = "MMDKimodo.MenuHost"
                wc.hInstance = instance
                wc.lpfnWndProc = self._wndproc
                try:
                    win32gui.RegisterClass(wc)
                except win32gui.error as error:
                    if error.winerror != 1410:  # 登録済み
                        raise
                self.notify = win32gui.CreateWindow("MMDKimodo.MenuHost", "", 0, 0, 0, 0, 0,
                                                    win32con.HWND_MESSAGE, 0, instance, None)
            except Exception as error:  # 呼んだ側で投げ直す
                failure.append(error)
                return
            finally:
                ready.set()
            win32gui.PumpMessages()

        self.notify_thread = threading.Thread(target=run, name="MMDKimodo.MenuHost", daemon=True)
        self.notify_thread.start()
        ready.wait()
        if failure:
            raise failure[0]

    def _stop_notify_thread(self):
        if self.notify:
            win32gui.PostMessage(self.notify, win32con.WM_CLOSE, 0, 0)
            self.notify_thread.join(5)
            self.notify = None

    def _wndproc(self, hwnd, message, wparam, lparam):
        if message == self._notify_message:
            self.commands.put((int(wparam), {1: "post", 2: "send"}.get(lparam, lparam)))
            return 0
        if message == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)

    def _release(self):
        for hook in self.hooks:
            _user32.UnhookWindowsHookEx(hook)
        self.hooks.clear()
        if self.module:
            _kernel32.FreeLibrary(self.module)
            self.module = None


def main():
    """試し: メニューを出し、押された項目を表示する。「メニューを外す」か制限時間で外して終わる。"""
    sys.stdout.reconfigure(encoding="utf-8")
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 300
    items = ["動作テスト", "-", "メニューを外す"]
    bridge = MenuBridge(items)
    bridge.attach()
    print(f"{time.strftime('%H:%M:%S')} メニューを付けました（メニューバーの {bridge.position} 番目）", flush=True)
    deadline = time.monotonic() + seconds
    try:
        while (left := deadline - time.monotonic()) > 0:
            try:
                index, how = bridge.commands.get(timeout=left)
            except queue.Empty:
                break
            print(f"{time.strftime('%H:%M:%S')} 押された: {index}「{items[index]}」（{how} で届いた）", flush=True)
            if items[index] == "メニューを外す":
                break
    finally:
        bridge.detach()
        print(f"{time.strftime('%H:%M:%S')} メニューを外しました", flush=True)


if __name__ == "__main__":
    main()
