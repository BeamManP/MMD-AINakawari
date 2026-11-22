"""プロンプトのサンプルの一覧（prompt_samples.txt）を読む。英語が苦手な人向けに、窓の「サンプルから選ぶ」で出す。

MMD の右下のパネル（mmd_plugin/nakawari_panel.cpp の show_samples）も同じファイルを同じ書き方で読む。
書き方: [種類] の行で種類を分け、その下に「動作：英語のプロンプト」を 1 行ずつ。# で始まる行は読み飛ばす。
種類は [日本語|English|中文] と書くと、英語の時（MMD の英語モード）は 2 つ目、中国語の時（中国語版 MMD932）は 3 つ目を出す。
動作の名前は「日本語|中文」と書くと、中国語の時は | の後ろを出す。英語の時は動作の名前は出さず、英語の文だけ出す（11-22 マスター「中国語にも」）。
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
        label, sep, prompt = line.partition("：")   # i18n: skip
        if not sep:
            continue
        if not groups:
            groups.append(("", []))
        groups[-1][1].append((label, prompt))
    return groups


def group_name(name, lang):
    """種類の名前 [日本語|English|中文] の、lang（"ja"・"en"・"zh"）の方。無い言葉は日本語。"""
    parts = [p.strip() for p in name.split("|")]
    index = {"ja": 0, "en": 1, "zh": 2}.get(lang, 0)
    return parts[index] if index < len(parts) and parts[index] else parts[0]


def label_name(label, lang):
    """動作の名前「日本語|中文」の、lang の方。英語の時は空（英語の文だけ出す）。中文が無ければ日本語。"""
    if lang == "en":
        return ""
    ja, _sep, zh = label.partition("|")
    return zh.strip() if lang == "zh" and zh.strip() else ja.strip()
