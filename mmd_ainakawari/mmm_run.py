"""MMM（MikuMikuMoving）で 1 回生成する入口。MMM の中の「AIナカワリ」のボタン（mmm-mcp の bridge）から呼ぶ。手で回してもよい。

    python -m mmd_ainakawari.mmm_run --engine motionbricks           # 選んだキーの最初から最後までを中割り
    python -m mmd_ainakawari.mmm_run --engine kimodo --prompt "A person walks forward."
    python -m mmd_ainakawari.mmm_run --undo                          # 前回の生成の前に戻す（MMM の Ctrl+Z でも戻る）

窓（app.py）は MMD の窓ごとに作る作りなので、MMM では使わない。設定の既定は窓と同じ（範囲は選んだキーの間・間引きは既定の段）。
進み具合は 1 行ずつ標準出力に出す（ボタンの窓がそのまま見せる）。最後の行は「OK: …」か「NG: …」。
"""
import argparse
import sys
import traceback

from . import resident, runner, smooth_stop, thin
from .i18n import _
from .mmm_link import MMMLink


def main(argv=None):
    ap = argparse.ArgumentParser(description="MMM で AIナカワリ を 1 回動かす")
    ap.add_argument("--engine", choices=["motionbricks", "kimodo"], default="motionbricks")
    ap.add_argument("--prompt", default="A person moves naturally between poses.")
    ap.add_argument("--all", action="store_true", help="範囲を使わず全部を作り直す（Kimodo の時だけ）")
    ap.add_argument("--thin", type=int, default=thin.DEFAULT_LEVEL, help="生成したキーの間引き（0 は間引かない）")
    ap.add_argument("--key-stop", action="store_true", help="中割りで、キーごとに止まる")
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--no-llama", action="store_true", help="Llama を使わず、サンプルの文だけで作る")
    ap.add_argument("--undo", action="store_true", help="前回の生成の前に戻す")
    a = ap.parse_args(argv)
    # 出力は utf-8 で 1 行ずつ（ボタンの窓が読む）
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    log = lambda line: print(line, flush=True)
    link = MMMLink()
    try:
        if a.undo:
            last = runner.load_last_run(link)
            if not last:
                raise RuntimeError(_("戻せる前回の生成がありません（MMM の Ctrl+Z でも戻せます）"))
            runner.undo(last["backup"], log, link=link, model=last.get("model"))
            print("OK: " + _("元に戻しました"), flush=True)
            return 0
        mb = a.engine == "motionbricks"
        if mb and not smooth_stop.available():
            raise RuntimeError(_("MotionBricks がまだ入っていません。MMD 版の「セットアップ」で入れてください"))
        rng = (None, None)
        if not (a.all and not mb):
            keys = link.selected_key_frames()
            if len(keys) < 2:
                raise RuntimeError(_("MMM のタイムラインで、作り直す範囲の最初と最後のキーを選んでください（2 つ以上のフレーム）"))
            rng = (keys[0], keys[-1])
        common = dict(range_start=rng[0], range_end=rng[1], key_stop=a.key_stop, thin=a.thin)
        if mb:
            s = runner.Settings(prompt="", engine="motionbricks", **common)
        else:
            s = runner.Settings(prompt=a.prompt, seed=a.seed, engine="kimodo", use_llama=not a.no_llama,
                                smooth_stop=smooth_stop.available(), **common)
        runner.generate(s, log, link=link)
        print("OK: " + _("できました。MMM で再生して確かめてください（Ctrl+Z で生成の前に戻ります）"), flush=True)
        return 0
    except resident.Cancelled:
        print("NG: " + _("中断しました（MMM のキーはそのままです）"), flush=True)
        return 1
    except Exception as e:
        traceback.print_exc(file=sys.stderr)
        print(f"NG: {e}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
