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


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def find_blob(cache, digest):
    """HF のキャッシュ（models--*/blobs/<sha256>）から同じ中身の物を探す。"""
    if not cache or not os.path.isdir(cache):
        return None
    for name in os.listdir(cache):
        blob = os.path.join(cache, name, "blobs", digest)
        if name.startswith("models--") and os.path.isfile(blob):
            return os.path.realpath(blob)   # blob がリンクのこともある（キャッシュを移した時など）。リンクのリンクを作らない
    return None


def place_llama(dest, reuse):
    folder = os.path.join(dest, LLAMA_DIR)
    os.makedirs(folder, exist_ok=True)
    for name, digest in LLAMA_FILES.items():
        target = os.path.join(folder, name)
        if os.path.isfile(target):
            continue   # 置く時に照らしてから名前を付けているので、あれば済み
        blob = find_blob(reuse, digest)
        partial = target + ".partial"
        if blob:
            print(f"手元のキャッシュから使います: {name}", flush=True)
            try:
                os.link(blob, partial)
            except OSError:
                shutil.copyfile(blob, partial)
            # blob の名前が sha256（HF が落とした時に照らしている）なので、照らし直さない
        else:
            print(f"落とします: {name}（{LLAMA_MIRROR}）", flush=True)
            got = hf_hub_download(LLAMA_MIRROR, name, revision=LLAMA_MIRROR_REVISION, local_dir=os.path.join(dest, ".download"))
            actual = sha256(got)
            if actual != digest:
                os.remove(got)
                raise SystemExit(f"{name} の中身が Meta の物と違います（{actual}）。置かずに止めます")
            os.replace(got, partial)
        os.replace(partial, target)
    for name in LLAMA_LICENSE_FILES:
        target = os.path.join(folder, name)
        if not os.path.isfile(target):
            got = hf_hub_download(LLAMA_MIRROR, name, revision=LLAMA_MIRROR_REVISION, local_dir=os.path.join(dest, ".download"))
            os.replace(got, target)
    shutil.rmtree(os.path.join(dest, ".download"), ignore_errors=True)
    return folder


def place_adapters(dest, llama):
    for repo, revision in ADAPTERS.items():
        folder = os.path.join(dest, *repo.split("/"))
        print(f"落とします: {repo}", flush=True)
        snapshot_download(repo, revision=revision, local_dir=folder)
    # mntp は、読み込む時に adapter_config.json の元の場所から Llama を読む。そこを手元のフォルダにする
    path = os.path.join(dest, *MNTP.split("/"), "adapter_config.json")
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    config["base_model_name_or_path"] = os.path.abspath(llama)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dest", help="置き場所（Kimodo の TEXT_ENCODERS_DIR にする）")
    parser.add_argument("--reuse", help="同じ重みが入っているかもしれない Hugging Face のキャッシュ")
    args = parser.parse_args()
    dest = os.path.abspath(args.dest)
    llama = place_llama(dest, args.reuse)
    place_adapters(dest, llama)
    print(f"できました: {dest}")


if __name__ == "__main__":
    sys.exit(main())
