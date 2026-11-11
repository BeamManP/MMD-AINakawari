"""mmm_link.py（MMM とのやり取り）の失敗の文の英語。"""
TEXT = {
    "MMM につながりません。MMM が起動しているか、Plugins に MmmBridge.dll があるかを確かめてください（{host}:{port}・{error}）":
        "Cannot connect to MMM. Check that MMM is running and that MmmBridge.dll is in Plugins ({host}:{port}, {error})",
    "MMM から返事がありません（MMM が閉じた可能性があります）": "No reply from MMM (MMM may have been closed)",
    "MMM でできませんでした: {error}": "MMM could not do it: {error}",
    "MMM が起動していません": "MMM is not running",
    "zip の中から読み込んだモデル（{file} の {inner}）には、まだ対応していません。zip を展開して、PMX を MMM に読み込み直してください":
        "Models loaded from inside a zip ({inner} in {file}) are not supported yet. Extract the zip and load the PMX into MMM again",
    "モデル無し": "no model",
    "始めた時と違うモデル（{now}）が選ばれています。キーは書き換えていません。「{name}」を選んでから、もう一度押してください":
        "A different model from the one you started with is selected ({now}). No keys were changed. Select \"{name}\" and try again",
    "MMM でモデルを選んでください": "Select a model in MMM",
    "書き戻すファイルがありません。キーは書き換えていません: {path}": "The file to write back does not exist. No keys were changed: {path}",
    "MMM に書き戻せず（{error}）、控えも戻せませんでした（{error2}）。控え: {restore}":
        "Could not write back to MMM ({error}), and the backup could not be restored either ({error2}). Backup: {restore}",
    "MMM に書き戻せませんでした（{error}）。控えから戻しました":
        "Could not write back to MMM ({error}). Restored from the backup",
}
