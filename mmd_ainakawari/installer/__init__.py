"""セットアップ（詳細の窓の「セットアップ」）。Kimodo と MotionBricks を、選んだ場所にボタン一つで入れる。

    steps.py   本体（段・続きから・落とす・外のプロセス）。python -m mmd_ainakawari.installer.steps で手でも回せる
    window.py  画面
    pins.py    落とす物の版（確かめた物に固定）
    kimodo-requirements.txt  Kimodo の環境の部品表（版と sha256。kimodo-requirements.in から uv pip compile で作る）
    fetch_kimodo_model.py    Kimodo のモデルを落とす（Kimodo の Python で回す）
"""
