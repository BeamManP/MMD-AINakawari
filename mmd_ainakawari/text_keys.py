"""プロンプトの読み取り結果（1 文 4096 個の数・約 16KB の .npy）の置き場と鍵。窓（Python 3.10・torch なし）と常駐の Kimodo の両方から使う。

読み取り結果は 2 か所から引く（tools/gguf_text.py の CachedText）:
    同梱   mmd_ainakawari/text_cache/<鍵>.npy                 サンプルの文と窓の最初の文。作る側で先に作って zip に入れる
                                                               （tools/make_sample_text_cache.py。11-10 マスター「既存のサンプルは全て事前生成」）
    手元   work/text_cache/gguf/kimodo-soma-rp/<鍵>.npy       使った文をためる（11-07 から。公式デモの CachedTextEncoder と同じ置き方）
どちらにも無い文だけ、Llama（llama-server）を起こして読み取る。Llama を入れていなければ読み取れないので、生成の前に止める。

鍵は公式デモの CachedTextEncoder（kimodo/demo/embedding_cache.py）と同じ作り方にしてある（11-07 からためた結果をそのまま使うため）:
    sha256("kimodo-soma-rp|LlamaServerEncoder|" + 整えた文)
「LlamaServerEncoder」は 11-07 に読み取り役のクラスの名前から付いた物で、もう名前とは関係ない。変えると、ためた結果が全部外れる。
文の整え方（sanitize_text）は Kimodo の kimodo/sanitize.py（Apache-2.0・NVIDIA）を写した物。窓の Python に Kimodo が無いので写した。
変わっていないかは tests/check_text_cache_1110.py が Kimodo の物と比べる。
"""
import hashlib
import os

HOME = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = "kimodo-soma-rp"
ENCODER_ID = "LlamaServerEncoder"
BUNDLED_DIR = os.path.join(HOME, "mmd_ainakawari", "text_cache")
WORK_DIR = os.path.join(HOME, "work", "text_cache", "gguf", MODEL)
DIM = 4096
# サンプル（prompt_samples.txt）のほかに同梱する文。窓の最初のプロンプト（app.py の DEFAULTS["prompt"]）
EXTRA = ("A person moves naturally between poses.",)


def sanitize_text(text):
    """Kimodo の sanitize_text（paragraph=True）と同じ整え方: 前後と重なった空白を消す・頭の記号を消す・頭を大文字・終わりに「.」。"""
    text = " ".join(text.strip().split())
    if text == "":
        return text
    for i, c in enumerate(text):
        if not str.isalnum(c):
            continue
        break
    text = text[i:]
    text = text.capitalize()
    final_punctuations = ".!?\"])'"
    for i, c in reversed(list(enumerate(text))):
        if not str.isalnum(c) and c not in final_punctuations:
            continue
        break
    text = text[: i + 1]
    if text[-1] not in ".!?":
        text = text + "."
    for sentence_break in ".!?":
        subtexts = text.split(sentence_break)
        text = f"{sentence_break} ".join(
            [y[0].capitalize() + y[1:] if y else y for x in subtexts for y in [x.strip()]]
        ).strip()
    return text


def key(text):
    """整えた文の鍵（.npy の名前）。"""
    return hashlib.sha256(f"{MODEL}|{ENCODER_ID}|{text}".encode("utf-8")).hexdigest()


def find(text):
    """文（整える前でよい）の読み取り結果のファイル。同梱 → 手元の順。空の文と、どちらにも無い文は None。"""
    return find_clean(sanitize_text(text))


def find_clean(clean):
    """整えた後の文の読み取り結果のファイル（find と同じ。整えるのを 2 回しない）。"""
    if not clean:
        return None
    name = key(clean) + ".npy"
    for folder in (BUNDLED_DIR, WORK_DIR):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def missing(texts):
    """読み取り結果の無い文（空の文は Llama に聞かずに 0 で済むので、無くてよい）。並びは渡した順・重なりは 1 つに。"""
    out = []
    for t in texts:
        if sanitize_text(t) and find(t) is None and t.strip() not in out:
            out.append(t.strip())
    return out


def bundled_texts():
    """同梱する文の一覧（サンプルの全部と EXTRA）。"""
    from . import samples
    texts = [prompt for _name, items in samples.load() for _label, prompt in items] + list(EXTRA)
    return list(dict.fromkeys(texts))
