"""runner.py（生成の流れ）の英語。用語は docs/英語の用語.md。"""
TEXT = {
    "MMD でモデルを選んでください（今はカメラ・照明・アクセサリが選ばれています）":
        "Select a model in MMD (a camera, light or accessory is selected now)",
    "PMX のモデルだけに対応しています（「{model}」は {file}）": "Only PMX models are supported (\"{model}\" is {file})",
    "PMX が見つかりません: {path}": "PMX not found: {path}",
    "MMD から「{model}」のモーションを読み込み中…": "Loading the motion of \"{model}\" from MMD...",
    "  キー {n} 個": "  {n} keys",
    "注意: 同じ名前のボーンが 2 本以上あります（{names}）。MMD は同じ名前のキーを前の方のボーンに入れるので、2 本目以降のキーは残せません（生成のあとは 0 に戻ります）":
        "Note: more than one bone has the same name ({names}). MMD puts keys of the same name into the first bone, "
        "so keys on the later bones cannot be kept (they go back to 0 after generation)",
    "注意: モデルに無いボーンは飛ばして作ります: {names}": "Note: bones missing from the model are skipped: {names}",
    "（上半身2 の分の曲がりは上半身に入れます）": " (the bend of Upper Body 2 goes into Upper Body)",
    "  書き戻す骨は前回の結果のままなので、前回の元のキーから作り直します（ほかの骨・表情は今のまま。バックアップ: {backup}）":
        "  The bones to write back are still the previous result, so it is redone from the previous original keys "
        "(other bones and expressions stay as they are). Backup: {backup}",
    "  バックアップ: {backup}": "  Backup: {backup}",
    "{a}〜{b}F・{n} フレーム": "{a}-{b}F, {n} frames",
    "{a}F の姿勢から続けて、後ろに {n} フレーム（{b}〜{c}F）を足します":
        "Continuing from the pose at {a}F, adding {n} frames after it ({b}-{c}F)",
    "。{a}F の姿勢は MMD のまま（後ろの動きにつなぎます）": ". The pose at {a}F stays as it is in MMD (it connects to the later motion)",
    "（手前 {n} フレームの動きも渡します）": " (the {n} frames before it are also passed in)",
    "注意: 足す所にあった体のキー（{frames}F）は上書きしました（指・表情などのキーはそのまま）":
        "Note: the body keys where frames were added ({frames}F) were overwritten (finger and expression keys are kept)",
    "範囲 {a}〜{b}F を作り直します: ": "Redoing range {a}-{b}F: ",
    "始まりと終わり（{lo}F・{hi}F）の姿勢を MMD から取り、外の動きにつなぎます":
        "takes the poses at the start and end ({lo}F, {hi}F) from MMD and connects to the motion outside",
    "始まり（{lo}F）の姿勢を MMD から取ってつなぎます（後ろにキーが無いので、終わりは決めません）":
        "takes the pose at the start ({lo}F) from MMD and connects to it (no key follows, so the end is left open)",
    "（外側 {n} フレームの動きも渡します）": " (the {n} frames outside are also passed in)",
    "  範囲の終わりまで作ります（範囲を使う時は、長さの欄は効きません）":
        "  It is generated up to the end of the range (Length has no effect when a range is used)",
    "・プロンプトの効き {cfg_text}・キーの効き {cfg_key}": ", Prompt strength {cfg_text}, Key strength {cfg_key}",
    "体のキー {n} 個: {frames}（{shown}）": "{n} body keys: {frames} ({shown})",
    "センターに合わせて作る: キーのポーズは使わず、{n} フレームで腰の位置と高さをセンター（キーと補間）に合わせます。ポーズと動きはプロンプトから作ります（{shown}）":
        "Follow center: key poses are not used; the hip position and height follow the center bone (keys and interpolation) on {n} frames. "
        "Poses and motion come from the prompt ({shown})",
    "プロンプトだけで作る: {a}F の場所と向きから作ります（{shown}）":
        "Prompt only: created from the position and facing at {a}F ({shown})",
    "腰の位置をセンターに合わせる: {n} フレームで腰の位置と高さを目印にします":
        "Hips follow the center: the hip position and height are used as markers on {n} frames",
    "全ての親だけのキー {n} 個: {frames}（腰がそこを通るように作る）":
        "{n} keys on the master bone alone: {frames} (the hips are made to pass through them)",
    "最後のキー（{key}F）で止まる: {a}〜{b}F は腰を動かさない": "Stops at the last key ({key}F): the hips do not move in {a}-{b}F",
    "（後ろ {n} フレームは止まるために余分に作るだけで、書き戻さない）":
        " (the {n} frames after it are only made extra for stopping and are not written back)",
    "手足の IK だけのキー {n} 個: {frames}（手足の位置だけ合わせ、体は任せる）":
        "{n} keys on limb IK alone: {frames} (only the limb positions are matched; the body is left to the AI)",
    "{a}F（{cm:.0f}cm）": "{a}F ({cm:.0f}cm)",
    "{a}〜{b}F（{cm:.0f}cm）": "{a}-{b}F ({cm:.0f}cm)",
    "注意: 足の裏がほかのキーより低いキーがあります: {shown}。床は一番低い足で決めるので、ほかのフレームもそのぶん沈みます。足が床に埋まっていないか、足ＩＫの高さを確かめてください":
        "Note: some keys have the soles lower than the other keys: {shown}. The floor is set by the lowest foot, "
        "so the other frames sink by the same amount. Check that the feet are not buried in the floor, and the height of the foot IK",
    "区間の始め {old}F の直後にキー（{key}F）があるので、区間の始めを {new}F にずらしました（キーで跳ばないように）":
        "A key ({key}F) follows right after the segment start {old}F, so the segment start was moved to {new}F (to avoid a jump at the key)",
    "注意: {s0}F からの区間は {n} フレームしかありません。Kimodo はつなぎに前の区間の 5 フレームを使うので、動きが出きらないことがあります（公式のデモは 1 区間 2 秒以上）":
        "Note: the segment from {s0}F is only {n} frames long. Kimodo uses 5 frames of the previous segment to connect, "
        "so the motion may not fully develop (the official demo uses segments of 2 s or more)",
    "注意: プロンプトに日本語があります。日本語はほとんど効かないので、英語で書いてください（例: A person poses cutely, tilting the head.）":
        "Note: the prompt contains Japanese. Japanese has almost no effect, so write it in English (e.g. A person poses cutely, tilting the head.)",
    "注意: 体のキーが {n} 個あります。Kimodo の推奨は {max} 個未満です（多いとキーに縛られて動きが硬くなることがあります）":
        "Note: there are {n} body keys. Kimodo recommends fewer than {max} (with many, the motion can become stiff, tied to the keys)",
    "プロンプトが空なので、キー（と腰・手足の目印）だけを手がかりに作ります（プロンプトの効きは関係しません）":
        "The prompt is empty, so it is created from the keys (and hip and limb markers) alone (Prompt strength does not matter)",
    "  区間 {a}〜{b}F: {prompt}": "  Segment {a}-{b}F: {prompt}",
    "MotionBricks で中割り中…": "In-between with MotionBricks...",
    "Kimodo で生成中…": "Generating with Kimodo...",
    "MotionBricks で止まり方を作り直し中…": "Redoing the stopping with MotionBricks...",
    "間のフレームのキー {n} 個を差し込みました": "Inserted {n} keys on the frames in between",
    "キーを間引き中（{level}）…": "Thinning out keys ({level})...",
    "  モデル全体のキー {before} → {after} 個（キーを置いたフレーム {aligned}・手足や頭のずれ最大 {cm:.1f}cm・{sec:.0f} 秒） → {out}":
        "  Keys for the whole model {before} -> {after} (keyed frames {aligned}, max limb/head drift {cm:.1f}cm, {sec:.0f} s) -> {out}",
    "MMD に読み込み中…": "Loading into MMD...",
    "注意: {frame}F へ戻せませんでした（MMD は 0F のままです）: {why}": "Note: could not go back to {frame}F (MMD stays at 0F): {why}",
    "・全ての親のキーとの腰のずれ最大 {cm:.0f}cm": ", max hip drift from the master keys {cm:.0f}cm",
    "できました（{sec:.0f} 秒・生成 {gen:.1f} 秒・キーとのずれ最大 {cm:.1f}cm{extra}）":
        "Done ({sec:.0f} s, generation {gen:.1f} s, max drift from the keys {cm:.1f}cm{extra})",
    "元に戻すためのバックアップがありません": "There is no backup to undo with",
    "元に戻しました（{backup}）": "Undone ({backup})",
    "注意: {what}は「{bone}」に載せません: {why}": "Note: not carried on \"{bone}\" ({what}): {why}",
    "{what}を「{bone}」に載せます（{a}F から・キー {n} 個）": "Carrying on \"{bone}\" ({what}) from {a}F, {n} keys",
}
