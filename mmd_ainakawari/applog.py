"""AIナカワリ の窓の記録（work\\app.log）。困った時に送ってもらう物（README の「困った時は」）。

書く物: 窓のログに出した行・生成や元に戻すが失敗した時の traceback・どこにも拾われなかった例外
（tk のボタンなどのコールバック・裏のスレッド・pythonw が捨てる stdout / stderr）。
常駐の記録は別のファイル（work\\<名前>_server.log。resident.py）。
1MB を超えたら app.log.1 に回して、1 世代だけ残す。
窓のプロセスは 1 つだけ（app.py の APP_MUTEX）なので、setup() は mutex を取った後に呼ぶ（2 回目の起動は書かない）。
"""
import datetime
import os
import platform
import sys
import threading
import traceback

from . import __version__, paths

LOG_PATH = os.path.join(paths.WORK_DIR, "app.log")
MAX_BYTES = 1 << 20
_lock = threading.RLock()
_file = None
_lost = 0   # 書けなかった行の数（write）


class _Stream:
    """pythonw では sys.stdout / sys.stderr が None。print や警告を捨てずに記録へ回す。"""

    def __init__(self, name):
        self.name = name
        self.buf = ""

    def write(self, s):
        with _lock:
            self.buf += s
            while "\n" in self.buf:
                line, self.buf = self.buf.split("\n", 1)
                write(f"[{self.name}] {line}")
        return len(s)

    def flush(self):
        pass


def _open():
    global _file
    os.makedirs(paths.WORK_DIR, exist_ok=True)
    _file = open(LOG_PATH, "a", encoding="utf-8", buffering=1)


def _rotate():
    """app.log を app.log.1 に回す。回せなかった時（ほかのプログラムが app.log.1 を開いているなど）は、そのまま app.log に書き続ける
    （11-06 Codex のレビュー: 閉じたままになり、以後の書き込みが例外になって、セットアップの画面の更新まで止まっていた）。"""
    global _file
    _file.close()
    try:
        os.replace(LOG_PATH, LOG_PATH + ".1")
    except OSError:
        pass
    _open()


def write(text):
    """記録に書く。複数行は 2 行目から字下げする。setup() の前は書かない（2 回目の起動など）。
    記録が書けなくても例外は出さない（窓やセットアップの画面を止めない）。書けなかった行は、次に開き直せた時に「書けなかった」と残す。"""
    global _file, _lost
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = str(text).rstrip("\n").split("\n")
    with _lock:
        if _file is None:
            return
        try:
            if _file.closed:
                _open()
            if _file.tell() > MAX_BYTES:
                _rotate()
            if _lost:
                _file.write(f"{stamp} （記録が書けなかった行が {_lost} 行あります）\n")
                _lost = 0
            _file.write(f"{stamp} {lines[0]}\n" + "".join(f"    {line}\n" for line in lines[1:]))
        except (OSError, ValueError):
            _lost += 1


def exception(title):
    """except の中で呼ぶ。今の例外の traceback を書く。"""
    write(f"{title}\n{traceback.format_exc()}")


def _hook(title, exc_type, exc, tb):
    write(f"{title}\n{''.join(traceback.format_exception(exc_type, exc, tb))}")


def setup():
    with _lock:
        if _file is not None:
            return
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > MAX_BYTES:
            os.replace(LOG_PATH, LOG_PATH + ".1")
        _open()
    write("―" * 30)
    write(f"起動: AIナカワリ {__version__}・Python {sys.version.split()[0]}・{platform.platform()}\n"
          f"Python: {sys.executable}\napp: {paths.HOME}")
    if sys.stdout is None:
        sys.stdout = _Stream("stdout")
    if sys.stderr is None:
        sys.stderr = _Stream("stderr")
    sys.excepthook = lambda t, e, tb: _hook("拾われなかった例外:", t, e, tb)   # i18n: skip
    threading.excepthook = lambda a: _hook(f"スレッド {a.thread.name if a.thread else '?'} で拾われなかった例外:",   # i18n: skip
                                           a.exc_type, a.exc_value, a.exc_traceback)


def hook_tk(root):
    """tk のコールバック（ボタン・after など）の例外。tk は既定では stderr に出すだけ。"""
    root.report_callback_exception = lambda t, e, tb: _hook("窓の処理で拾われなかった例外:", t, e, tb)   # i18n: skip
