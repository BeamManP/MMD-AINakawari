"""Kimodo の文の読み取り（LLM2Vec ＋ Llama 3 8B Instruct）を、Hugging Face の申請なしで使えるように置く。

Kimodo の Python で回す:
    F:\\kimodo\\.venv\\Scripts\\python.exe tools\\prepare_text_encoder.py F:\\kimodo\\text_encoders [--reuse F:\\kimodo\\hf_cache]

Kimodo は元の Llama を meta-llama/Meta-Llama-3-8B-Instruct（申請が要る）から取りに行く。ここでは、
重みを申請の要らない写し（NousResearch。Llama 3 のライセンス文つきの再配布）から取り、
中身が Meta の物と同じかを sha256 で照らしてから置く。LLM2Vec のアダプタの設定は、元の場所を手元のフォルダに書き換える。
置いたフォルダは、Kimodo の環境変数 TEXT_ENCODERS_DIR で読ませる（mmd_ainakawari/pipeline.py・tools/start_textencoder.cmd）。

名前の扱い: LLM2Vec は model.config._name_or_path が "meta-llama/Meta-Llama-3-8B-Instruct" の時だけ、文の前後に
Llama 3 の印を付ける。手元のフォルダから読むと、mntp の config.json の _name_or_path（元の名前のまま）を使い直すので、印は今までと同じ。

--reuse: Hugging Face のキャッシュに同じ重み（ファイル名が sha256 の blob）があれば、落とし直さずにそれを使う（同じドライブならハードリンク）。

途中で止めても、もう一度回せば続きから直る（11-05 Codex のレビュー）:
    - 重みは全部 sha256 で照らす（置いてある物・キャッシュの物も）。照らした物は大きさと更新時刻を .verified.json に残し、
      次からは変わっていなければ照らし直さない
    - アダプタは .download\\ に原本を落とし（huggingface_hub がそこで落とし直しを判断する）、使う方へ写す。
      書き換えた設定は一時ファイルに書いてから入れ替える
    - 全部終わったら READY を置く。生成側（mmd_ainakawari/pipeline.py）は READY を見る
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

from huggingface_hub import hf_hub_download, snapshot_download

LLAMA_MIRROR = "NousResearch/Meta-Llama-3-8B-Instruct"
LLAMA_MIRROR_REVISION = "53346005fb0ef11d3b6a83b12c895cca40156b6c"
LLAMA_DIR = os.path.join("meta-llama", "Meta-Llama-3-8B-Instruct")
# Meta の meta-llama/Meta-Llama-3-8B-Instruct と同じ中身（2026-11-05 に、Meta から落とした物と写しの記録の両方で照らした）
LLAMA_FILES = {
    "config.json": "61f3de03a16ca8046b05dc777bce72717022bc8522152eee61a69072272ef54b",
    "model.safetensors.index.json": "146776fce3f6db1103aa6f249e65ee5544c5923ce6f971b092eee79aa6e5d37b",
    "model-00001-of-00004.safetensors": "d8cf9c4d0dd972e1a2131bfe656235ee98221679711a3beef6d46dadf0f20b5c",
    "model-00002-of-00004.safetensors": "8d4782b4a69ef03845159ce1a15e272aadaaf134dc138d68f616098e8531729c",
    "model-00003-of-00004.safetensors": "3acdd690e65c24f42a24581b8467af98bd3ca357444580f8012aacd2bd607921",
    "model-00004-of-00004.safetensors": "67e9ad31c8c32abf3a55ee7fc7217b3ecb35fd3c74d98a5bd233e0e4d6964f46",
}
LLAMA_LICENSE_FILES = ("LICENSE", "USE_POLICY.md")   # Llama 3 のライセンスと使い方の決まり（写しに付いている物）

# LLM2Vec のアダプタ（MIT・申請なし）。Kimodo の TEXT_ENCODER_PRESETS の名前のまま置く。版は 2026-11-05 に動かした物
MNTP = "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp"
SUPERVISED = "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp-supervised"
ADAPTERS = {
    MNTP: "31474e395ada192e8ed1586db6be79fb3b70c9c0",
    SUPERVISED: "baa8ebf04a1c2500e61288e7dad65e8ae42601a7",
}
READY = "READY"            # 全部置けた印（mmd_ainakawari/pipeline.py が見る）
VERIFIED = ".verified.json"
DOWNLOAD = ".download"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def remove(path):
    if os.path.lexists(path):
        os.remove(path)


def find_blob(cache, digest):
    """HF のキャッシュ（models--*/blobs/<sha256>）から同じ名前の物を探す。中身は呼ぶ側で照らす。"""
    if not cache or not os.path.isdir(cache):
        return None
    for name in os.listdir(cache):
        blob = os.path.join(cache, name, "blobs", digest)
        if name.startswith("models--") and os.path.isfile(blob):
            return os.path.realpath(blob)   # blob がリンクのこともある（キャッシュを移した時など）。リンクのリンクを作らない
    return None


class Verified:
    """照らし済みの記録（名前 → [大きさ, 更新時刻, sha256]）。大きさか更新時刻が変われば照らし直す。"""

    def __init__(self, folder):
        self.path = os.path.join(folder, VERIFIED)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def ok(self, folder, name, digest):
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            return False
        st = os.stat(path)
        if self.data.get(name) == [st.st_size, st.st_mtime_ns, digest]:
            return True
        print(f"照らしています: {name}", flush=True)
        if sha256(path) != digest:
            return False
        self.mark(folder, name, digest)
        return True

    def mark(self, folder, name, digest):
        st = os.stat(os.path.join(folder, name))
        self.data[name] = [st.st_size, st.st_mtime_ns, digest]
        write_atomic(self.path, json.dumps(self.data, indent=1))


def place_llama(dest, reuse):
    folder = os.path.join(dest, LLAMA_DIR)
    os.makedirs(folder, exist_ok=True)
    downloads = os.path.join(dest, DOWNLOAD, "llama")
    verified = Verified(folder)
    for name, digest in LLAMA_FILES.items():
        target = os.path.join(folder, name)
        if verified.ok(folder, name, digest):
            continue
        if os.path.lexists(target):
            print(f"中身が Meta の物と違うので置き直します: {name}", flush=True)
            remove(target)
        partial = target + ".partial"
        remove(partial)   # 前に途中で止まった残り（キャッシュへのハードリンクのこともある。消してもキャッシュは残る）
        blob = find_blob(reuse, digest)
        if blob:
            print(f"手元のキャッシュから使います: {name}", flush=True)
            try:
                os.link(blob, partial)
            except OSError:
                shutil.copyfile(blob, partial)
            print(f"照らしています: {name}", flush=True)
            if sha256(partial) != digest:
                print(f"キャッシュの中身が違ったので、落とします: {name}", flush=True)
                remove(partial)
                blob = None
        if not blob:
            print(f"落とします: {name}（{LLAMA_MIRROR}）", flush=True)
            got = hf_hub_download(LLAMA_MIRROR, name, revision=LLAMA_MIRROR_REVISION, local_dir=downloads)
            print(f"照らしています: {name}", flush=True)
            actual = sha256(got)
            if actual != digest:
                remove(got)
                raise SystemExit(f"{name} の中身が Meta の物と違います（{actual}）。置かずに止めます")
            os.replace(got, partial)
        os.replace(partial, target)
        verified.mark(folder, name, digest)
    for name in LLAMA_LICENSE_FILES:
        target = os.path.join(folder, name)
        if not os.path.isfile(target):
            got = hf_hub_download(LLAMA_MIRROR, name, revision=LLAMA_MIRROR_REVISION, local_dir=downloads)
            shutil.copyfile(got, target + ".partial")
            os.replace(target + ".partial", target)
    shutil.rmtree(downloads, ignore_errors=True)
    return folder


def copy_tree(src, dst):
    """src の中身を dst に写す（大きい物はハードリンク）。.cache（huggingface_hub の記録）は写さない。"""
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != ".cache"]
        out = os.path.join(dst, os.path.relpath(root, src))
        os.makedirs(out, exist_ok=True)
        for name in files:
            target = os.path.join(out, name)
            remove(target)
            try:
                os.link(os.path.join(root, name), target)
            except OSError:
                shutil.copyfile(os.path.join(root, name), target)


def place_adapters(dest, llama):
    for repo, revision in ADAPTERS.items():
        print(f"落とします: {repo}", flush=True)
        original = os.path.join(dest, DOWNLOAD, *repo.split("/"))
        snapshot_download(repo, revision=revision, local_dir=original)   # 原本は書き換えない（落とし直しの判断を壊さない）
        copy_tree(original, os.path.join(dest, *repo.split("/")))
    # mntp は、読み込む時に adapter_config.json の元の場所から Llama を読む。そこを手元のフォルダにする
    with open(os.path.join(dest, DOWNLOAD, *MNTP.split("/"), "adapter_config.json"), encoding="utf-8") as f:
        config = json.load(f)
    config["base_model_name_or_path"] = os.path.abspath(llama)
    path = os.path.join(dest, *MNTP.split("/"), "adapter_config.json")
    remove(path)   # 原本へのハードリンクなので、書く前に切り離す
    write_atomic(path, json.dumps(config, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dest", help="置き場所（Kimodo の TEXT_ENCODERS_DIR にする）")
    parser.add_argument("--reuse", help="同じ重みが入っているかもしれない Hugging Face のキャッシュ")
    args = parser.parse_args()
    dest = os.path.abspath(args.dest)
    os.makedirs(dest, exist_ok=True)
    remove(os.path.join(dest, READY))
    llama = place_llama(dest, args.reuse)
    place_adapters(dest, llama)
    write_atomic(os.path.join(dest, READY), "ok\n")
    print(f"できました: {dest}")


if __name__ == "__main__":
    sys.exit(main())
