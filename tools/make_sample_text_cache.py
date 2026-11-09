"""同梱する読み取り結果（mmd_ainakawari/text_cache）を作り直す。作る側で使う道具（zip には入れない）。

    F:\\kimodo\\.venv\\Scripts\\python.exe tools\\make_sample_text_cache.py

サンプル（mmd_ainakawari/prompt_samples.txt）の全部と、窓の最初のプロンプト（text_keys.EXTRA）を、llama-server で読み取って置く。
Llama を入れていない人も、これらの文なら Llama なしで作れる（11-10 マスター「既存のサンプルは全て事前生成」）。
一覧に無くなった文の結果は消す。手元にためた結果（work/text_cache/gguf）に同じ文があれば、ずれていないかも比べる。
llama-server と GGUF の場所は、paths.json の Kimodo の場所から決める（セットアップが置く形）。
サンプルを書き換えたら、これを回してから git add する（tests/check_text_cache_1110.py が足りない物を数える）。
"""
import os
import sys

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HOME)
sys.path.insert(0, os.path.join(HOME, "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import numpy as np  # noqa: E402

from gguf_text import LlamaServerEncoder  # noqa: E402
from mmd_ainakawari import paths, text_keys  # noqa: E402


def main():
    texts = text_keys.bundled_texts()
    log = os.path.join(HOME, "work", "llama_server_make_sample.log")
    enc = LlamaServerEncoder(paths.llama_server(), paths.text_gguf(), log, device="cpu")
    print(f"llama-server を起こしました（{enc.seconds_load:.1f} 秒）。{len(texts)} 文を読み取ります", flush=True)
    os.makedirs(text_keys.BUNDLED_DIR, exist_ok=True)
    keep, worst = set(), 0.0
    try:
        for t in texts:
            clean = text_keys.sanitize_text(t)
            name = text_keys.key(clean) + ".npy"
            keep.add(name)
            v = enc.embed(clean).astype(np.float32)[None]   # (1, 4096)。手元にためる物と同じ形
            old = os.path.join(text_keys.WORK_DIR, name)
            note = ""
            if os.path.isfile(old):
                d = float(np.abs(np.load(old) - v).max())
                worst = max(worst, d)
                note = f"・手元の結果との差 {d:.2e}"
            with open(os.path.join(text_keys.BUNDLED_DIR, name), "wb") as f:
                np.save(f, v)
            print(f"  {clean}{note}", flush=True)
    finally:
        enc.proc.kill()
    stale = [n for n in os.listdir(text_keys.BUNDLED_DIR) if n.endswith(".npy") and n not in keep]
    for n in stale:
        os.remove(os.path.join(text_keys.BUNDLED_DIR, n))
    print(f"置きました: {len(keep)} 文（{text_keys.BUNDLED_DIR}）・消した古い物 {len(stale)}・手元の結果との差の最大 {worst:.2e}")


if __name__ == "__main__":
    main()
