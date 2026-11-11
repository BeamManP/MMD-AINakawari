"""mmd_memory.py（MMD のメモリからキーを読む所）の失敗の文の英語。"""
TEXT = {
    "PMX ではありません: {path}": "Not a PMX file: {path}",
    "MMD のキーの並びを読めませんでした（つながりが壊れています）。MMD の操作が終わってからもう一度押してください":
        "Could not read MMD's key list (the links are broken). Try again after MMD finishes what it is doing",
    "MMD でモデルが選ばれていません": "No model is selected in MMD",
    "MMD の表情 {morphs}・IK {iks} 個が、PMX の {pmx_morphs}・{pmx_iks} 個と合いません":
        "MMD has {morphs} morphs and {iks} IKs, but the PMX has {pmx_morphs} and {pmx_iks}",
    "PMX が途中で終わっています": "The PMX file ends unexpectedly",
}
