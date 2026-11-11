"""11-11: 画面に出す文の訳（i18n.py・mmd_ainakawari/texts/en_*.py）の漏れを探す。MMD も Kimodo も使わない。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_i18n.py [--list]

見る物（mmd_ainakawari の .py 全部。texts と i18n.py を除く）:
1. _()・N_()・tr()（self.tr など）に渡した文が、英語の表にあるか
2. 差し込み {名前}: 呼ぶ側の名前と文の中の名前が合うか・英語の訳も同じ名前を使うか
3. 包み忘れた日本語の文（説明の文・applog の記録・コマンドの引数の説明・行の末尾に「# i18n: skip」がある行は見ない）
4. 英語の表にあって、どこからも使われていない文（--list の時に一覧）
問題があれば 1 で終わる。
"""
import ast
import os
import re
import string
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from mmd_ainakawari import i18n  # noqa: E402

PKG = os.path.join(HERE, "mmd_ainakawari")
JP = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff61-\uff9f\u3000-\u303f\uff01-\uff60]")
CALLS = {"_", "N_", "tr"}
IGNORED_CALLS = {"write", "exception", "add_argument", "ArgumentParser"}   # applog.write・applog.exception・argparse
SKIP = "# i18n: skip"


def fields(text):
    try:
        return {f.split(".")[0].split("[")[0] for _, f, _, _ in string.Formatter().parse(text) if f is not None}
    except ValueError as e:
        return {f"<壊れた書式: {e}>"}


def call_name(node):
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def scan(path):
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines()
    tree = ast.parse(src)
    used, problems, loose = [], [], []
    inside = set()   # 訳の呼び出しの中・見ない呼び出しの中・説明の文の、文字列の id

    # 関数の中で _ に値を入れていると、その関数の _() は UnboundLocalError で落ちる（_ がその関数のものになる）
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        own, stack = [], list(ast.iter_child_nodes(fn))
        while stack:   # 入れ子の関数・lambda・内包表記（[x for _ in …] など）は別のスコープなので見ない
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
                              ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                continue
            own.append(n)
            stack.extend(ast.iter_child_nodes(n))
        assigns = any(isinstance(n, ast.Name) and n.id == "_" and isinstance(n.ctx, ast.Store) for n in own)
        args = fn.args.args + fn.args.kwonlyargs + ([fn.args.vararg] if fn.args.vararg else [])
        if assigns or any(a.arg == "_" for a in args):
            for n in own:
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_":
                    problems.append((n.lineno, "_ の上書き: この関数（lambda）で _ に値を入れているので _() が使えない"))

    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                inside.add(id(first.value))
        if not isinstance(node, ast.Call):
            continue
        name = call_name(node)
        if name in IGNORED_CALLS:
            inside.update(id(n) for n in ast.walk(node))
        if name not in CALLS or not node.args:
            continue
        arg = node.args[0]
        inside.update(id(n) for n in ast.walk(arg))
        if isinstance(arg, ast.JoinedStr):
            problems.append((node.lineno, "f-string を訳に渡している（{名前} と kw にする）"))
            continue
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            continue   # _(NOTE) など。中身は N_() の所で見る
        text = arg.value
        used.append((node.lineno, text))
        if name == "N_":
            continue
        given = {k.arg for k in node.keywords}
        if None in given:
            continue   # **kw
        want = fields(text)
        if want != given:
            problems.append((node.lineno, f"差し込みが合わない（文 {sorted(want)}・渡す {sorted(given)}）: {text[:40]!r}"))

    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        if isinstance(node, ast.JoinedStr):
            parts = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if JP.search(parts):
                inside.update(id(n) for n in ast.walk(node))
                if SKIP not in lines[node.lineno - 1] and SKIP not in lines[node.end_lineno - 1]:
                    loose.append((node.lineno, "f\"" + parts[:50] + "\""))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and JP.search(node.value):
            if SKIP not in lines[node.lineno - 1] and SKIP not in lines[node.end_lineno - 1]:
                loose.append((node.lineno, repr(node.value[:50])))
    return used, problems, loose


def main():
    show_all = "--list" in sys.argv
    en = i18n._table("en")
    bad = 0
    all_used = set()
    for root, dirs, files in os.walk(PKG):
        dirs[:] = [d for d in dirs if d not in ("texts", "__pycache__")]
        for f in sorted(files):
            if not f.endswith(".py") or (root == PKG and f == "i18n.py"):
                continue
            path = os.path.join(root, f)
            rel = os.path.relpath(path, HERE)
            used, problems, loose = scan(path)
            missing = []
            for line, text in used:
                all_used.add(text)
                if text not in en:
                    missing.append((line, text))
                elif fields(en[text]) != fields(text):
                    problems.append((line, f"英語の訳の差し込みが違う: {sorted(fields(text))} / {sorted(fields(en[text]))}: {text[:40]!r}"))
            if missing or problems or loose:
                print(f"== {rel}: 訳が無い {len(missing)}・食い違い {len(problems)}・包み忘れ {len(loose)}")
                for line, text in (missing if show_all else missing[:5]):
                    print(f"   {line}: 訳が無い: {text[:60]!r}")
                for line, msg in problems:
                    print(f"   {line}: {msg}")
                for line, text in (loose if show_all else loose[:5]):
                    print(f"   {line}: 包み忘れ: {text}")
                bad += len(missing) + len(problems) + len(loose)
    unused = sorted(set(en) - all_used)
    if unused:
        print(f"== 英語の表の、どこからも使われていない文 {len(unused)}" + ("" if show_all else "（--list で一覧）"))
        for text in (unused if show_all else []):
            print(f"   {text[:60]!r}")
    print("---")
    print("問題なし" if not bad else f"問題 {bad} 件")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
