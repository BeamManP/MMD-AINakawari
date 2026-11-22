"""外からの操作の口（0.7.0。mmd-mcp の mmd_ainakawari_* のツールが、別の PC のエージェントの代わりに使う）。

窓（app.py の Hub）が、この PC の中だけで開く名前付きパイプで待つ。1 回つなぐごとに JSON の依頼を 1 つ受けて、JSON の返事を 1 つ返す。
窓・右下のパネルを外から押す形にしなかったのは、失敗が画面の文字と知らせの窓でしか分からず、知らせの窓は外から見えないまま
MMD の前に残るため（11-14 マスターと相談）。ここから来た依頼では知らせの窓を出さず、理由を返事（code と message）で返す。

依頼（どれも "protocol": 1 と "op" を付ける。"hwnd" は相手の MMD・MMM の窓。1 つしか開いていなければ省ける）:
    hello      版と protocol だけ返す
    status     その MMD の様子と、依頼（job_id を付ければその依頼・省けば一番新しい依頼）の様子
    generate   生成を頼む。すぐに番号（job の id）を返す。終わったかは status で見る
    cancel     生成の中断（MMD に書き戻す前まで）
    undo       生成前のモーションに戻す（これも番号を返す）
generate に付ける物は settings_from の説明を見る。知らない名前の項目が付いていたら断る（打ち間違いを黙って捨てない）。

返事: 通れば {"ok": true, …}、断る時は {"ok": false, "code": 決まった字, "message": 人が読む文}。
依頼の様子（job）の state は running（作っている）→ committing（MMD に書き戻している。もう中断できない）→ done / failed / cancelled。
undo は running → done / failed。

守っていること:
- 口はこの PC の中だけ（PIPE_REJECT_REMOTE_CLIENTS）。合言葉は付けない（同じ PC の同じ人のプログラムは、もともと窓を操作できる）
- 中身は JSON だけ（pickle を通さない）。1 通は MAX_BYTES まで
- 口のスレッドは tk を触らない。依頼は Hub の requests に入れて、tk のスレッド（Hub._poll）が handle を呼ぶ。
  tk が取りに来ない・答えない時は、期限で断る（待ち続けない）。期限で諦めた依頼を、後から tk が実行しないように Slot で受け渡す
"""
import collections
import json
import threading
import time
import uuid

import pywintypes
import win32event
import win32file
import win32pipe
import winerror

from . import __version__, applog, errors, i18n, runner, thin
from .i18n import _

PROTOCOL = 1
PIPE = r"\\.\pipe\AINakawari.Control.v1"   # 開発版は後ろに .<AINAKAWARI_INSTANCE>（app.py）。mmd-mcp の ainakawari.py と同じ
MAX_BYTES = 64 * 1024
READ_WAIT = 2.0     # つないでから依頼が届くまで・返事を相手が読み終えるまで
TAKE_WAIT = 5.0     # tk のスレッドが依頼を取りに来るまで（Hub._poll は 0.1 秒ごと）
REPLY_WAIT = 15.0   # 取ってから答えるまで（隠した窓を作る・MMD の選んだキーを読むなど。ふつうは 1 秒もかからない）
JOBS_KEPT = 50
LOG_KEPT = 40
TERMINAL = ("done", "failed", "cancelled")
_FIRST_INSTANCE = 0x00080000        # FILE_FLAG_FIRST_PIPE_INSTANCE（同じ名前の口がもうあれば作らない）
_REJECT_REMOTE = 0x00000008         # PIPE_REJECT_REMOTE_CLIENTS

# generate で省いた項目の値。作風に関わる物は、窓に保存してある設定を引き継がずにここで決める（11-14 マスター「分けるで」。
# 窓の seed が固定だと同じ頼み方のたびに同じ動きが返り、窓で試した効きや「全ての親に載せる」が外からの結果に効いてしまう）。
# 値は窓の最初の設定（app.DEFAULTS）と同じ（tests/check_control_1114.py が突き合わせる）。
# この PC に合わせた物（MACHINE_KEYS。Llama を使うか・間引き）だけ、窓の保存してある設定から引き継ぐ
REMOTE_DEFAULTS = {"steps": 100, "seed": -1, "post_processing": True, "cfg_text": 2.0, "cfg_key": 2.0,
                   "stop_at_last_key": True, "smooth_stop": True, "key_stop": False, "wrist_lerp": False,
                   "root_move": False, "root_turn": False}
MACHINE_KEYS = ("use_llama", "thin", "thin_nakawari")
ENGINES = ("kimodo", "motionbricks")
MODES = ("fill", "extend", "fresh", "center")
# 依頼に付けられる項目（generate 以外でも、知らない名前は断る）
FIELDS = {"protocol", "op", "hwnd", "job_id", "engine", "mode", "prompt", "range", "length", "steps", "seed",
          "post_processing", "cfg_text", "cfg_key", "stop_at_last_key", "smooth_stop", "key_stop", "wrist_lerp", "thin",
          "use_llama", "root_move", "root_turn"}


class Refused(Exception):
    """依頼を断る（code は決まった字・文は人が読む物）。"""

    def __init__(self, code, message, **extra):
        super().__init__(message)
        self.code = code
        self.extra = extra

    def reply(self):
        return {"ok": False, "code": self.code, "message": str(self), **self.extra}


def about():
    return {"name": "AINakawari", "version": __version__, "protocol": PROTOCOL}


def pipe_name(instance=""):
    return PIPE + (f".{instance}" if instance else "")


# ---------------- 依頼 → 生成の設定 ----------------

def _typed(req, key, kinds, what):
    value = req.get(key)
    if value is None:
        return None
    if isinstance(value, bool) != (kinds is bool) or not isinstance(value, kinds):
        raise Refused("bad_request", _("{key} は{what}で指定してください", key=key, what=what))
    return value


def _int(req, key, default=None, low=None, high=None):
    value = _typed(req, key, int, _("整数"))
    if value is None:
        return default
    if (low is not None and value < low) or (high is not None and value > high):
        raise Refused("bad_request", _("{key} は {low}〜{high} で指定してください", key=key,
                                       low="" if low is None else low, high="" if high is None else high))
    return value


def _number(req, key, default, low, high):
    value = _typed(req, key, (int, float), _("数"))
    if value is None:
        return float(default)
    if not low <= value <= high:
        raise Refused("bad_request", _("{key} は {low}〜{high} で指定してください", key=key, low=low, high=high))
    return float(value)


def _flag(req, key, default):
    value = _typed(req, key, bool, _("true か false"))
    return bool(default) if value is None else value


def _choice(req, key, choices, default):
    value = req.get(key, default)
    if value not in choices:
        raise Refused("bad_request", _("{key} は {choices} のどれかで指定してください", key=key, choices=" / ".join(choices)))
    return value


def _range(req, selected_keys):
    """作り直す範囲 (始まり, 終わり)。全部なら None。selected_keys: MMD のタイムラインで選んでいるキーのフレームを読む関数。"""
    value = req.get("range", "selected_keys")
    if value == "all":
        return None
    if value == "selected_keys":
        try:
            keys = selected_keys()
        except Exception as e:   # 選び替えの途中など。理由をそのまま返す
            raise Refused("keys_unreadable", _("選んだキーを読めません（{why}）", why=errors.explain(e))) from None
        if keys is None or len(keys) < 2:
            raise Refused("range_required", _("MMD のタイムラインで、作り直す範囲の最初と最後のキーを選んでください（2 つ以上のフレーム）"))
        return keys[0], keys[-1]
    if isinstance(value, dict) and set(value) == {"start", "end"}:
        start, end = _int(value, "start", low=0), _int(value, "end", low=0)
        if start is not None and end is not None:
            if end - start < 1:
                raise Refused("bad_request", _("範囲は 2 フレーム以上にしてください"))
            return start, end
    raise Refused("bad_request", _('range は "selected_keys"・"all"・start と end のフレームを入れたオブジェクトのどれかで指定してください'))


def defaults_for(cfg):
    """generate で省いた項目に使う値。cfg は窓の保存してある設定（App.cfg）。"""
    return {**REMOTE_DEFAULTS, **{k: cfg[k] for k in MACHINE_KEYS}}


def settings_from(req, cfg, selected_keys, kimodo_ready, motionbricks_ready):
    """generate の依頼 → (runner.Settings, 返事に入れる要約)。窓の App._settings と同じ決まりで作る（窓の部品は読まない・設定も保存しない）。

    engine: "kimodo"（既定。プロンプトで作る）か "motionbricks"（中割り。プロンプトは使わない）
    mode（kimodo だけ）: "fill" キーの間を埋める（既定）・"extend" 続きを足す・"fresh" プロンプトだけで作る・"center" センターに合わせて作る
    prompt（kimodo では必ず）: 英語の文。行頭に「45: …」と書いた行で区間に分けられる（pipeline.prompt_segments）
    range: "selected_keys"（既定。MMD で選んだキーの最初から最後まで）・"all"・{"start": F, "end": F}
    length: extend では足すフレーム数（必ず）・fresh で range が "all" の時は作るフレーム数（必ず）
    残りは defaults_for(cfg) の値: steps・seed・cfg_text・cfg_key・post_processing・stop_at_last_key・smooth_stop・key_stop・
    wrist_lerp・root_move・root_turn は決まった既定値（REMOTE_DEFAULTS。seed は -1＝毎回違う動き）、
    use_llama・thin だけ窓の保存してある設定（この PC に合わせた物。Llama を使わない・間引き）。
    """
    cfg = defaults_for(cfg)
    engine = _choice(req, "engine", ENGINES, "kimodo")
    nakawari = engine == "motionbricks"
    mode = "fill" if nakawari else _choice(req, "mode", MODES, "fill")
    if nakawari and not motionbricks_ready:
        raise Refused("not_set_up", _("MotionBricks がまだ入っていません。詳細の窓の下の「セットアップ」で入れてください"))
    if not nakawari and not kimodo_ready:
        raise Refused("not_set_up", _("AI のモデルがまだ入っていません。下の「セットアップ」で入れてください"))
    prompt = "" if nakawari else req.get("prompt")
    if not nakawari and (not isinstance(prompt, str) or not prompt.strip()):
        raise Refused("bad_request", _("prompt（作りたい動きの英語の文）を指定してください"))
    length_in = _int(req, "length", low=1)
    selection = _range(req, selected_keys)
    in_range = selection is not None
    # 範囲を使う時は範囲の終わりまで作るので、長さは使わない（続きを足す時を除く。App._settings と同じ）
    length = length_in if mode == "fresh" and not nakawari and not in_range else None
    extend = length_in if mode == "extend" and not nakawari else None
    if mode == "extend" and extend is None:
        raise Refused("length_required", _("「続きを足す」では、足す長さ（フレーム数）を入れてください"))
    if mode == "fresh" and length is None and not in_range:
        raise Refused("length_required", _("「プロンプトだけで作る」では長さを入れてください"))
    levels = len(thin.LEVELS) - 1
    common = dict(range_start=selection[0] if selection else None, range_end=selection[1] if selection else None,
                  key_stop=_flag(req, "key_stop", cfg["key_stop"]), wrist_lerp=_flag(req, "wrist_lerp", cfg["wrist_lerp"]),
                  thin=_int(req, "thin", round(cfg["thin_nakawari" if nakawari else "thin"]), 0, levels))
    if nakawari:
        s = runner.Settings(prompt="", engine="motionbricks", **common)
    else:
        s = runner.Settings(
            prompt=prompt, steps=_int(req, "steps", int(cfg["steps"]), 1, 1000), seed=_int(req, "seed", int(cfg["seed"]), -1),
            post_processing=_flag(req, "post_processing", cfg["post_processing"]),
            cfg_text=_number(req, "cfg_text", cfg["cfg_text"], 0.0, 20.0), cfg_key=_number(req, "cfg_key", cfg["cfg_key"], 0.0, 20.0),
            length=length, extend=extend, use_keys=mode not in ("fresh", "center"), use_center=mode == "center",
            stop_at_last_key=mode == "fill" and _flag(req, "stop_at_last_key", cfg["stop_at_last_key"]),
            smooth_stop=_flag(req, "smooth_stop", cfg["smooth_stop"]) and motionbricks_ready, engine="kimodo",
            use_llama=_flag(req, "use_llama", cfg["use_llama"]),
            root_move=_flag(req, "root_move", cfg["root_move"]), root_turn=_flag(req, "root_turn", cfg["root_turn"]), **common)
    summary = {"engine": engine, "mode": mode, "prompt": s.prompt, "range": list(selection) if selection else "all",
               "length": length if length is not None else extend, "steps": s.steps, "seed": s.seed, "thin": s.thin}
    return s, summary


# ---------------- 依頼の記録 ----------------

class Jobs:
    """外から頼まれた生成・元に戻すの記録（Hub が持つ。窓を作り直しても残る）。触るのは tk のスレッドだけ。
    番号は窓のプロセスを起動し直しても重ならない（起動し直すと前の記録は消え、status は unknown_job を返す）。"""

    def __init__(self):
        self._jobs = collections.OrderedDict()

    def new(self, kind, hwnd, request=None):
        job = {"id": uuid.uuid4().hex[:12], "kind": kind, "hwnd": hwnd, "state": "running", "committed": False,
               "cancel_requested": False, "started": time.time(), "finished": None, "message": "", "error": None,
               "request": request or {}, "result": None, "log": collections.deque(maxlen=LOG_KEPT)}
        self._jobs[job["id"]] = job
        while len(self._jobs) > JOBS_KEPT:
            self._jobs.popitem(last=False)
        return job

    def get(self, job_id):
        return self._jobs.get(job_id)

    def latest(self, hwnd):
        return next((j for j in reversed(self._jobs.values()) if j["hwnd"] == hwnd), None)


def commit(job):
    """MMD への書き戻しが始まった（ここからは中断できない・MMD のキーが変わりうる）。"""
    job["state"], job["committed"] = "committing", True


def finish(job, outcome, message, result=None):
    """outcome: "done"・"failed"・"cancelled"。窓が「終わった」と見るのと同じ時に呼ぶ（busy が下りる前に終わりと答えない）。"""
    job["state"], job["message"], job["finished"] = outcome, message, time.time()
    if outcome == "failed":
        job["error"] = message
    if outcome == "done" and isinstance(result, dict) and job["kind"] == "generate":
        # 書き戻したフレームの範囲は入れない（生成の Job の長さには、前後のつなぎ用の余分なフレームも入っていて紛らわしい）。
        # 頼んだ範囲は request にある。中身を確かめたい時は output（書き戻した VMD）を読む
        job["result"] = {"span": result.get("span"), "model": result.get("model"), "output": result.get("output"),
                         "backup": result.get("backup"), "root_written": bool(result.get("root_written"))}


def public(job):
    """返事に入れる形。"""
    end = job["finished"] or time.time()
    return {"id": job["id"], "kind": job["kind"], "hwnd": job["hwnd"], "state": job["state"], "committed": job["committed"],
            "cancel_requested": job["cancel_requested"], "seconds": round(end - job["started"], 1),
            "message": job["message"], "error": job["error"], "request": job["request"], "result": job["result"],
            "log": list(job["log"])}


# ---------------- 依頼をさばく（tk のスレッド） ----------------

def _hwnd(req):
    value = req.get("hwnd")
    if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
        raise Refused("bad_request", _("{key} は{what}で指定してください", key="hwnd", what=_("整数")))
    return value


def _job_of(hub, app, req):
    job_id = req.get("job_id")
    if job_id is None:
        return hub.jobs.latest(app.mmd.hwnd)
    job = hub.jobs.get(job_id) if isinstance(job_id, str) else None
    if job is None or job["hwnd"] != app.mmd.hwnd:
        raise Refused("unknown_job", _("その番号の依頼は見つかりません（{name} を起動し直すと、前の番号は消えます）", name=i18n.name()))
    return job


def _status(hub, app, req):
    job = _job_of(hub, app, req)
    return {"ok": True, **about(), **app.remote_state(), "job": public(job) if job else None}


def _generate(hub, app, req):
    return {"ok": True, "job": public(app.remote_generate(req))}


def _cancel(hub, app, req):
    job_id = req.get("job_id")
    if job_id is not None:
        _job_of(hub, app, req)
    job = app.remote_cancel(job_id)
    return {"ok": True, "job": public(job) if job else None}


def _undo(hub, app, req):
    return {"ok": True, "job": public(app.remote_undo())}


OPS = {"status": _status, "generate": _generate, "cancel": _cancel, "undo": _undo}


def handle(hub, req):
    """依頼 1 つをさばいて返事を作る（tk のスレッドで呼ぶ）。断る時も例外にせず返事にする。"""
    try:
        if not isinstance(req, dict):
            raise Refused("bad_request", _("依頼は JSON のオブジェクトで送ってください"))
        if req.get("protocol") != PROTOCOL:
            raise Refused("protocol_mismatch", _("protocol が合いません（こちらは {ours}）", ours=PROTOCOL), **about())
        unknown = sorted(set(req) - FIELDS)
        if unknown:
            raise Refused("bad_request", _("知らない項目があります: {names}", names=", ".join(unknown)))
        op = req.get("op")
        if op == "hello":
            return {"ok": True, **about()}
        if op not in OPS:
            raise Refused("bad_request", _("op は {choices} のどれかで指定してください", choices=" / ".join(["hello", *OPS])))
        app = hub.control_app(_hwnd(req))
        with i18n.use(app.lang):   # 断る文・ログを、その MMD の窓の言葉で
            return OPS[op](hub, app, req)
    except Refused as e:
        return e.reply()
    except Exception as e:   # 口を落とさない。どこで落ちたかは記録に
        applog.exception("外からの依頼の途中:")
        return {"ok": False, "code": "internal", "message": errors.explain(e), "detail": f"{type(e).__name__}: {e}"}


# ---------------- 口（別のスレッド） ----------------

class Slot:
    """口のスレッドから tk のスレッドへ渡す依頼 1 つ。tk が取る前に口が諦めたら、tk は実行しない（どちらが先かを 1 つの錠で決める）。"""

    def __init__(self, request):
        self.request = request
        self.reply = None
        self.taken = threading.Event()
        self.done = threading.Event()
        self._abandoned = False
        self._lock = threading.Lock()

    def take(self):
        with self._lock:
            if self._abandoned:
                return False
            self.taken.set()
            return True

    def abandon(self):
        with self._lock:
            if self.taken.is_set():
                return False
            self._abandoned = True
            return True

    def answer(self, reply):
        self.reply = reply
        self.done.set()


class _Gone(Exception):
    """相手がいなくなった・期限が来た・1 通が大きすぎる。"""


def _event():
    return win32event.CreateEvent(None, True, False, None)


def _finish_io(pipe, overlapped, seconds):
    if win32event.WaitForSingleObject(overlapped.hEvent, int(seconds * 1000)) != win32event.WAIT_OBJECT_0:
        win32file.CancelIo(pipe)
        win32event.WaitForSingleObject(overlapped.hEvent, 1000)   # 取り消しが済むまで（バッファを手放す前に）
        raise _Gone("timeout")
    try:
        return win32file.GetOverlappedResult(pipe, overlapped, False)
    except pywintypes.error as e:   # 途中で切れた・1 通が MAX_BYTES より大きい（ERROR_MORE_DATA）
        raise _Gone(str(e)) from None


def read_message(pipe, seconds):
    overlapped = pywintypes.OVERLAPPED()
    overlapped.hEvent = _event()
    buffer = win32file.AllocateReadBuffer(MAX_BYTES)
    try:
        win32file.ReadFile(pipe, buffer, overlapped)
    except pywintypes.error as e:
        raise _Gone(str(e)) from None
    return bytes(buffer[:_finish_io(pipe, overlapped, seconds)])


def write_message(pipe, data, seconds):
    overlapped = pywintypes.OVERLAPPED()
    overlapped.hEvent = _event()
    try:
        win32file.WriteFile(pipe, data, overlapped)
    except pywintypes.error as e:
        raise _Gone(str(e)) from None
    _finish_io(pipe, overlapped, seconds)


class Server:
    """名前付きパイプの口。submit(slot) は依頼を tk のスレッドへ渡す関数（Hub.requests に入れる）。"""

    def __init__(self, name, submit, take_wait=TAKE_WAIT, reply_wait=REPLY_WAIT):
        self.name = name
        self.submit = submit
        self.take_wait = take_wait
        self.reply_wait = reply_wait
        self._stop = _event()
        self._thread = None
        self._first = None

    def _create(self, first=False):
        return win32pipe.CreateNamedPipe(
            self.name, win32pipe.PIPE_ACCESS_DUPLEX | win32file.FILE_FLAG_OVERLAPPED | (_FIRST_INSTANCE if first else 0),
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT | _REJECT_REMOTE,
            win32pipe.PIPE_UNLIMITED_INSTANCES, MAX_BYTES, MAX_BYTES, 0, None)

    def start(self):
        """口を開く。同じ名前の口がもうある（ほかのプログラムが先に作った）時は pywintypes.error。"""
        self._first = self._create(first=True)
        self._thread = threading.Thread(target=self._serve, name="ainakawari-control", daemon=True)
        self._thread.start()

    def stop(self):
        win32event.SetEvent(self._stop)
        if self._thread:
            self._thread.join(3)

    def _stopped(self, seconds=0.0):
        return win32event.WaitForSingleObject(self._stop, int(seconds * 1000)) == win32event.WAIT_OBJECT_0

    def _wait_client(self, pipe):
        """客がつなぐまで待つ。止められたら False。つないですぐ切った客は _Gone。"""
        overlapped = pywintypes.OVERLAPPED()
        overlapped.hEvent = _event()
        try:
            if win32pipe.ConnectNamedPipe(pipe, overlapped) == winerror.ERROR_PIPE_CONNECTED:
                return True   # 口を作ってから待つまでの間に、もうつながっていた
        except pywintypes.error as e:   # 待つ前につないで、もう切っていた（ERROR_NO_DATA）
            raise _Gone(str(e)) from None
        got = win32event.WaitForMultipleObjects([overlapped.hEvent, self._stop], False, win32event.INFINITE)
        if got != win32event.WAIT_OBJECT_0:
            win32file.CancelIo(pipe)
            return False
        return True

    def _next(self):
        try:
            return self._create()
        except pywintypes.error as e:
            applog.write(f"外からの操作の次の口を作れません: {e}")
            return None

    def _serve(self):
        waiting = self._first
        try:
            while True:
                while waiting is None:   # 次の口を作れなかった。少し待って作り直す
                    if self._stopped(1.0):
                        return
                    waiting = self._next()
                pipe, waiting = waiting, None
                try:
                    if not self._wait_client(pipe):
                        return
                    # 次の客の口を先に用意する（口が 1 つも無い瞬間があると、相手には「動いていない」と見える）
                    waiting = self._next()
                    self._talk(pipe)
                except _Gone:
                    pass   # 相手が途中でやめた。こちらは次の客へ
                except Exception:
                    applog.exception("外からの操作の口:")
                finally:
                    if waiting is None:   # つないですぐ切った客など。この口を閉じる前に、次の口を作っておく
                        waiting = self._next()
                    try:
                        win32pipe.DisconnectNamedPipe(pipe)
                    except pywintypes.error:
                        pass
                    pipe.Close()
        finally:
            if waiting is not None:
                waiting.Close()

    def _talk(self, pipe):
        raw = read_message(pipe, READ_WAIT)
        try:
            request = json.loads(raw.decode("utf-8"))
        except ValueError:   # JSON でない・UTF-8 でない（UnicodeDecodeError も ValueError）
            reply = Refused("bad_request", _("依頼は JSON のオブジェクトで送ってください")).reply()
        else:
            reply = self._ask(request)
        data = json.dumps(reply, ensure_ascii=False).encode("utf-8")
        if len(data) > MAX_BYTES:
            applog.write(f"外からの依頼の返事が大きすぎます（{len(data)} バイト）")
            data = json.dumps({"ok": False, "code": "internal", "message": "reply too large"}).encode("utf-8")
        write_message(pipe, data, READ_WAIT)
        try:
            read_message(pipe, READ_WAIT)   # 相手が読み終えて閉じるのを待つ（先に切ると、返事が届かないことがある）
        except _Gone:
            pass

    def _ask(self, request):
        slot = Slot(request)
        self.submit(slot)
        if not slot.taken.wait(self.take_wait) and slot.abandon():
            return Refused("ui_busy", _("{name} の窓が応答しません。少し待ってから、もう一度頼んでください", name=i18n.name())).reply()
        if not slot.done.wait(self.reply_wait):
            return Refused("ui_timeout", _("{name} の返事が間に合いませんでした。頼んだ事は受け付けられたかもしれません。status で確かめてください",
                                           name=i18n.name())).reply()
        return slot.reply
