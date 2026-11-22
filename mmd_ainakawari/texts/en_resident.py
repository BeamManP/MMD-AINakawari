"""resident.py（背景のサーバー）の英語。用語は docs/英語の用語.md。"""
TEXT = {
    "{name} の口（127.0.0.1:{port}）を、ほかのプログラムが使っているようです。そのプログラムを閉じてからもう一度押してください":
        "Another program seems to be using the port of {name} (127.0.0.1:{port}). Close that program and press the button again",
    "  {name} を常駐させています（初回だけモデルを読み込みます）…":
        "  Starting the {name} background server (the model is loaded on the first run only)...",
    "（記録がありません）": "(no log)",
    "  {name} の橋渡しが新しくなっていたので、常駐を立ち上げ直します…":
        "  The {name} bridge was updated, so restarting the background server...",
    "{name} の常駐（裏で動く生成の部品）が {sec:.0f} 秒たっても準備できません。パソコンの負荷が高いか、ビデオメモリが足りないかもしれません。もう一度押しても続く時は、パソコンを再起動してください。それでも続く時は、詳細の窓の「セットアップ」をやり直してください（記録: {path}）": "The {name} background server (the part that generates motion) is not ready after {sec:.0f} s. The PC may be under heavy load, or video memory may be short. If pressing it again does not help, restart the PC. If it still happens, run Setup again in the details window (log: {path})",
    "{name} の常駐（裏で動く生成の部品）が終わりません。AIナカワリ を閉じてから開き直してください（記録: {path}）": "The {name} background server (the part that generates motion) does not stop. Close AI Nakawari and open it again (log: {path})",
    "{name} の常駐（裏で動く生成の部品）が起動できませんでした。もう一度押しても続く時は、パソコンを再起動してください。それでも続く時は、詳細の窓の「セットアップ」をやり直してください\n{tail}": "The {name} background server (the part that generates motion) could not start. If pressing it again does not help, restart the PC. If it still happens, run Setup again in the details window\n{tail}",
    "{name} が生成に失敗しました。設定を変えるか、長さを短くして、もう一度押してください。詳しく:\n": "{name} failed to generate. Change the settings or shorten the length, then press it again. Details:\n",
    "{name} の常駐（裏で動く生成の部品）が途中で終わりました。ビデオメモリが足りなかったかもしれません。もう一度押しても続く時は、パソコンを再起動してください。それでも続く時は、詳細の窓の「セットアップ」をやり直してください（記録: {path}）": "The {name} background server (the part that generates motion) stopped midway. Video memory may have run short. If pressing it again does not help, restart the PC. If it still happens, run Setup again in the details window (log: {path})",
    "{name} が {min} 分たっても答えません。生成が重すぎるか、止まっているかもしれません。長さを短くしてください。もう一度押しても続く時は、パソコンを再起動してください。それでも続く時は、詳細の窓の「セットアップ」をやり直してください（記録: {path}）": "{name} has not replied after {min} min. The generation may be too heavy or stuck. Shorten the length. If pressing it again does not help, restart the PC. If it still happens, run Setup again in the details window (log: {path})",
}
