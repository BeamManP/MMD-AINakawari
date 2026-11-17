"""MikuMikuDance.exe を 2 つ（日本語版 9.32 x64 と、中国語版など書き換えた物）比べる。作る側で使う道具（zip には入れない）。

    python tools\\compare_mmd_exe.py 日本語版\\MikuMikuDance.exe 比べる\\MikuMikuDance.exe [出力.md]

11-18 マスター「中国版 MMD 対応」（mmdybk の「MMD932 汉化版」）の下調べ用。知りたいのは 2 つ:
1. プログラム本体（.text）と、mmd-mcp が読むメモリの形に効くデータの区画が同じか
   （同じなら、メモリの番地はそのまま使えて、変わったのは文字だけ。mmd-mcp の VERIFIED_SHA256 と install_plugin の判定を広げれば済む）
2. 画面の文字がどう訳されたか（AIナカワリが窓を探すのに使う「モーションデータ読込」などの中国語）
違うバイトの範囲を拾い、日本語版は cp932 と UTF-16、比べる方は gbk・cp936・UTF-16・cp932 で読んで並べる。
pefile が要る（システムの Python に入っている）。
"""
import hashlib
import sys

import pefile

# AIナカワリ・mmd-mcp が MMD の画面の文字に頼っている所（mmd_ainakawari/mmd_link.py ほか。11-18 に grep）
WATCH = ["モーションデータ読込", "用のモーションデータです", "続行しますか", "全ﾌﾚｰﾑ", "全ボーンﾌﾚｰﾑ", "全表情ﾌﾚｰﾑ",
         "新規プロジェクト", "モデル操作", "カメラ・照明・アクセサリ", "English Mode"]


def sections(pe, data):
    out = {}
    for s in pe.sections:
        name = s.Name.decode("ascii", "replace").rstrip("\0 ").split("\0")[0].strip()   # 中国語版は名前の後ろに空白などが混ざる
        raw = data[s.PointerToRawData:s.PointerToRawData + s.SizeOfRawData]
        out[name] = (s.VirtualAddress, s.Misc_VirtualSize, s.PointerToRawData, s.SizeOfRawData, hashlib.sha256(raw).hexdigest())
    return out


def decode_all(raw, codecs):
    shown = []
    for c in codecs:
        try:
            t = raw.decode(c)
        except UnicodeDecodeError:
            continue
        t = t.replace("\0", "·").strip("·")
        if t and sum(ch.isprintable() for ch in t) / len(t) > 0.8:
            shown.append(f"{c}「{t[:80]}」")
    return " / ".join(shown) or raw[:40].hex(" ")


def diff_ranges(a, b, gap=8):
    """同じ長さの部分で違うバイトの範囲（近い物はまとめる）。"""
    n = min(len(a), len(b))
    ranges, start, last = [], None, None
    for i in range(n):
        if a[i] != b[i]:
            if start is None:
                start = i
            elif i - last > gap:
                ranges.append((start, last + 1))
                start = i
            last = i
    if start is not None:
        ranges.append((start, last + 1))
    return ranges


def main():
    ja_path, other_path = sys.argv[1], sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else None
    ja, other = open(ja_path, "rb").read(), open(other_path, "rb").read()
    lines = [f"# {ja_path} と {other_path}", "",
             f"- 大きさ: {len(ja)} / {len(other)} バイト",
             f"- SHA256: {hashlib.sha256(ja).hexdigest()} / {hashlib.sha256(other).hexdigest()}", ""]
    pa, pb = pefile.PE(data=ja), pefile.PE(data=other)
    lines.append(f"- 64bit か: {pa.FILE_HEADER.Machine == 0x8664} / {pb.FILE_HEADER.Machine == 0x8664}")
    lines.append(f"- ImageBase: {hex(pa.OPTIONAL_HEADER.ImageBase)} / {hex(pb.OPTIONAL_HEADER.ImageBase)}")
    lines += ["", "## 区画", "", "| 区画 | 番地 | 大きさ | 中身 |", "|---|---|---|---|"]
    sa, sb = sections(pa, ja), sections(pb, other)
    for name in sorted(set(sa) | set(sb), key=lambda n: (sa.get(n) or sb.get(n))[0]):
        x, y = sa.get(name), sb.get(name)
        if not x or not y:
            lines.append(f"| {name} | {'片方だけ'} | | |")
            continue
        same_place = x[0] == y[0] and x[1] == y[1]
        lines.append(f"| {name} | {hex(x[0])}{'' if same_place else ' → ' + hex(y[0])} | {x[1]}{'' if x[1] == y[1] else ' → ' + str(y[1])} | "
                     f"{'同じ' if x[4] == y[4] else '違う'} |")
    lines += ["", "## 違うバイトの範囲（区画ごと・同じ番地どうし）", ""]
    for name, x in sa.items():
        y = sb.get(name)
        if not y or x[4] == y[4]:
            continue
        ra = ja[x[2]:x[2] + x[3]]
        rb = other[y[2]:y[2] + y[3]]
        ranges = diff_ranges(ra, rb)
        lines.append(f"### {name}: {len(ranges)} か所")
        for s, e in ranges[:400]:
            s0, e0 = max(0, s - 2), e + 2
            lines.append(f"- +{hex(s)}〜{hex(e)}: 日本語 {decode_all(ra[s0:e0], ('cp932', 'utf-16-le'))}"
                         f" → 比べる方 {decode_all(rb[s0:e0], ('gbk', 'utf-16-le', 'cp932'))}")
        lines.append("")
    lines += ["## AIナカワリ・mmd-mcp が頼っている文字", ""]
    for w in WATCH:
        hits = []
        for enc in ("cp932", "utf-16-le"):
            k = w.encode(enc)
            hits.append(f"{enc}: 日本語版 {ja.count(k)}・比べる方 {other.count(k)}")
        lines.append(f"- {w}: " + "・".join(hits))
    text = "\n".join(lines) + "\n"
    if out_path:
        open(out_path, "w", encoding="utf-8").write(text)
        print(f"書きました: {out_path}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


if __name__ == "__main__":
    main()
