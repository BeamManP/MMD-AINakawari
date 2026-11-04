"""常駐の生成サーバー（tools/kimodo_gen.py・tools/mb_gen.py の --serve）に頼む。いなければ立ち上げる。

モデルの読み込み（Kimodo は torch 込みで 25 秒・MotionBricks は 3 秒）を 1 回で済ませるため。
常駐は 127.0.0.1 の決まった口で待ち、しばらく頼まれなければ自分で終わる。窓（app.py）とは別のプロセスなので、
窓を閉じても残り、次に開いた窓からも使える。記録は work/<名前>_server.log。
"""
import os
import subprocess
import time
from dataclasses import dataclass
from multiprocessing.connection import Client

AUTHKEY = b"MMDKimodo.resident.v1"   # tools/kimodo_gen.py・tools/mb_gen.py と同じ
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")


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


def _connect(server):
    try:
        return Client(("127.0.0.1", server.port), authkey=AUTHKEY)
    except (OSError, EOFError):   # いない・終わる途中（接続を切られた）
        return None


def _log_tail(path, lines=15):
    try:
        return "\n".join(open(path, encoding="utf-8", errors="replace").read().splitlines()[-lines:])
    except OSError:
        return "（記録がありません）"


def _start(server, log):
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{server.name}_server.log")
    log(f"  {server.name} を常駐させています（初回だけモデルを読み込みます）…")
    out = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen([server.python, server.script, "--serve", str(server.port), *server.args], stdout=out, stderr=subprocess.STDOUT,
                            cwd=server.cwd, env=server.env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    out.close()
    deadline = time.monotonic() + server.start_timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"{server.name} の常駐が起動できませんでした:\n{_log_tail(log_path)}")
        conn = _connect(server)
        if conn is not None:
            return conn
        time.sleep(0.5)
    raise RuntimeError(f"{server.name} の常駐が {server.start_timeout:.0f} 秒たっても準備できません（{log_path}）")


def call(server, request, log=print):
    """依頼を送って (結果, 1 行のまとめ) を返す。

    常駐は自分の橋渡しのファイルが書き換わっていたら、作らずに stale で答えて終わる。その時は立ち上げ直して頼み直す。
    """
    reply = _send(_connect(server) or _start(server, log), server, request)
    if reply.get("stale"):
        log(f"  {server.name} の橋渡しが新しくなっていたので、常駐を立ち上げ直します…")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:   # 古い常駐が口を閉じるまで待つ
            conn = _connect(server)
            if conn is None:
                break
            conn.close()
            time.sleep(0.2)
        reply = _send(_start(server, log), server, request)
    if not reply["ok"]:
        raise RuntimeError(f"{server.name} が失敗しました:\n" + reply.get("error", "")[-1500:])
    return reply["result"], reply.get("line", "")


def shutdown(server):
    """常駐がいれば終わらせる（モードを切り替えた時に、使わない方のメモリを空ける）。終わらせたら True。"""
    conn = _connect(server)
    if conn is None:
        return False
    _send(conn, server, {"shutdown": True})
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:   # 口が閉じるまで待つ
        conn = _connect(server)
        if conn is None:
            return True
        conn.close()
        time.sleep(0.2)
    raise RuntimeError(f"{server.name} の常駐が終わりません（{os.path.join(LOG_DIR, server.name + '_server.log')}）")


def _send(conn, server, request):
    try:
        conn.send(request)
        return conn.recv()
    except EOFError:
        raise RuntimeError(f"{server.name} の常駐が途中で終わりました（{os.path.join(LOG_DIR, server.name + '_server.log')}）")
    finally:
        conn.close()
