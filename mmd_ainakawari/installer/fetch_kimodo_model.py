"""Kimodo のモデルを Hugging Face から落とす（セットアップの段。Kimodo の Python で回す）。

    <Kimodo>\\.venv\\Scripts\\python.exe fetch_kimodo_model.py <hf_cache> <repo> <revision>

版を固定して落とし、refs\\main にその版を書く。Kimodo は LOCAL_CACHE の時、版を指定せずに（main で）キャッシュを探すが、
コミットの番号で落とすと huggingface_hub は main の目印を書かないので（tools/kimodo_gen.py は LOCAL_CACHE=true で読む）。
申請の要らないリポジトリなので、アカウントは要らない。
"""
import os
import sys

from huggingface_hub import snapshot_download


def main():
    cache, repo, revision = sys.argv[1:4]
    # できた時に出す文。言葉は呼ぶ側（steps.py）が決めて 4 つ目の引数で渡す（この Python からは i18n を読めない）
    done = sys.argv[4] if len(sys.argv) > 4 else "できました: {path}"   # i18n: skip
    path = snapshot_download(repo_id=repo, revision=revision, cache_dir=cache)
    refs = os.path.join(cache, "models--" + repo.replace("/", "--"), "refs")
    os.makedirs(refs, exist_ok=True)
    tmp = os.path.join(refs, "main.tmp")
    with open(tmp, "w", encoding="ascii") as f:
        f.write(revision)
    os.replace(tmp, os.path.join(refs, "main"))
    print(done.format(path=path), flush=True)


if __name__ == "__main__":
    main()
