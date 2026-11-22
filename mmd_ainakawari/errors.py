"""エラーを、窓に出す文（今の言葉）にする（11-22 マスター「エラーメッセージがわかりづらい」）。

窓に出る失敗の文は、ここを通してから出す:
    except Exception as e:
        status.set(_("失敗: {error}", error=errors.explain(e)))

- AIナカワリが自分で出した文（_() で作った文）は、そのまま出す。どうすればいいかまで、その文に書く。
- mmd-mcp などから届いた英語の文（開発者・AI 向けの文）は、下の RULES で「何が起きたか＋どうすればいいか」に言い換える。
  どれにも当たらなければ共通の文にして、原文を後ろに付ける（報告をもらった時に追えるように）。
  11-22 の報告「Failed: MMD selector size is unsupported.」は、この原文がそのまま窓に出ていた。
- 自分のコードの思わぬ失敗（KeyError など）は、app.log を添えて知らせてもらう文にする。
どこで落ちたか（traceback）は、呼ぶ側で applog.exception に残す。
"""
import errno
import os
import re

from .i18n import N_, _

HERE = os.path.dirname(os.path.abspath(__file__))

# 自分の文とみなす例外の型（この中で、このフォルダのコードが raise した物）。KeyError などは思わぬ失敗の方へ
OWN_TYPES = (RuntimeError, ValueError, OSError)

class ModelError(RuntimeError):
    """モデル（PMX）が AIナカワリ の使える形でない（ボーンが足りないなど）。文は _() で作って渡す。"""


# 日本語のボーン名を持たないモデル（海外の変換モデルなど）に出す案内。ボーンの名前は訳さない（PMX の中の名前なので）
BONES_HINT = N_("AIナカワリは、MMD の標準の日本語のボーン名（センター・上半身・下半身・左足ＩＫ など）を持つ PMX のモデルで動きます")

BUSY = N_("MMD が別の操作の途中だったため、うまく読み書きできませんでした。MMD を操作していない状態で、もう一度押してください")

# mmd-mcp の英語の文 → 言い換え（上から順に見る。mmd-mcp の ui_state・windows・file_operations・native_dialogs・timeline・
# bone_state・bone_controls・bone_selection・playback・scene_controls・ui_language・pmx_geometry の raise を 11-22 に洗い出した）
RULES = [
    (r"minimized", N_("MMD の窓が最小化されています。元の大きさに戻してから、もう一度押してください")),
    (r"modal dialog|[Uu]nexpected dialog|dialog requires|[Dd]ialog did not close|did not open .+ within",
     N_("MMD で別の窓（確認やお知らせの窓など）が開いています。その窓を閉じてから、もう一度押してください")),
    (r"[Pp]layback", N_("MMD が再生中です。再生を止めてから、もう一度押してください")),
    (r"frame number|has no valid number|[Ii]nvalid numeric text|[Ff]inish (the edit|editing|entering)",
     N_("MMD の入力欄（フレーム番号など）が入力の途中です。Enter で確定してから、もう一度押してください")),
    (r"bone editing mode|camera mode|Select camera/light",
     N_("MMD がカメラ・照明・アクセサリの編集になっています。モデルを選んで「モデル編」にしてから、もう一度押してください")),
    (r"Select a model|Select an editable bone|Select a model and a bone|Model selector unavailable",
     N_("MMD でモデルを選んでから、もう一度押してください")),
    (r"Expand (the|its)|panel is not visible", N_("MMD の操作パネルが閉じています。パネルを開いてから、もう一度押してください")),
    (r"[Mm]ultiple MMD", N_("MMD が 2 つ以上開いています。1 つにしてから、もう一度押してください")),
    (r"window not found|process changed|process/window changed|UI thread changed",
     N_("MMD が閉じられたか、起動し直されました。MMD を開いてから、もう一度押してください")),
    (r"verified MMD 9\.32|could not be verified|Unsupported MMD UI language|Unsupported MMD layout|layout is unsupported|"
     r"layout validation|Owner-drawn|[Ss]election bridge|64-bit Python",
     N_("この MMD には対応していません。MMD 9.32 x64（日本語版か、中国語版 MMD932）で使ってください")),
    (r"PMX", N_("モデル（PMX）の中身を読めませんでした。ファイルが壊れているか、対応していない形式です")),
    (r"[Ii]nput file does not exist", N_("読み込むファイルが見つかりませんでした")),
    (r"file dialog rejected", N_("MMD のファイルを開く窓が、ファイルの場所を受け付けませんでした。ファイルの場所に使えない文字が無いか確かめてください")),
    (r"model selector disagree|model identity and UI selection disagree",
     N_("MMD のモデル欄と、中で選ばれているモデルが合いません。MMD でモデルを選び直してから、もう一度押してください")),
    (r"changed (during|while|before|after)|time limit|did not respond|did not finish|[Rr]etry|in progress|timed out|"
     r"disagree|did not stop|did not display|readback mismatch|selection failed|rejected|does not match the expected|"
     r"button is unavailable|[Mm]enu is missing|command is missing or disabled|Expected enabled", BUSY),
    (r"[Oo]utput directory does not exist", N_("書き出す先のフォルダが見つかりませんでした")),
]
UNKNOWN_MMD = N_("MMD の操作中に思わぬエラーが起きました。MMD を操作していない状態で、もう一度押してください。"
                 "続く時は、この文を添えて作者に知らせてください（{detail}）")
UNKNOWN = N_("思わぬエラーが起きました（{detail}）。続く時は、詳細の窓の「ログ」→「記録のフォルダを開く」にある app.log を添えて、"
             "作者に知らせてください")


def explain(e):
    """例外 e を窓に出す文（今の言葉）にする。"""
    if isinstance(e, OSError) and e.errno is not None:   # Python や Windows が出した OS のエラー（自分で raise した物は errno が無い）
        return _os_error(e)
    if isinstance(e, ModelError) or (isinstance(e, OWN_TYPES) and _raised_here(e)):
        return str(e)
    if _raised_here(e):   # 自分のコードの思わぬ失敗
        return _(UNKNOWN, detail=_detail(e))
    return explain_text(str(e), _detail(e))


def explain_text(text, detail=None):
    """mmd-mcp などの英語の文を、言い換えの文にする。当たらなければ共通の文（原文つき）。"""
    for pattern, message in RULES:
        if re.search(pattern, text or ""):
            return _(message)
    return _(UNKNOWN_MMD, detail=detail or text)


def describe(result):
    """mmd-mcp の操作の返事（{"status", "dialogs", ...}）が completed でない時の、止まった理由の文。"""
    status = str(result.get("status") or "")
    dialogs = result.get("dialogs")
    if status == "dialog_requires_action":
        titles = [d.get("title") for d in dialogs or [] if isinstance(d, dict) and d.get("title")]
        return _("MMD で別の窓（{titles}）が開いています。その窓を閉じてから、もう一度押してください",
                 titles=_("・").join(titles)) if titles else _(RULES[1][1])
    if status == "timeout":
        return _("MMD の操作が時間内に終わりませんでした。MMD の様子を確かめてから、もう一度押してください")
    if status == "verification_failed":
        return _("MMD に操作が入ったかを確かめられませんでした。MMD の様子を確かめてから、もう一度押してください")
    if status.endswith(("Error", "Exception")) or status in ("Cancelled", "Failed"):   # 例外を返事の形にした物（mmd_link）
        return explain_text(str(dialogs or ""), f"{status}: {dialogs}")
    return explain_text(f"{status} {dialogs or ''}".strip())


def _os_error(e):
    path = e.filename if e.filename else ""
    if e.errno == errno.ENOENT:
        return _("ファイルが見つかりません: {path}", path=path)
    if e.errno in (errno.EACCES, errno.EPERM):
        return _("ファイルを開けません。ほかのソフトが使っているか、書き込みが許されていない場所です: {path}", path=path)
    if e.errno == errno.ENOSPC:
        return _("ディスクの空きが足りません。空きを作ってから、もう一度押してください")
    return _("ファイルを読み書きできませんでした: {path}（{detail}）", path=path, detail=_detail(e))


def _raised_here(e):
    """e を raise したのが、このフォルダ（mmd_ainakawari）のコードか（いちばん内側の Python の段で見る）。"""
    tb = e.__traceback__
    if tb is None:
        return True   # raise していない例外（自分で作って渡した物）
    while tb.tb_next is not None:
        tb = tb.tb_next
    return os.path.abspath(tb.tb_frame.f_code.co_filename).startswith(HERE + os.sep)


def _detail(e):
    return f"{type(e).__name__}: {e}"
