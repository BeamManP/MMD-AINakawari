"""画面に出す文の言葉（日本語・英語）。MMD が英語モード（ヘルプ → English Mode）の時は英語にする（11-11 マスター）。

書き方:
    from .i18n import _, N_
    log(_("MMD に読み込み中…"))
    raise RuntimeError(_("PMX が見つかりません: {path}", path=pmx))
    NOTE = N_("…")        # 後で _(NOTE) で訳す定数（N_ は何もしない。確認スクリプトが訳の表と突き合わせる印）

- 文の中身は日本語のまま書く。英語の時だけ texts/en_*.py の表（日本語 → 英語）から引き、表に無ければ日本語で出す。
- 差し込みは {名前}（str.format）。f-string の中身を _() に入れない（表から引けなくなる）。差し込みがある時の { } は {{ }} と書く。
- 言葉は MMD ごとの窓が、その MMD のモードで決める。モードが変わったら（起動直後の取り違えも）、窓が 2 秒ごとに見て作り直す
  （app.App._check_language。0.4.1。0.4.0 は窓を作る時に 1 回読むだけで、MMD の起動直後は英語モードでも日本語になった）。
  窓の部品は窓の tr（translator）で、生成などの仕事のスレッドは use(言葉) の中で _() を呼ぶ。
  どちらも決まっていない所（窓より前の知らせなど）は、最初に開いた MMD の言葉（set_default）。
- 訳の漏れ・表の余り・差し込みの食い違いは tests/check_i18n.py が探す。訳さない日本語（ボーンの名前・MMD の部品の文字など）は
  その行の末尾に「# i18n: skip」と書く。
"""
import contextlib
import contextvars
import importlib
import os
import pkgutil
import threading

LANGS = ("ja", "en")
NAME = {"ja": "AIナカワリ", "en": "AI Nakawari"}   # 名前（英語の時は AI Nakawari。11-11 マスター）

_LANG = contextvars.ContextVar("ainakawari_lang", default=None)
_default = "ja"
_tables = {}
_lock = threading.Lock()


def N_(text):
    """訳す定数の印（中身はそのまま返す。訳すのは使う所の _()）。"""
    return text


def _table(lang):
    """texts/<lang>_*.py の表（TEXT）をまとめた物。同じ文に違う訳があれば止める（確認スクリプトでも見る）。"""
    with _lock:
        if lang not in _tables:
            merged, where = {}, {}
            folder = os.path.join(os.path.dirname(__file__), "texts")
            for info in pkgutil.iter_modules([folder]):
                if not info.name.startswith(lang + "_"):
                    continue
                table = importlib.import_module(f"{__package__}.texts.{info.name}").TEXT
                for ja, text in table.items():
                    if ja in merged and merged[ja] != text:
                        raise ValueError(f"訳が 2 つあります（{where[ja]}・{info.name}）: {ja!r}")
                    merged[ja], where[ja] = text, info.name
            _tables[lang] = merged
        return _tables[lang]


def lang():
    """今の言葉（"ja"・"en"）。"""
    return _LANG.get() or _default


def set_default(value):
    """決まっていない所の言葉（最初に開いた MMD の言葉）。"""
    global _default
    _default = _check(value)


def _check(value):
    if value not in LANGS:
        raise ValueError(f"言葉は {LANGS} のどれか（{value!r}）")
    return value


@contextlib.contextmanager
def use(value):
    """この中（このスレッド）では value の言葉で _() を引く。生成などの仕事のスレッドを包む。"""
    token = _LANG.set(_check(value))
    try:
        yield
    finally:
        _LANG.reset(token)


def translate(text, lang_, /, **kw):
    if lang_ != "ja":
        text = _table(lang_).get(text, text)
    return text.format(**kw) if kw else text


def _(text, /, **kw):
    """text を今の言葉にする。kw は {名前} への差し込み（text は位置だけで受けるので、差し込みの名前に text も使える）。"""
    return translate(text, lang(), **kw)


def translator(value):
    """value の言葉に決めた _()（窓の部品用。MMD ごとの窓は、それぞれの言葉の tr を持つ）。"""
    value = _check(value)
    return lambda text, /, **kw: translate(text, value, **kw)


def name(value=None):
    """AIナカワリ の名前（英語の時は AI Nakawari）。"""
    return NAME[value or lang()]
