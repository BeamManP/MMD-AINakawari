"""gpu.py（GPU の診断）の英語。用語は docs/英語の用語.md。"""
TEXT = {
    "（VRAM {gb:.0f}GB）": " (VRAM {gb:.0f}GB)",
    "{gpu}{vram}・メインメモリ {ram:.0f}GB": "{gpu}{vram}, RAM {ram:.0f}GB",
    "。メインメモリが足りないかもしれません（目安 {gb:.0f}GB 以上）": ". RAM may be insufficient (at least {gb:.0f}GB recommended)",
    "GPU を使わずに作ります（時間がかかります。2 秒の動きに 1 分ほど）": "Generates without a GPU (slow: about 1 min for 2 s of motion)",
    "DirectML で動かします（GPU の名前は読めませんでした）": "Runs on DirectML (could not read the GPU name)",
    "GPU が見つかりません。セットアップで試して、動けば GPU なしで作ります（時間がかかります）":
        "No GPU found. Setup will try it, and if it works, generation runs without a GPU (slow)",
    "この PC で動きます（DirectML）": "Works on this PC (DirectML)",
    "NVIDIA 以外の GPU です。DirectML で動かします（セットアップの試しの生成で確かめます）":
        "This is a non-NVIDIA GPU. It runs on DirectML (Setup confirms this with a test generation)",
    "CUDA_VISIBLE_DEVICES={visible} で GPU が無効になっています（この設定を外してください）":
        "The GPU is disabled by CUDA_VISIBLE_DEVICES={visible} (remove this setting)",
    "GPU を調べられませんでした。「生成」を押して試してください": "Could not check the GPU. Press Generate to try it",
    "NVIDIA の GPU が見つかりません（計算の方式が CUDA になっています。「セットアップ」を押して入れ直してください）":
        "No NVIDIA GPU found (the backend is set to CUDA). Press Setup to reinstall",
    "この PC で動きます": "Works on this PC",
    "VRAM が足りないかもしれません（目安 {gb:.0f}GB 以上）": "VRAM may be insufficient (at least {gb:.0f}GB recommended)",
    "メインメモリが足りないかもしれません（目安 {gb:.0f}GB 以上）": "RAM may be insufficient (at least {gb:.0f}GB recommended)",
}
