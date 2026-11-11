"""11-11（0.4.1）: MMD の英語モードが窓の言葉と違ったら、窓を作り直す（app.App._check_language）。窓・MMD は使わない。

    E:\\Projects\\mmd-mcp\\.venv\\Scripts\\python.exe -X utf8 tests\\check_language_1111.py

0.4.0 は窓を作る時に 1 回読むだけで、MMD の起動直後（ボタンの字がまだ日本語）に作られた窓は、英語モードでも日本語のままだった。
1. 言葉が同じなら作り直さない
2. 違えば、4 回目（2 秒）で作り直す。それより前は作り直さない
3. 生成中は作り直さない（終わってから）
4. 読めない時（MMD が忙しいなど）は作り直さない
"""
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

from mmd_ainakawari import app  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("OK  " if ok else "NG  ") + name + (f" … {detail}" if detail else ""))


class Hub:
    def __init__(self):
        self.rebuilt = []

    def rebuild(self, a):
        self.rebuilt.append(a)


class Link:
    def __init__(self, lang):
        self.lang = lang

    def language(self):
        if isinstance(self.lang, Exception):
            raise self.lang
        return self.lang


def make(window_lang, mmd_lang, busy=False):
    a = app.App.__new__(app.App)   # Tk の窓は作らない（_check_language が使う物だけ持たせる）
    a.lang, a.link, a.hub, a.busy, a._lang_ticks = window_lang, Link(mmd_lang), Hub(), busy, 0
    return a


def ticks(a, n):
    return [a._check_language() for _ in range(n)]


a = make("en", "en")
check("1. 言葉が同じなら作り直さない", not any(ticks(a, 12)) and not a.hub.rebuilt)

a = make("ja", "en")   # 起動直後に日本語で作られた窓（MMD は英語モード）
got = ticks(a, 4)
check("2. 違えば 4 回目（2 秒）で作り直す", got == [False, False, False, True] and len(a.hub.rebuilt) == 1, str(got))

a = make("ja", "en", busy=True)
check("3. 生成中は作り直さない", not any(ticks(a, 12)) and not a.hub.rebuilt)
a.busy = False
check("3. 生成が終わったら作り直す", any(ticks(a, 4)) and len(a.hub.rebuilt) == 1)

a = make("ja", RuntimeError("MMD control did not respond"))
check("4. 読めない時は作り直さない", not any(ticks(a, 12)) and not a.hub.rebuilt)

print("---")
print(f"{sum(results)}/{len(results)} 通った")
sys.exit(0 if all(results) else 1)
