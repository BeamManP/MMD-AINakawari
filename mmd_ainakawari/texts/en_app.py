"""app.py（窓）と、窓が出す部品の文（thin.py の段の名前・panel.py のボタン）の英語。用語は docs/英語の用語.md。"""
TEXT = {
    # ---- 窓の定数 ----
    "生成したキーを、MMD の補間曲線で表せる所だけ減らします。\n右ほど少なくなり、動きは元から少しずつ離れます（左端は間引きません）":
        "Removes generated keys where MMD's interpolation curves can reproduce the motion.\n"
        "Further right means fewer keys and a little more drift from the original (far left keeps every key)",
    "打ったキーとキーの間を、プロンプト無しで MotionBricks がつなぎます。\n作るのはキーの間が 17〜57 フレームの所で、それ以外は MMD の補間を使います。":
        "MotionBricks fills the gaps between your keys, without a prompt.\n"
        "It only fills gaps of 17-57 frames; other gaps keep MMD's interpolation.",
    "MMD でキーを打ってから「生成」を押してください": "Set keys in MMD, then press Generate",
    "AI のモデルがまだ入っていません。下の「セットアップ」で入れてください":
        "The AI models are not installed yet. Install them with Setup below",
    "キーの間を埋める": "Fill between keys",
    "続きを足す": "Extend",
    "プロンプトだけで作る": "Prompt only",
    "センターに合わせて作る": "Follow center",
    "打ったキーのポーズを守って、キーとキーの間を作ります（長さは最後のキーまで）":
        "Keeps the poses of your keys and creates the motion between them (up to the last key)",
    "範囲の終わり（「全部」なら最後のキー）の後ろに、長さの分だけ続きを足します。それより前の動きは変えません":
        "Adds Length frames after the end of the range (the last key for All). Earlier motion is not changed",
    "最初のキーの場所と向きから、プロンプトだけで動きを作ります":
        "Creates motion from the prompt alone, starting at the position and facing of the first key",
    "腰の位置・高さだけをセンター（キーと補間）に合わせ、ポーズと動きはプロンプトから作ります（長さは最後のキーまで）":
        "Only the hip position and height follow the center bone (keys and interpolation); poses and motion come from the prompt (up to the last key)",
    # ---- 窓の部品 ----
    "選択中のモデル：（読み取り中）": "Selected model: (reading...)",
    "選択中のモデル：（読み取れません: {error}）": "Selected model: (cannot read: {error})",
    "選択中のモデル：{name}": "Selected model: {name}",
    "選択中のモデル：（なし。MMD のモデル欄でモデルを選んでください）": "Selected model: (none. Select a model in MMD's model selector)",
    "範囲": "Range",
    "全部": "All",
    "選んだキーの間": "Between selected keys",
    "選んだキーの間（{a}〜{b}F）": "Between selected keys ({a}-{b}F)",
    "選んだキーの間（{a}F だけ。2 つ以上選んでください）": "Between selected keys (only {a}F. Select two or more)",
    "選んだキーの間（キーを選んでいません）": "Between selected keys (no keys selected)",
    "選んだキーの間（読み取れません）": "Between selected keys (cannot read)",
    "生成": "Generate",
    "中断": "Cancel",
    "元に戻す": "Undo",
    "ログ": "Log",
    "セットアップ": "Setup",
    "AIナカワリ のログ": "AI Nakawari log",
    "記録のフォルダを開く": "Open log folder",
    "困った時は、このフォルダの app.log と、名前が _server.log で終わるファイルを GitHub の Issues に添えてください":
        "If something goes wrong, attach app.log and the files ending in _server.log from this folder to a GitHub issue",
    "Kimodo がまだ入っていません。下の「セットアップ」で入れてください": "Kimodo is not installed yet. Install it with Setup below",
    "やりたいこと": "Mode",
    "長さ": "Length",
    "キーの間引き": "Key thinning",
    "最後のキーで止まる": "Stop at the last key",
    "なめらかに止まる": "Smooth stop",
    "プロンプト（英語。1 行が 1 区間の動き）": "Prompt (English. One line = the motion of one section)",
    "＋ 今のフレームで区切る": "+ Split at current frame",
    "＋ 今のフレーム（{frame}F）で区切る": "+ Split at current frame ({frame}F)",
    "サンプルから選ぶ ▼": "Samples ▼",
    "プロンプトの読み取り（Llama 3）を使う": "Read prompts with Llama 3",
    "メインメモリが足りない時は外してください（約 8GB 減ります。サンプルの文だけで作ります）":
        "Turn this off if you are short of RAM (saves about 8 GB; only sample prompts can be used)",
    "プロンプトの効き": "Prompt strength",
    "上げると、文の動きが強く・大きく出ます（動きが弱い・出ない時は 3〜5 に）。上げすぎると大げさで不自然になります":
        "Higher makes the prompt's motion stronger and bigger (try 3-5 if the motion is weak or missing). Too high looks exaggerated",
    "キーの効き": "Key strength",
    "上げると、キーのポーズへ寄せる力が強くなります（キーの前後がカクつく時に）。下げると、キーの近くも自由に動きます（動きが硬い時に）。キーのフレームの姿勢はどちらでもそのまま残ります":
        "Higher pulls the motion harder toward your key poses (if it jerks around keys). Lower lets it move freely near keys "
        "(if it looks stiff). The poses on the key frames are kept either way",
    "推奨（{v:g}・{v:g}）に戻す": "Reset to recommended ({v:g}, {v:g})",
    "（推奨）": " (recommended)",
    "詳しい設定": "Advanced settings",
    "計算の回数（少ないほど速い）": "Steps (fewer is faster)",
    "seed（-1 で毎回違う動き）": "Seed (-1 for a different motion each time)",
    "仕上補正（足すべり・姿勢）": "Post-processing (foot sliding, posture)",
    "一時ファイルの置き場": "Temporary files",
    "変更…": "Change...",
    "既定に戻す": "Default",
    "開く": "Open",
    "生成のたびに、元の動きの控え（original_）と結果（kimodo_）の VMD をここに書きます":
        "Each generation writes a backup of the original motion (original_) and the result (kimodo_) here as VMD",
    "{path}（既定）": "{path} (default)",
    "一時ファイルの置き場を選ぶ": "Choose the folder for temporary files",
    "そのフォルダには書けません: {folder}\n（{error}）": "Cannot write to that folder: {folder}\n({error})",
    "キーごとに止まる（外すと、勢いを保って通る）": "Stop at each key (off: pass through keys with momentum)",
    "手首は MMD の補間にする（回りすぎを抑える）": "Use MMD interpolation for the wrists (prevents over-rotation)",
    "MotionBricks がまだ入っていません。下の「セットアップ」で入れてください": "MotionBricks is not installed yet. Install it with Setup below",
    "自由に書くには、上の「プロンプトの読み取り（Llama 3）を使う」を入れます": "To write your own, turn on \"Read prompts with Llama 3\" above",
    "プロンプトの読み取り（Llama 3）を使わない設定なので、サンプルの文だけ選べます。":
        "Prompt reading (Llama 3) is turned off, so only sample prompts can be used.",
    "自由に書くには、下の「セットアップ」で入れます": "To write your own, install it with Setup below",
    "プロンプトの読み取り（Llama 3）を入れていないので、サンプルの文だけ選べます。":
        "Prompt reading (Llama 3) is not installed, so only sample prompts can be used.",
    "{why}\n行を押してから「サンプルから選ぶ」で入れてください。\n{how}": "{why}\nClick a line, then choose a prompt from Samples.\n{how}",
    "F（範囲の終わりまで）": "F (to the end of the range)",
    "F（最後のキーまで）": "F (to the last key)",
    "F（最初のキーから数えた全部の長さ。必須）": "F (total length from the first key. Required)",
    "F 足す（範囲の終わりの後ろに）": "F to add (after the end of the range)",
    "F 足す（最後のキーの後ろに）": "F to add (after the last key)",
    "F 足す（{a}〜{b}F を作ります）": "F to add (creates {a}-{b}F)",
    "・": ", ",
    "範囲内に上書きされるキーフレームがあります（{frames}F の体のキー）": "Keys in this range will be overwritten (body keys at {frames}F)",
    "サンプルの一覧が読めません: {error}": "Cannot read the sample list: {error}",
    "（空にする：プロンプトなしでキーだけで作る）": "(Clear: create from the keys only, without a prompt)",
    "MMD の今のフレームを読めませんでした": "Could not read MMD's current frame",
    "（{error}）": " ({error})",
    "{frame}F から始まる区間はもうあります": "A section starting at {frame}F already exists",
    " （MMM）": " (MMM)",
    "選んだキーを読めません。MMD の操作を終えてから選び直してください": "Cannot read the selected keys. Finish what you are doing in MMD and select them again",
    "範囲の最初と最後のキーを選んでください": "Select the first and last keys of the range",
    # ---- MMD の右下のパネル ----
    "全部のキー": "All keys",
    "選んだキー（読めません）": "Selected keys (cannot read)",
    "選んだキー {a}〜{b}F": "Selected keys {a}-{b}F",
    "選んだキー {a}F だけ": "Only {a}F selected",
    "キーを選んでいません": "No keys selected",
    "詳細の窓で「セットアップ」を押してください": "Press Setup in the details window",
    "詳　細": "Details",
    "MMD が応答しませんでした。もう一度押してください": "MMD did not respond. Press it again",
    # ---- 生成・元に戻す ----
    "MotionBricks がまだ入っていません。詳細の窓の下の「セットアップ」で入れてください":
        "MotionBricks is not installed yet. Install it with Setup at the bottom of the details window",
    "「続きを足す」では、足す長さ（フレーム数）を入れてください": "For Extend, enter the number of frames to add in Length",
    "「プロンプトだけで作る」では長さを入れてください": "For Prompt only, enter a Length",
    "MMD のタイムラインで、作り直す範囲の最初と最後のキーを選んでください（2 つ以上のフレーム）":
        "Select the first and last keys of the range to regenerate in MMD's timeline (two or more frames)",
    "「詳しい設定」の計算の回数・seed には数字を入れてください": "Enter numbers for Steps and Seed in Advanced settings",
    "生成中…": "Generating...",
    "中断しています…": "Cancelling...",
    "中断を頼みました…": "Cancel requested...",
    "中断しました（MMD のキーはそのままです）": "Cancelled (the keys in MMD are unchanged)",
    "中断しました": "Cancelled",
    "失敗: {error}": "Failed: {error}",
    "できました。MMD で再生して確かめてください": "Done. Play it back in MMD to check",
    "元に戻し中…": "Undoing...",
    "生成前のモーションに戻しました": "Restored the motion from before generating",
    # ---- 起動 ----
    "MMD（か MMM）が起動していません。起動してから開いてください": "MMD (or MMM) is not running. Start it first",
    "AIナカワリ の起動がまだ終わっていません。少し待ってから、もう一度開いてください": "AI Nakawari is still starting. Wait a moment and open it again",
    "開こうとした MMD・MMM が見つかりません。開いているか確かめてください": "Cannot find that MMD / MMM window. Check that it is open",
    # ---- thin.py の段の名前 ----
    "しない": "Off",
    "細かく": "Fine",
    "ふつう": "Normal",
    "粗く": "Coarse",
    "とても粗く": "Very coarse",
}
