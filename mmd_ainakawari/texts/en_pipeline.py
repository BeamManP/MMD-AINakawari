"""pipeline.py（Kimodo への依頼を作る所）の英語。用語は docs/英語の用語.md。"""
TEXT = {
    "足す長さは 1 フレーム以上にしてください": "Set the length to add to 1 frame or more",
    "「{bone}」に親のボーンがあります。「{bone}」がいちばん上のボーンのモデルだけに対応しています":
        "\"{bone}\" has a parent bone. Only models where \"{bone}\" is the top bone are supported",
    "区間の開始フレームは小さい順に、重ならないように書いてください": "Write the segment start frames in ascending order, without duplicates",
    "{s}F からの区間が {n} フレームあります。Kimodo の 1 区間は {max_frames} フレーム（10 秒）までです。区間を分けるか、範囲か長さを絞ってください":
        "The segment from {s}F is {n} frames long. A Kimodo segment can be up to {max_frames} frames (10 s). "
        "Split it into segments, or narrow the range or length",
    "Kimodo の結果の関節の並びが SOMA の骨格ファイルと違います": "The joint order of the Kimodo result differs from the SOMA skeleton file",
    "キーが 1 つもありません（0F にキーを打ってください）": "There are no keys (set a key at 0F)",
    "区間の始めをキーの次へずらしたら、{st}F の区間が {n} フレームになりました（{min} フレーム以上要ります）。区間の始めをキーから離してください":
        "After moving the segment start past the key, the segment at {st}F is {n} frames long ({min} or more are needed). "
        "Move the segment start away from the key",
    "{s}F の区間が生成する範囲（{first}〜{last}F）の外です": "The segment at {s}F is outside the range to generate ({first}-{last}F)",
    "{s}F の区間が {n} フレームしかありません（{min} フレーム以上にしてください）":
        "The segment at {s}F is only {n} frames long (make it {min} or more)",
    "範囲の始まり（{a}F）が終わり（{b}F）より後ろです": "The range start ({a}F) is after its end ({b}F)",
    "範囲は 2 フレーム以上にしてください": "Make the range 2 frames or more",
    "{why}ので、「サンプルから選ぶ」の文だけが使えます。読み取れない文: {lost}（自由に書くには、{how}）":
        "{why}, so only sentences from \"Choose from samples\" can be used. Sentences that cannot be read: {lost} (to write freely, {how})",
    "{frame}F の直後にキーが続いているので、ここでは区間を分けられません。毎フレームにキーがある時は、先に「元に戻す」を押してください":
        "Keys continue right after {frame}F, so the segments cannot be split here. If there is a key on every frame, press Undo first",
    "長さは 2 フレーム以上にしてください": "Make the length 2 frames or more",
    "キーが 1 つしかありません。長さ（フレーム）を入れるか、キーをもう 1 つ打ってください":
        "There is only 1 key. Enter a length (frames), or set another key",
    "「プロンプトの読み取り（Llama 3）を使う」を外している": "prompt reading (Llama 3) is turned off",
    "詳細の窓でチェックを入れてください": "turn it on in the details window",
    "プロンプトの読み取り（Llama 3）を入れていない": "prompt reading (Llama 3) is not installed",
    "セットアップで入れてください": "install it with Setup",
}
