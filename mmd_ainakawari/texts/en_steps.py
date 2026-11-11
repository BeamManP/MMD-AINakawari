"""installer/steps.py（セットアップの段）と、fetch_kimodo_model.py に渡す文の英語。用語は docs/英語の用語.md。"""
TEXT = {
    # ---- 定数・段の見出し ----
    "通信が途中で切れたようです。少し時間をおいて、もう一度「セットアップ」を押してください。済んだ手順は飛ばして、続きから始めます。":
        "The connection seems to have dropped. Wait a moment and press Setup again. Finished steps are skipped and it continues from where it stopped.",
    "できました: {path}": "Done: {path}",
    "環境を作り直すため": "to rebuild the environment",
    "次の生成から、選んだ計算の方式で動かすため": "so the next generation runs with the chosen backend",
    "Kimodo の本体を落とす": "Download Kimodo",
    "Kimodo の Python の環境を作る（約 5GB）": "Build the Kimodo Python environment (about 5 GB)",
    "Kimodo の骨格を用意する": "Prepare the Kimodo skeleton",
    "Kimodo のモデルを落とす（約 1GB）": "Download the Kimodo model (about 1 GB)",
    "プロンプトを読み取るモデルを落とす（約 8GB。いちばん長くかかります）": "Download the prompt reading model (about 8 GB, the longest step)",
    "プロンプトの読み取りに使う llama.cpp を落とす": "Download llama.cpp for prompt reading",
    "プロンプトの読み取り（Llama 3）を消す（約 8GB 空きます）": "Remove Llama 3 prompt reading (frees about 8 GB)",
    "ONNX Runtime を Kimodo の環境に入れる（NVIDIA 以外の GPU でも動かすため）": "Install ONNX Runtime into the Kimodo environment (to run on non-NVIDIA GPUs)",
    "Kimodo が動くか確かめる（2 秒の動きを試しに作る）": "Check that Kimodo runs (generate a 2 s test motion)",
    "MotionBricks の本体を落とす": "Download MotionBricks",
    "MotionBricks のモデルを落とす（約 1.1GB）": "Download the MotionBricks models (about 1.1 GB)",
    "MotionBricks の Python の環境を作る（約 3GB）": "Build the MotionBricks Python environment (about 3 GB)",
    "ONNX Runtime を MotionBricks の環境に入れる（NVIDIA 以外の GPU でも動かすため）": "Install ONNX Runtime into the MotionBricks environment (to run on non-NVIDIA GPUs)",
    "MotionBricks が動くか確かめる（1 秒の動きを試しに作る。初回は数分かかる）": "Check that MotionBricks runs (generate a 1 s test motion; the first run takes a few minutes)",
    # ---- 場所・環境の確認 ----
    "セットアップの道具（uv）が見つかりません: {path}。zip の中身を全部展開し直してください":
        "The setup tool (uv) was not found: {path}. Extract the whole zip again",
    "zip の中身が足りません（{name} がありません）。zip の中身を全部展開し直してください":
        "The zip is missing files ({name} not found). Extract the whole zip again",
    "Microsoft Visual C++ 再頒布可能パッケージ（x64）が入っていません。": "The Microsoft Visual C++ Redistributable (x64) is not installed.",
    "{url} から落として入れてから、もう一度押してください（Microsoft の公式の物です）":
        "Download and install it from {url}, then press the button again (it is the official one from Microsoft)",
    "入れる場所は「D:\\AINakawari」のような、ドライブから始まる半角の英数字だけのフォルダにしてください。":
        "Choose a folder like \"D:\\AINakawari\": starting with a drive letter, using only half-width letters and digits.",
    "日本語・空白・記号（& ( ) など）が入ると、途中の部品が動かないことがあります。":
        "Japanese characters, spaces and symbols (& ( ) etc.) can stop some of the parts from working.",
    "ドライブ {drive} がありません": "Drive {drive} does not exist",
    "{name} 本体のフォルダ（{path}）の中には入れられません。別のフォルダにしてください":
        "It cannot go inside the {name} folder ({path}). Choose another folder",
    "MMD の plugin フォルダ（{path}）の中には入れられません。MMD が起動しなくなります。別のフォルダにしてください":
        "It cannot go inside MMD's plugin folder ({path}); MMD would no longer start. Choose another folder",
    # ---- 流れ ----
    "空きが足りません。残りの手順で約 {need:.0f}GB 使いますが、{drive} の空きは {free:.0f}GB です。空きを作るか、別のドライブを選んでください":
        "Not enough free space. The remaining steps need about {need:.0f} GB, but {drive} has {free:.0f} GB free. Free up some space or choose another drive",
    "入れる場所: {path}（空き {free:.0f}GB・残りの手順で約 {need:.0f}GB）":
        "Install location: {path} ({free:.0f} GB free, about {need:.0f} GB needed for the remaining steps)",
    "プロンプトの読み取り（Llama 3）: 入れます": "Prompt reading (Llama 3): will be installed",
    "プロンプトの読み取り（Llama 3）: 入れません（「サンプルから選ぶ」の文だけで作ります）":
        "Prompt reading (Llama 3): will not be installed (only the sample prompts can be used)",
    "点検しています: {name}": "Checking: {name}",
    "―― 点検: 「{name}」は済んだ印がありますが、中身が欠けているので、やり直します":
        "-- Check: \"{name}\" is marked as done, but some files are missing, so it will be redone",
    "済み（{s:.0f} 秒）": "Done ({s:.0f} s)",
    "セットアップが終わりました": "Setup finished",
    "点検しました。欠けている物はありませんでした": "Checked. Nothing was missing",
    "この場所を使うように設定しました（{path}）": "This location is now in use ({path})",
    # ---- 外のコマンド・進み具合 ----
    "通信が途中で切れたようです。{s:.0f} 秒待って、続きからもう一度試します（{n} 回目／全 {total} 回）":
        "The connection seems to have dropped. Waiting {s:.0f} s, then trying again from where it stopped (attempt {n} of {total})",
    "{what}: 通信が切れたので、少し待ってやり直します…": "{what}: connection dropped, waiting a moment to retry...",
    "{what}… {m} 分 {s:02d} 秒": "{what}... {m} min {s:02d} s",
    "・ここまでに約 {gb:.1f}GB": ", about {gb:.1f} GB so far",
    "\u3000": "  ",
    "{name}（{size}）": "{name} ({size})",
    "落としている物: ": "Downloading: ",
    "・": ", ",
    " ほか {n} 個": " and {n} more",
    "「{what}」で失敗しました（終了コード {rc}）。": "\"{what}\" failed (exit code {rc}).",
    # ---- 落とす ----
    "{label}: 通信が途中で切れました。{s:.0f} 秒待って、続き（{mb:,.0f} MB）から落とします（{n} 回目／全 {total} 回）":
        "{label}: connection dropped. Waiting {s:.0f} s, then resuming from {mb:,.0f} MB (attempt {n} of {total})",
    "{label}: 通信が切れたので、少し待って続きから落とします…": "{label}: connection dropped, waiting a moment to resume...",
    "{label} の大きさが違います（{actual} バイト・正しくは {size}）。もう一度押してください":
        "{label} has the wrong size ({actual} bytes, expected {size}). Press the button again",
    "{label}: 中身を確かめています": "{label}: verifying...",
    "{label} の中身が違います（壊れて届いたかもしれません）。もう一度押してください":
        "The contents of {label} do not match (it may have arrived damaged). Press the button again",
    "{label} を落とせませんでした（{error}）。もう一度押してください": "Could not download {label} ({error}). Press the button again",
    "{label} を落とせませんでした（{error}）。ネットにつながっているか確かめて、もう一度押してください":
        "Could not download {label} ({error}). Check your internet connection and press the button again",
    "{label} を落とす途中で切れました（{error}）。もう一度押すと続きから落とします":
        "The download of {label} was interrupted ({error}). Press the button again to resume",
    "{label} を落とす途中で切れました（{done:,.0f} / {total:,.0f} MB）。もう一度押すと続きから落とします":
        "The download of {label} was interrupted ({done:,.0f} / {total:,.0f} MB). Press the button again to resume",
    "{label}: {done:,.0f} / {total:,.0f} MB（{pct}%）": "{label}: {done:,.0f} / {total:,.0f} MB ({pct}%)",
    "{label}: {done:,.0f} MB": "{label}: {done:,.0f} MB",
    "{name} の zip": "{name} zip",
    "{name} の zip を展開しています": "Extracting the {name} zip...",
    "{name} の zip が壊れていました。もう一度押すと落とし直します": "The {name} zip was damaged. Press the button again to download it again",
    "{name} の zip の中身が正しくありません（{tops}）": "The contents of the {name} zip are not as expected ({tops})",
    # ---- 計算の方式・常駐 ----
    "{env}={value} は {choices} の並びにしてください": "Set {env}={value} to a list of {choices}",
    "計算の方式: {backend} で試します": "Backend: trying {backend}",
    "{label} は {backend} では動きませんでした。次の方式で試します:": "{label} did not work with {backend}. Trying the next backend:",
    "常駐の {name} を終わらせました（{why}）": "Stopped the background {name} ({why})",
    "常駐を終わらせられませんでした（{kind}: {error}）": "Could not stop the background server ({kind}: {error})",
    # ---- Kimodo ----
    "PyTorch など約 5GB を落として入れます（いちばん大きい物は 1 個で約 2.5GB）。回線によって 10 分〜1 時間ほどかかります":
        "Downloading and installing about 5 GB (PyTorch and others; the largest file alone is about 2.5 GB). This takes 10 min to 1 h depending on your connection",
    "下の青い字の時間と量が増えていれば、進んでいます。通信が切れた時は、自動で続きからやり直します":
        "If the time and amount in blue below keep growing, it is working. If the connection drops, it retries from where it stopped automatically",
    "Python の用意": "Preparing Python",
    "Kimodo の部品を入れる": "Installing Kimodo parts",
    "Kimodo を入れる": "Installing Kimodo",
    "zip の中の部品が、別の版の Kimodo 用です（{commit}）。zip を落とし直してください":
        "The part in the zip is for a different version of Kimodo ({commit}). Download the zip again",
    "zip の中の部品（{path}）が無いか、壊れています。zip を落とし直してください":
        "The part in the zip ({path}) is missing or damaged. Download the zip again",
    "組み立て済みの部品の読み込み": "Loading the prebuilt part",
    "ONNX Runtime を入れる（Kimodo）": "Installing ONNX Runtime (Kimodo)",
    "ONNX Runtime の読み込み（Kimodo）": "Loading ONNX Runtime (Kimodo)",
    "骨格の書き出し": "Exporting the skeleton",
    "Kimodo のモデルを落とす": "Downloading the Kimodo model",
    "写す元の GGUF の中身が違います（{path}）": "The contents of the GGUF to copy do not match ({path})",
    "もう置いてありました: {name}": "Already in place: {name}",
    "写しました: {path}": "Copied: {path}",
    "落としました: {name}": "Downloaded: {name}",
    "llama.cpp の zip": "llama.cpp zip",
    "llama.cpp の zip を展開しています": "Extracting the llama.cpp zip...",
    "llama.cpp の zip の中身が正しくありません（llama-server.exe がありません）":
        "The contents of the llama.cpp zip are not as expected (llama-server.exe not found)",
    "llama.cpp の版を確かめる": "Checking the llama.cpp version",
    "{path} を消しています": "Deleting {path}...",
    "消しました: {path}": "Deleted: {path}",
    "初めての読み込みなので 1〜2 分かかります（プロンプトを読み取るモデル約 8GB をメインメモリに読みます）":
        "The first load takes 1-2 min (the prompt reading model, about 8 GB, is loaded into RAM)",
    "初めての読み込みなので 1 分ほどかかります（プロンプトはサンプルの読み取り結果を使います）":
        "The first load takes about 1 min (prompts use the prepared reading of the samples)",
    "DirectML では、初回だけ Kimodo のモデルを ONNX に書き出します（約 1.2GB・1 分ほど）":
        "With DirectML, the Kimodo model is exported to ONNX on the first run only (about 1.2 GB, about 1 min)",
    "GPU を使わずに作ります（2 秒の動きに 1 分ほどかかります）": "Running without the GPU (a 2 s motion takes about 1 min)",
    "Kimodo の試しの生成": "Kimodo test generation",
    "Kimodo の試しの生成の結果が空でした（{path}）": "The Kimodo test generation returned nothing ({path})",
    "Kimodo で {frames} フレーム作れました（計算の方式: {backend}）。この場所を使うように設定しました":
        "Kimodo generated {frames} frames (backend: {backend}). This location is now in use",
    # ---- MotionBricks ----
    "約 3GB を落として入れます。下の青い字の時間と量が増えていれば、進んでいます":
        "Downloading and installing about 3 GB. If the time and amount in blue below keep growing, it is working",
    "MotionBricks の部品を入れる": "Installing MotionBricks parts",
    "ONNX Runtime を入れる（MotionBricks）": "Installing ONNX Runtime (MotionBricks)",
    "ONNX Runtime の読み込み（MotionBricks）": "Loading ONNX Runtime (MotionBricks)",
    "Kimodo の骨格がありません。先に Kimodo のセットアップを済ませてください": "The Kimodo skeleton is missing. Finish the Kimodo setup first",
    "初回は GPU に合わせた TensorRT の準備で数分かかります（止まって見えても進んでいます）":
        "The first run takes a few minutes to prepare TensorRT for your GPU (it is still working even if it looks stuck)",
    "MotionBricks の試しの生成": "MotionBricks test generation",
    "MotionBricks の試しの生成の結果が空でした（{path}）": "The MotionBricks test generation returned nothing ({path})",
    "MotionBricks で {frames} フレーム作れました（計算の方式: {backend}）。この場所を使うように設定しました":
        "MotionBricks generated {frames} frames (backend: {backend}). This location is now in use",
}
