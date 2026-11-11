"""mmm_run.py（MMM 版の生成・元に戻す）の、画面に出す文の英語。"""
TEXT = {
    "戻せる前回の生成がありません（MMM の Ctrl+Z でも戻せます）": "There is no previous generation to undo (you can also undo with Ctrl+Z in MMM)",
    "元に戻しました": "Undone",
    "MotionBricks がまだ入っていません。MMD 版の「セットアップ」で入れてください":
        "MotionBricks is not installed yet. Install it with Setup in the MMD version",
    "MMM のタイムラインで、作り直す範囲の最初と最後のキーを選んでください（2 つ以上のフレーム）":
        "In the MMM timeline, select the first and last keys of the range to redo (at least 2 frames)",
    "できました。MMM で再生して確かめてください（Ctrl+Z で生成の前に戻ります）":
        "Done. Play it in MMM to check (Ctrl+Z goes back to before the generation)",
    "中断しました（MMM のキーはそのままです）": "Cancelled (the keys in MMM are unchanged)",
}
