"""resident.py（背景のサーバー）の英語。用語は docs/英語の用語.md。"""
TEXT = {
    "{name} の口（127.0.0.1:{port}）を、ほかのプログラムが使っているようです。そのプログラムを閉じてからもう一度押してください":
        "Another program seems to be using the port of {name} (127.0.0.1:{port}). Close that program and press the button again",
    "  {name} を常駐させています（初回だけモデルを読み込みます）…":
        "  Starting the {name} background server (the model is loaded on the first run only)...",
    "{name} の常駐が {sec:.0f} 秒たっても準備できません（{path}）":
        "The {name} background server is not ready after {sec:.0f} s ({path})",
    "{name} の常駐が終わりません（{path}）": "The {name} background server does not stop ({path})",
    "（記録がありません）": "(no log)",
    "  {name} の橋渡しが新しくなっていたので、常駐を立ち上げ直します…":
        "  The {name} bridge was updated, so restarting the background server...",
    "{name} の常駐が起動できませんでした:\n{tail}": "The {name} background server could not start:\n{tail}",
    "{name} が失敗しました:\n": "{name} failed:\n",
    "{name} の常駐が途中で終わりました（{path}）": "The {name} background server stopped midway ({path})",
    "{name} が {min} 分たっても答えません（{path}）": "{name} has not replied after {min} min ({path})",
}
