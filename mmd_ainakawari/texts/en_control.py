"""control.py（外からの操作の口）の英語。用語は docs/英語の用語.md。"""
TEXT = {
    "{key} は{what}で指定してください": "{key} must be {what}",
    "整数": "an integer",
    "数": "a number",
    "true か false": "true or false",
    "{key} は {low}〜{high} で指定してください": "{key} must be within {low} to {high}",
    "{key} は {choices} のどれかで指定してください": "{key} must be one of {choices}",
    'range は "selected_keys"・"all"・start と end のフレームを入れたオブジェクトのどれかで指定してください':
        'range must be "selected_keys", "all", or an object with start and end frames',
    "prompt（作りたい動きの英語の文）を指定してください": "Specify prompt (an English sentence describing the motion)",
    "その番号の依頼は見つかりません（{name} を起動し直すと、前の番号は消えます）":
        "No job with that id (ids are lost when {name} restarts)",
    "依頼は JSON のオブジェクトで送ってください": "Send the request as a JSON object",
    "protocol が合いません（こちらは {ours}）": "Protocol mismatch (this side speaks {ours})",
    "知らない項目があります: {names}": "Unknown fields: {names}",
    "op は {choices} のどれかで指定してください": "op must be one of {choices}",
    "{name} の窓が応答しません。少し待ってから、もう一度頼んでください":
        "The {name} window is not responding. Wait a moment and try again",
    "{name} の返事が間に合いませんでした。頼んだ事は受け付けられたかもしれません。status で確かめてください":
        "{name} did not reply in time. The request may have been accepted; check with status",
    "選んだキーを読めません（{why}）": "Could not read the selected keys ({why})",
}
