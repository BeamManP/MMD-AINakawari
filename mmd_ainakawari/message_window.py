"""別スレッドで回す見えない窓。MMD のプラグインや 2 回目の起動からの知らせを受ける。"""
import ctypes
import threading

import win32api
import win32con
import win32gui

_register = ctypes.windll.user32.RegisterWindowMessageW
_register.argtypes = [ctypes.c_wchar_p]
_register.restype = ctypes.c_uint


def register_message(name):
    return _register(name)


class MessageWindow:
    """専用のスレッドで回す見えない窓。handlers の登録メッセージが届くと handler(wparam, lparam) をそのスレッドで呼ぶ。

    tkinter の mainloop は待ち受け中に GIL を手放すので、同じスレッドに pywin32 の窓を置くと、
    メッセージが来た瞬間に Python ごと落ちる（2026-11-03 に実際に落ちた）。なので必ず別スレッドで回す。
    受け口の関数は窓のクラスごとに 1 つなので、同じプロセスで複数作る時は class_name を変えること。
    """

    def __init__(self, class_name, handlers):
        self.class_name = class_name
        self.handlers = {register_message(name): handler for name, handler in handlers.items()}
        self.hwnd = None
        self.thread = None

    def start(self):
        if self.hwnd:
            return
        ready = threading.Event()
        failure = []

        def run():
            try:
                instance = win32api.GetModuleHandle(None)
                wc = win32gui.WNDCLASS()
                wc.lpszClassName = self.class_name
                wc.hInstance = instance
                wc.lpfnWndProc = self._wndproc
                try:
                    win32gui.RegisterClass(wc)
                except win32gui.error as error:
                    if error.winerror != 1410:  # 登録済み
                        raise
                self.hwnd = win32gui.CreateWindow(self.class_name, "", 0, 0, 0, 0, 0,
                                                  win32con.HWND_MESSAGE, 0, instance, None)
            except Exception as error:  # 呼んだ側で投げ直す
                failure.append(error)
                return
            finally:
                ready.set()
            win32gui.PumpMessages()

        self.thread = threading.Thread(target=run, name=self.class_name, daemon=True)
        self.thread.start()
        ready.wait()
        if failure:
            raise failure[0]

    def stop(self):
        if self.hwnd:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)
            self.thread.join(5)
            self.hwnd = None

    def _wndproc(self, hwnd, message, wparam, lparam):
        if message in self.handlers:
            self.handlers[message](wparam, lparam)
            return 0
        if message == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(hwnd, message, wparam, lparam)
