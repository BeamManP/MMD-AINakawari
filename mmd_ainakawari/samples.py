"""プロンプトのサンプルの一覧（prompt_samples.txt）を読む。英語が苦手な人向けに、窓の「サンプルから選ぶ」で出す。

MMD の右下のパネル（mmd_plugin/nakawari_panel.cpp の show_samples）も同じファイルを同じ書き方で読む。
書き方: [種類] の行で種類を分け、その下に「動作：英語のプロンプト」を 1 行ずつ。# で始まる行は読み飛ばす。
"""
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_samples.txt")


def load(path=PATH):
    """[(種類, [(動作, 英語のプロンプト)])]。種類の行より前の項目は、名前の無い種類（""）に入る。"""
    groups = []
    for line in open(path, encoding="utf-8-sig").read().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            groups.append((line[1:-1], []))
            continue
        label, sep, prompt = line.partition("：")
        if not sep:
            continue
        if not groups:
            groups.append(("", []))
        groups[-1][1].append((label, prompt))
    return groups
