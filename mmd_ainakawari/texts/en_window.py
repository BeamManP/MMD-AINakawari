"""installer/window.py（セットアップの窓）の英語。用語は docs/英語の用語.md。"""
TEXT = {
    "AIナカワリ のセットアップ": "AI Nakawari Setup",
    "閉じる": "Close",
    "セットアップを始める": "Start Setup",
    "中止": "Cancel",
    "別の場所に入れる…": "Install to another location...",
    "点検して直す": "Check and repair",
    "入れる場所": "Install to",
    "選ぶ…": "Browse...",
    "ライセンス（入れる前に読んでください）": "Licenses (please read before installing)",
    "Meta Llama 3 Community License（プロンプトの読み取りに使う Llama 3）": "Meta Llama 3 Community License (Llama 3, used for prompt reading)",
    "Llama 3 の使い方の決まり（Acceptable Use Policy）": "Llama 3 Acceptable Use Policy",
    "NVIDIA Open Model License（Kimodo のモデル）": "NVIDIA Open Model License (Kimodo model)",
    "NVIDIA Open Model Agreement（MotionBricks のモデル）": "NVIDIA Open Model Agreement (MotionBricks model)",
    "MIT（プロンプトの読み取りを動かす llama.cpp）": "MIT (llama.cpp, which runs prompt reading)",
    "上のライセンスに同意して入れます": "I agree to the licenses above and install",
    "Llama 3 で作った物を公開する時は、「Built with Meta Llama 3」の表示が要ります":
        "If you publish anything made with Llama 3, you must show \"Built with Meta Llama 3\"",
    "プロンプトを自由に書けるようにする（Llama 3 を入れる・約 8GB・生成中にメインメモリを約 8GB 使う）":
        "Let me write my own prompts (installs Llama 3: about 8GB; uses about 8GB of RAM while generating)",
    "外すと「サンプルから選ぶ」の文だけで作ります（メインメモリの少ない PC 向け）。後からここで入れたり外したりできます":
        "If unchecked, only the sentences under \"Choose from samples\" are available (for PCs with little RAM). You can add or remove it here later",
    "GPU なし": "No GPU",
    "GPU を調べられませんでした": "Could not check the GPU",
    "NVIDIA の GPU が見つかりません": "No NVIDIA GPU found",
    "{missing}・メインメモリ {ram:.0f}GB": "{missing}, RAM {ram:.0f}GB",
    "現在の環境：{hardware}　→": "Your PC: {hardware}  ->",
    "？": "?",
    "入れる場所（半角の英数字だけのフォルダ）": "Install location (a folder with only half-width letters and digits)",
    "（読めません）": "(cannot read)",
    "空き {free}／これから使う量 約 {need:.0f}GB": "Free {free} / to be used: about {need:.0f}GB",
    "（済んだ {done} 手順の分を除く）": " (excluding {done} finished steps)",
    "別の方法で入れた環境を使っています": "Using an environment installed another way",
    "・": ", ",
    "\n入れ直したい時は、「別の場所に入れる…」で場所を選んでください": "\nTo reinstall, choose a location with \"Install to another location...\"",
    "入っています": "Installed",
    "この場所に入っています（まだ使っていません）": "Installed in this location (not in use yet)",
    "場所: {dest}": "Location: {dest}",
    "\n「この場所を使う」を押すと、すぐ使えます": "\nPress \"Use this location\" to start using it right away",
    "この場所を使う": "Use this location",
    "…": "...",
    "更新があります（{n} 手順・約 {need:.0f}GB）": "Update available ({n} steps, about {need:.0f}GB)",
    "場所: {dest}\n変わる手順: {names}": "Location: {dest}\nSteps that change: {names}",
    "更新する": "Update",
    "途中で止まっています（あと {n} 手順・約 {need:.0f}GB）": "Stopped partway ({n} steps left, about {need:.0f}GB)",
    "場所: {dest}\n押すと、止まった手順から進みます": "Location: {dest}\nPress to continue from the step that stopped",
    "続きから始める": "Continue",
    "AI のモデルを入れます": "Install the AI models",
    "Kimodo・MotionBricks と、それを動かす Python をまとめて入れます（落とす量は約 {gb}GB）":
        "Installs Kimodo, MotionBricks, and the Python that runs them (download about {gb}GB)",
    "入れてあるプロンプトの読み取り（Llama 3・約 8GB）を消します。\n"
    "消した後は「サンプルから選ぶ」の文だけで作ります（また入れる時は約 8GB 落とし直します）。よろしいですか？":
        "This removes the installed prompt reading (Llama 3, about 8GB).\n"
        "Afterwards only the sentences under \"Choose from samples\" are available (installing it again downloads about 8GB). Continue?",
    "点検しています…": "Checking...",
    "入っている物を点検しています（10 秒ほど）。欠けている物があれば、入れ直します":
        "Checking what is installed (about 10 s). Anything missing will be reinstalled",
    "入れています…": "Installing...",
    "入れています（落とす量は約 {gb:.0f}GB）。この窓は閉じても裏で進みます":
        "Installing (download about {gb:.0f}GB). It keeps going in the background if you close this window",
    "中止しました。もう一度押すと続きから進みます": "Cancelled. Press again to continue from where it stopped",
    "止まりました: {e}\nもう一度押すと、止まった手順から進みます": "Stopped: {e}\nPress again to continue from the step that stopped",
    "思わぬエラーで止まりました（{e}）。詳細の窓の「ログ」→「記録のフォルダを開く」にある app.log を送ってください":
        "Stopped by an unexpected error ({e}). Please send app.log, found under Log > Open the log folder in the details window",
    "中止しますか？（済んだ手順はそのまま残ります）": "Cancel? (Finished steps are kept)",
    "止めています…": "Stopping...",
    "できました。「生成」で使えます": "Done. You can now use Generate",
}
