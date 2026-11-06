"""セットアップが落とす物の版（確かめた物に固定する。11-05 マスター「固定でいきたい」）。

どれも 11-02〜11-05 にマスターの F:\\kimodo・F:\\motionbricks で動かして確かめた版。上げる時は、ここと
kimodo-requirements.txt を変えて、まっさらな場所へのセットアップと試しの生成を通してから。
GitHub の zip はコミットの番号で取る（中身はその番号で決まる。zip そのもののバイト列は GitHub が作り直すことがあるので照らさない）。
"""

# Kimodo（NVIDIA・コードは Apache-2.0）。2026-10-15 のコミット
KIMODO_COMMIT = "e1c219c99b4b94ba48be1fb6a1cbc64ecee4c954"
KIMODO_ZIP = f"https://github.com/nv-tlabs/kimodo/archive/{KIMODO_COMMIT}.zip"
KIMODO_PYTHON = "3.10.19"
# Kimodo のモデル（NVIDIA Open Model License）。Kimodo は LOCAL_CACHE の時に refs\main から探すので、落とした後に main の目印を書く
KIMODO_MODEL_REPO = "nvidia/Kimodo-SOMA-RP-v1.2"
KIMODO_MODEL_REVISION = "0e3c89024d896064b6851201373f7834784a386b"

# 文の読み取り（LLM2Vec ＋ Llama 3 8B を GGUF Q8_0 にした物。Meta Llama 3 Community License・LLM2Vec のアダプタは MIT）。
# 第三者（fernandotonon さん）のリポジトリなので、コミットで固定する（11-07 マスター判断。消えたら写しを置くか考える）
TEXT_GGUF_REPO = "fernandotonon/Llama-3-LLM2Vec-8B-Kimodo-TextEncoder-GGUF"
TEXT_GGUF_REVISION = "d9931ecb2e20c7f0fd6c86284cd00eb83154bdf9"
TEXT_GGUF_URL = "https://huggingface.co/{repo}/resolve/{revision}/{name}"
TEXT_GGUF_FILE = ("Llama-3-LLM2Vec-8B-Kimodo-TextEncoder-Q8_0.gguf",
                  "332f86e0b7f5eb022795bd00507245d2efe12f5b5057cedcce678d8a32ad4ce6", 7982601376)
# 一緒に置くライセンスの文（コミットで中身が決まるので照らさない）
TEXT_GGUF_LICENSES = ("LICENSE-Llama-3.txt", "USE_POLICY-Llama-3.md", "NOTICE-Llama-3.txt", "LICENSE-LLM2Vec-MIT.txt", "README.md")

# llama.cpp（MIT）の CPU 版。文の読み取りの llama-server だけを使う。2026-11-06 のビルド（GitHub の記録の sha256 と照らした）
LLAMACPP_BUILD = "b12170"
LLAMACPP_ZIP = (f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMACPP_BUILD}/llama-{LLAMACPP_BUILD}-bin-win-cpu-x64.zip",
                "29ca39fe6ac853b735738cf28aabfe9a9af6bf502f34f52d43c1a24d61d69450", 24745645)

# MotionBricks（NVIDIA・コードは Apache-2.0、モデルは NVIDIA Open Model Agreement）。2026-10-23 のコミット
MOTIONBRICKS_COMMIT = "54fc563aeaaf819a753d72cc9fdc6713989cdd43"
MOTIONBRICKS_ZIP = f"https://github.com/NVlabs/motionbricks/archive/{MOTIONBRICKS_COMMIT}.zip"
# マスターの F:\motionbricks\.venv と同じ版。.python-version（3.12）に任せると、UV_NO_CONFIG の下では uv が 3.14 を選び、
# TensorRT（tensorrt-cu12-bindings 10.8）に 3.14 の部品が無くて止まった（11-06）
MOTIONBRICKS_PYTHON = "3.12.12"
# GitHub の zip の LFS のファイルは目印（ポインタ）だけなので、使う物だけを LFS の URL から落とす。
# LFS の識別子はそのまま中身の sha256。ロボット（unitree_g1）・見本のモーション・説明の画像は使わないので落とさない
MOTIONBRICKS_LFS_URL = "https://media.githubusercontent.com/media/NVlabs/motionbricks/{commit}/{path}"
MOTIONBRICKS_LFS = {
    "motionbricks/assets/onnx/soma/mmm_v6_soma_fp32.onnx":
        ("856419dc72aeb14e591eebf4dd0ea05734a2506ddb00bcd39dd6dac2ad60f4fb", 757864273),
    "motionbricks/assets/onnx/soma/mmm_v6_soma_fp16.onnx":   # soma_n1.json が両方の名前を持つ
        ("6c9f78e23decbda8e1cfd1b0cc96980ea4b24b3ca2c808d03b058f48f82fc9ef", 380327058),
    "motionbricks/assets/human/soma_base_skel_minimal_no_root.usd":
        ("4ab93d78a0f1c06d3bcbedee5ceebb5d9d5b002fd0a88638e9399ed80b61871d", 2036435),
}
# 入れた後の大きさは、段ごとの目安（steps.Setup.steps の GB）で見積もる。全部で約 29GB（11-06 まっさらな環境のテストで実測）
