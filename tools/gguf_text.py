"""Kimodo の文の読み取り（LLM2Vec ＋ Llama 3 8B）を、GGUF Q8_0 と llama.cpp の llama-server（CPU）で行う。Kimodo の Python で動かす。

Kimodo 本来の LLM2VecEncoder（bfloat16・約 16GB）の代わりに load_model(text_encoder=…) に渡す。読み取りの形は同じ:
文を "<|start_header_id|>user<|end_header_id|>\\n\\n{文}<|eot_id|>" にして、最後の層の出力のうち「{文}<|eot_id|>」の
トークンだけを平均した 4096 次元を 1 本返す（LLM2Vec の mean pooling・skip_instruction。Kimodo は 1 文 1 本で使う）。

GGUF は fernandotonon/Llama-3-LLM2Vec-8B-Kimodo-TextEncoder-GGUF（mntp と supervised のアダプタを重みに混ぜ込み、
双方向の注意にしたもの）。11-07 に bf16 版と 47 文で比べて cos 平均 0.99986・最小 0.99977、作った動きのずれは
同じ seed で姿勢の平均 0.41cm（seed を変えた時の約 60 分の 1）。メインメモリは 15.9GB → 7.6GB（docs/DEVELOPMENT.md）。

llama-server は子プロセスとして 127.0.0.1 の空いた口で起こし、Windows のジョブに入れる（親が終われば子も終わる）。
"""
import ctypes
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from ctypes import wintypes

import numpy as np

HEAD = "<|start_header_id|>user<|end_header_id|>\n\n"   # LLM2Vec が Meta-Llama-3-8B-Instruct の時に付ける印
EOT = "<|eot_id|>"
DIM = 4096
CONTEXT = 512          # 1 文のトークンの上限（双方向の注意は 1 回で全部読むので、-b・-ub も同じにする）
START_TIMEOUT = 180.0  # 起動の上限（Q8_0 の 8GB をディスクから読む。2 回目からは数秒）
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class _JobLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                              "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _JobLimitEx(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _JobLimit), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _kill_with_parent(proc):
    """proc を「このプロセスが終わったら一緒に終わる」ジョブに入れる。ジョブの取っ手はプロセスが終わるまで持ち続ける。"""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.OpenProcess.restype = wintypes.HANDLE
    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW")
    info = _JobLimitEx()
    info.BasicLimitInformation.LimitFlags = 0x2000   # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):   # ExtendedLimitInformation
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject")
    handle = k32.OpenProcess(0x0001 | 0x0100, False, proc.pid)   # PROCESS_TERMINATE | PROCESS_SET_QUOTA
    if not handle or not k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(handle)):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject")
    k32.CloseHandle(wintypes.HANDLE(handle))
    return job


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _tail(path, lines=15):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:])
    except OSError:
        return ""


class LlamaServerEncoder:
    """Kimodo の text_encoder（LLM2VecEncoder と同じ呼び方: 文 → (テンソル, 長さ)。1 文は (1, 4096)・長さ 1）。"""

    def __init__(self, server_exe, gguf, log_path, device="cuda", threads=None):
        for path, what in ((server_exe, "llama.cpp（llama-server.exe）"), (gguf, "文の読み取りのモデル（GGUF）")):
            if not os.path.isfile(path):
                raise FileNotFoundError(f"{what}がありません: {path}")
        self._device = device
        self.log_path = log_path
        self.port = _free_port()
        args = [server_exe, "-m", gguf, "--embeddings", "--pooling", "none", "-c", str(CONTEXT), "-b", str(CONTEXT),
                "-ub", str(CONTEXT), "--host", "127.0.0.1", "--port", str(self.port), "--no-webui"]
        if threads:
            args += ["-t", str(threads)]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        self._log = open(log_path, "w", encoding="utf-8")
        t0 = time.time()
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=self._log, stderr=subprocess.STDOUT,
                                     creationflags=NO_WINDOW)
        try:
            self._job = _kill_with_parent(self.proc)
        except OSError:
            self.proc.kill()
            raise
        while True:
            try:
                if self._call("/health", timeout=2).get("status") == "ok":
                    break
            except (OSError, ValueError):
                pass
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server が止まりました（{log_path}）:\n{_tail(log_path)}")
            if time.time() - t0 > START_TIMEOUT:
                self.proc.kill()
                raise RuntimeError(f"llama-server が {START_TIMEOUT:.0f} 秒たっても準備できません（{log_path}）")
            time.sleep(0.3)
        self.seconds_load = time.time() - t0

    def _call(self, path, body=None, timeout=120):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     data=json.dumps(body).encode("utf-8") if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def embed(self, text):
        """1 文 → 4096 次元（float32）。"""
        body = text.strip() + EOT
        n_tail = len(self._call("/tokenize", {"content": body, "add_special": False, "parse_special": True})["tokens"])
        try:
            rows = self._call("/embedding", {"content": HEAD + body})[0]["embedding"]
        except urllib.error.HTTPError as e:   # 長すぎる文など。llama-server の言い分を出す
            raise RuntimeError(f"文の読み取りに失敗しました（{e.code}: {e.read().decode('utf-8', 'replace')[:300]}）")
        tok = np.asarray(rows, dtype=np.float32)
        if tok.ndim != 2 or tok.shape[1] != DIM or not 0 < n_tail < len(tok):
            raise RuntimeError(f"文の読み取りの結果の形が想定と違います（{tok.shape}・文の部分 {n_tail} トークン）")
        return tok[-n_tail:].mean(axis=0)

    def __call__(self, text):
        import torch

        one = isinstance(text, str)
        texts = [text] if one else list(text)
        e = torch.from_numpy(np.stack([self.embed(t) for t in texts]))[:, None].to(self._device)   # (N, 1, 4096)
        if one:
            return e[0], 1
        return e, [1] * len(texts)

    def to(self, device=None, dtype=None):
        if device is not None:
            self._device = str(device)
        return self

    def eval(self):
        return self

    def get_device(self):
        import torch
        return torch.device(self._device)

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
