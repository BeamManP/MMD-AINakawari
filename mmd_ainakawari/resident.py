"""常駐の生成サーバー（tools/kimodo_gen.py・tools/mb_gen.py の --serve）に頼む。いなければ立ち上げる。

モデルの読み込み（Kimodo は torch 込みで 25 秒・MotionBricks は 3 秒）を 1 回で済ませるため。
常駐は 127.0.0.1 の決まった口で待ち、5 分頼まれなければ自分で終わる。窓（app.py）とは別のプロセスで、
MMD が全部閉じて窓のプロセスが終わる時に stop() で終わらせる（使っていない間に約 8GB をつかみ続けないように。11-08 マスター）。
記録は work/<名前>_server.log。

窓は MMD ごとに同じプロセスのスレッドで生成するので、同じ常駐の立ち上げは口ごとのロックで 1 つずつにする。
つなぐ・答えを待つには期限を付ける（口をほかのプログラムが使っていて黙っている時に、窓が戻らなくならないように）。

中断（11-10 マスター「生成押したら中断になる感じで」）: 生成のスレッドが cancellable(印) の中で頼む。印が立つと、
立ち上げ・答え待ちをやめて Cancelled を出す。作っている途中の常駐には、頼んだ接続にそのまま {"cancel": True} を送る
（常駐は 1 ステップごとに見て、作るのをやめて次の依頼を待つ。常駐は落とさないので、次の生成でモデルを読み直さない）。
"""
import contextlib
import os
import subprocess
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client

AUTHKEY = b"AINakawari.resident.v1"   # tools/kimodo_gen.py・tools/mb_gen.py と同じ
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")
CONNECT_TIMEOUT = 5.0     # つないで合言葉を確かめるまで
REPLY_TIMEOUT = 15 * 60   # 1 回の生成の答えを待つ上限（低負荷の初回の読み取りや長い動きでも数十秒）
_start_locks = defaultdict(threading.Lock)


class _Busy(Exception):
    """口は開いているが合言葉の答えが来ない。常駐がモデルを読み込み中（口は読み込みの前に開ける）か、ほかのプログラム。"""


class Cancelled(Exception):
    """使う人が中断した（失敗ではない）。"""

    def __str__(self):
        return "中断しました"


_cancel = threading.local()   # 生成のスレッドごとの「中断の印」（threading.Event）


@contextlib.contextmanager
def cancellable(event):
    """この中で頼んだ生成は、event が立つと Cancelled で止まる（event が None なら今までどおり）。"""
    before = getattr(_cancel, "event", None)
    _cancel.event = event
    try:
        yield
    finally:
        _cancel.event = before


def cancel_requested():
    event = getattr(_cancel, "event", None)
    return event is not None and event.is_set()


def check_cancel():
    """中断が頼まれていれば Cancelled。時間のかかる所の切れ目で呼ぶ。"""
    if cancel_requested():
        raise Cancelled()


def acquire(lock):
    """lock を取る（with の代わり）。待っている間に中断されたら Cancelled。取れたら、呼んだ側が release する。"""
    while not lock.acquire(timeout=0.2):
        check_cancel()


@dataclass
class Server:
    name: str          # 記録のファイル名とメッセージ用
    port: int
    python: str
    script: str
    cwd: str
    env: dict
    args: tuple = ()             # --serve <口> の後ろに付ける引数
    start_timeout: float = 600.0   # 読み込みの上限。メモリ 16GB・GTX 1650 の PC で 180 秒を超えた報告があり 600 に（11-10）


def _log_path(server):
    return os.path.join(LOG_DIR, f"{server.name}_server.log")


def _connect(server, timeout=CONNECT_TIMEOUT):
    """つながった Connection か、いなければ None。合言葉が違う相手はエラー、timeout 秒で答えが来なければ _Busy。

    Client には期限が無いので別のスレッドでつなぎ、時間切れならあきらめた印を付ける。あきらめた接続が後でつながったら、
    そのスレッドが閉じる（置き去りの接続が常駐の受け取りをふさいで、本物の依頼が待たされないように。11-04 Codex のレビュー）。
    """
    box = {}
    lock = threading.Lock()

    def go():
        try:
            result = Client(("127.0.0.1", server.port), authkey=AUTHKEY)
        except (OSError, EOFError):   # いない・終わる途中（接続を切られた）
            result = None
        except AuthenticationError as e:
            result = e
        with lock:
            if box.get("abandoned"):
                if hasattr(result, "close"):
                    result.close()
            else:
                box["result"] = result
    threading.Thread(target=go, daemon=True).start()
    deadline = time.monotonic() + timeout
    cancelled = False
    while time.monotonic() < deadline:
        with lock:
            if "result" in box:
                break
        if cancel_requested():   # 読み込み中の常駐を待っている間に中断された
            cancelled = True
            break
        time.sleep(0.05)
    with lock:
        if "result" not in box:
            box["abandoned"] = True
            raise Cancelled() if cancelled else _Busy()
    if isinstance(box["result"], AuthenticationError):
        raise _foreign(server)
    return box["result"]


def _foreign(server):
    return RuntimeError(f"{server.name} の口（127.0.0.1:{server.port}）を、ほかのプログラムが使っているようです。"
                        f"そのプログラムを閉じてからもう一度押してください")


def _connect_waiting(server, deadline):
    """_connect と同じ。ただし読み込み中なら、1 本の接続で deadline まで待つ。過ぎたらほかのプログラムとしてエラー。"""
    try:
        return _connect(server, timeout=max(CONNECT_TIMEOUT, deadline - time.monotonic()))
    except _Busy:
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
            # 口をほかの常駐（別のプロセスの AIナカワリ が同時に立ち上げたもの）に取られて終わった時は、そちらを使う
            conn = _connect_waiting(server, deadline)
            if conn is not None:
                return conn
            raise RuntimeError(f"{server.name} の常駐が起動できませんでした:\n{_log_tail(_log_path(server))}")
        check_cancel()   # 常駐は読み込みを続ける（次の生成ですぐ使える）
        time.sleep(0.5)
    raise RuntimeError(f"{server.name} の常駐が {server.start_timeout:.0f} 秒たっても準備できません（{_log_path(server)}）")


def _ready(server, log):
    lock = _start_locks[server.port]   # 同じ常駐を 2 つ立ち上げない
    acquire(lock)
    try:
        return _connect_waiting(server, time.monotonic() + server.start_timeout) or _start(server, log)
    finally:
        lock.release()


def call(server, request, log=print):
    """依頼を送って (結果, 1 行のまとめ) を返す。

    常駐は自分の橋渡しのファイルが書き換わっていたら、作らずに stale で答えて終わる。その時は立ち上げ直して頼み直す。
    """
    check_cancel()
    reply = _send(_ready(server, log), server, request)
    if reply.get("stale"):
        log(f"  {server.name} の橋渡しが新しくなっていたので、常駐を立ち上げ直します…")
        _wait_closed(server)
        reply = _send(_ready(server, log), server, request)
    if reply.get("cancelled") or cancel_requested():   # 常駐が途中でやめた・作り終わるのと中断が行き違った（結果は捨てる）
        raise Cancelled()
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


def notify(name, port, request, wait=10.0):
    """口 port の常駐がいれば request を送って答えを返す。いなければ立ち上げずに None。

    例外は出さない（窓の終わり・設定の切り替えを止めない）。生成の途中や読み込み中で wait 秒のうちに答えない時は None。
    """
    server = Server(name, port, "", "", "", {})
    lock = _start_locks[port]
    if not lock.acquire(timeout=wait):   # 生成のスレッドが立ち上げている途中
        return None
    try:
        conn = _connect(server, timeout=wait)
        if conn is None:
            return None
        return _send(conn, server, request)
    except Exception:   # いない・ほかのプログラム・答えない
        return None
    finally:
        lock.release()


def stop(name, port, wait=10.0):
    """窓のプロセスが終わる時に、口 port の常駐がいれば終わらせる。終わらせたら True。
    答えない時は、常駐が作り終わってから自分のアイドルの時間（5 分）で終わる。"""
    return notify(name, port, {"shutdown": True}, wait) is not None


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
    told = False   # 中断を常駐に知らせたか
    try:
        conn.send(request)
        deadline = time.monotonic() + REPLY_TIMEOUT
        while not conn.poll(0.1):
            if cancel_requested() and not told:   # 同じ接続で知らせる。常駐は切れ目で見て、やめたら答える（古い橋渡しは最後まで作る）
                conn.send({"cancel": True})
                told = True
            if time.monotonic() > deadline:
                raise RuntimeError(f"{server.name} が {REPLY_TIMEOUT // 60} 分たっても答えません（{_log_path(server)}）")
        return conn.recv()
    except (EOFError, ConnectionError):
        if told:   # 中断を知らない橋渡しが、知らせを読まないまま接続を閉じた（結果は届かない）。頼んだのは中断なので、中断として扱う
            raise Cancelled()
        raise RuntimeError(f"{server.name} の常駐が途中で終わりました（{_log_path(server)}）")
    finally:
        conn.close()
