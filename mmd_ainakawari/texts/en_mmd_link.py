"""mmd_link.py（MMD とのやり取り）の失敗の文の英語。用語は docs/英語の用語.md。"""
TEXT = {
    "MMD が起動していません": "MMD is not running",
    "MMD が {count} 個起動しています。1 つにしてください": "{count} MMD windows are open. Keep only one",
    "MMD が閉じられました": "MMD was closed",
    "MMD のモデル欄（{name}）と中のモデルが合いません。もう一度選び直してください":
        "MMD's model selector ({name}) does not match the model inside. Select the model again",
    "MMD でモデルを選んでください": "Select a model in MMD",
    "MMD で全部のキーを選択できませんでした: {status} {dialogs}": "Could not select all the keys in MMD: {status} {dialogs}",
    "MMD からモーションを書き出せませんでした: {status} {dialogs}": "Could not export the motion from MMD: {status} {dialogs}",
    "モデル以外": "not a model",
    "始めた時と違うモデル（{now}）が選ばれています。キーは消していません。「{name}」を選んでから、もう一度押してください":
        "A different model from the one you started with is selected ({now}). No keys were deleted. Select \"{name}\" and try again",
    "MMD でカメラ・照明・アクセサリが選ばれています。モデルを選んでからもう一度押してください":
        "Camera, light or accessory is selected in MMD. Select a model and try again",
    "読み込むファイルがありません。キーは消していません: {path}": "The file to load does not exist. No keys were deleted: {path}",
    "ボーンのキーを消す時": "while deleting bone keys",
    "表情のキーを消す時": "while deleting facial keys",
    "モーションを読み込む時": "while loading the motion",
    "{stage}（範囲選択）": "{stage} (range selection)",
    "MMD で今のキーを消せませんでした（{stage}: {why}）。キーは消していません":
        "Could not delete the current keys in MMD ({stage}: {why}). No keys were deleted",
    "MMD にモーションを読み込めませんでした: {why}": "Could not load the motion into MMD: {why}",
    "MMD にモーションを読み込めませんでした（{why}）。消したキーは、バックアップから戻しました":
        "Could not load the motion into MMD ({why}). The deleted keys were restored from the backup",
    "MMD にモーションを読み込めず（{why}）、バックアップも読み込めませんでした。MMD の「ファイル」→「モーションデータ読込」で、次のファイルを読み込んでください: {path}":
        "Could not load the motion into MMD ({why}), and the backup could not be loaded either. "
        "In MMD, load this file from File > Load motion data: {path}",
    "OK を押した後、読み込みが終わりませんでした": "Loading did not finish after pressing OK",
}
