"""常駐の生成サーバー（tools/kimodo_gen.py・tools/mb_gen.py の --serve）に頼む。いなければ立ち上げる。

モデルの読み込み（Kimodo は torch 込みで 25 秒・MotionBricks は 3 秒）を 1 回で済ませるため。
常駐は 127.0.0.1 の決まった口で待ち、しばらく頼まれなければ自分で終わる。窓（app.py）とは別のプロセスなので、
窓を閉じても残り、次に開いた窓からも使える。記録は work/<名前>_server.log。

窓は MMD ごとに同じプロセスのスレッドで生成するので、同じ常駐の立ち上げは口ごとのロックで 1 つずつにする。
つなぐ・答えを待つには期限を付ける（口をほかのプログラムが使っていて黙っている時に、窓が戻らなくならないように）。
"""
import os
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client

AUTHKEY = b"MMDKimodo.resident.v1"   # tools/kimodo_gen.py・tools/mb_gen.py と同じ
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")
CONNECT_TIMEOUT = 5.0     # つないで合言葉を確かめるまで
REPLY_TIMEOUT = 15 * 60   # 1 回の生成の答えを待つ上限（低負荷の初回の読み取りや長い動きでも数十秒）
_start_locks = defaultdict(threading.Lock)


class _Busy(Exception):
    """口は開いているが合言葉の答えが来ない。常駐がモデルを読み込み中（口は読み込みの前に開ける）か、ほかのプログラム。"""


@dataclass
class Server:
    name: str          # 記録のファイル名とメッセージ用
    port: int
    python: str
    script: str
    cwd: str
    env: dict
    args: tuple = ()             # --serve <口> の後ろに付ける引数
    start_timeout: float = 180.0


def _log_path(server):
    return os.path.join(LOG_DIR, f"{server.name}_server.log")


def _connect(server):
    """つながった Connection か、いなければ None。合言葉が違う相手はエラー、答えが来なければ _Busy。"""
    box = {}

    def go():
        try:
            box["conn"] = Client(("127.0.0.1", server.port), authkey=AUTHKEY)
        except (OSError, EOFError):   # いない・終わる途中（接続を切られた）
            box["conn"] = None
        except AuthenticationError as e:
            box["error"] = e
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(CONNECT_TIMEOUT)
    if t.is_alive():
        raise _Busy()
    if "error" in box:
        raise _foreign(server)
    return box["conn"]


def _foreign(server):
    return RuntimeError(f"{server.name} の口（127.0.0.1:{server.port}）を、ほかのプログラムが使っているようです。"
                        f"そのプログラムを閉じてからもう一度押してください")


def _connect_waiting(server, deadline):
    """_connect と同じ。ただし読み込み中（_Busy）なら deadline まで待つ。過ぎたらほかのプログラムとしてエラー。"""
    while True:
        try:
            return _connect(server)
        except _Busy:
            if time.monotonic() > deadline:
                raise _foreign(server)


def _log_tail(path, lines=15):
    try:
        return "\n".join(open(path, encoding="utf-8", errors="replace").read().splitlines()[-lines:])
    except OSError:
        return "（記録がありません）"


def _start(server, log):
    os.makedirs(LOG_DIR, exist_ok=True)
    log(f"  {server.name} を常駐させています（初回だけモデルを読み込みます）…")
    out = open(_log_path(server), "w", encoding="utf-8")
    proc = subprocess.Popen([server.python, server.script, "--serve", str(server.port), *server.args], stdout=out, stderr=subprocess.STDOUT,
                            cwd=server.cwd, env=server.env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    out.close()
    deadline = time.monotonic() + server.start_timeout
    while time.monotonic() < deadline:
        conn = _connect_waiting(server, deadline)
        if conn is not None:
            return conn
        if proc.poll() is not None:
            # 口をほかの常駐（別のプロセスの MMDKimodo が同時に立ち上げたもの）に取られて終わった時は、そちらを使う
            conn = _connect_waiting(server, deadline)
            if conn is not None:
                return conn
            raise RuntimeError(f"{server.name} の常駐が起動できませんでした:\n{_log_tail(_log_path(server))}")
        time.sleep(0.5)
    raise RuntimeError(f"{server.name} の常駐が {server.start_timeout:.0f} 秒たっても準備できません（{_log_path(server)}）")


def _ready(server, log):
    with _start_locks[server.port]:   # 同じ常駐を 2 つ立ち上げない
        return _connect_waiting(server, time.monotonic() + server.start_timeout) or _start(server, log)


def call(server, request, log=print):
    """依頼を送って (結果, 1 行のまとめ) を返す。

    常駐は自分の橋渡しのファイルが書き換わっていたら、作らずに stale で答えて終わる。その時は立ち上げ直して頼み直す。
    """
    reply = _send(_ready(server, log), server, request)
    if reply.get("stale"):
        log(f"  {server.name} の橋渡しが新しくなっていたので、常駐を立ち上げ直します…")
        _wait_closed(server)
        reply = _send(_ready(server, log), server, request)
    if not reply["ok"]:
        raise RuntimeError(f"{server.name} が失敗しました:\n" + reply.get("error", "")[-1500:])
    return reply["result"], reply.get("line", "")


def shutdown(server):
    """常駐がいれば終わらせる（モードを切り替えた時に、使わない方のメモリを空ける）。終わらせたら True。"""
    with _start_locks[server.port]:
        conn = _connect_waiting(server, time.monotonic() + server.start_timeout)
        if conn is None:
            return False
        _send(conn, server, {"shutdown": True})
        _wait_closed(server)
        return True


def _wait_closed(server, seconds=10):
    """常駐が口を閉じるまで待つ（終わる途中の常駐に頼まないように）。"""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            conn = _connect(server)
        except _Busy:   # 終わる途中で口だけ開いている
            continue
        if conn is None:
            return
        conn.close()
        time.sleep(0.2)
    raise RuntimeError(f"{server.name} の常駐が終わりません（{_log_path(server)}）")


def _send(conn, server, request):
    try:
        conn.send(request)
        if not conn.poll(REPLY_TIMEOUT):
            raise RuntimeError(f"{server.name} が {REPLY_TIMEOUT // 60} 分たっても答えません（{_log_path(server)}）")
        return conn.recv()
    except (EOFError, ConnectionError):
        raise RuntimeError(f"{server.name} の常駐が途中で終わりました（{_log_path(server)}）")
    finally:
        conn.close()
