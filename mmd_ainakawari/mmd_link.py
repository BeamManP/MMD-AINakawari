"""開いている MMD とのやり取り（mmd-mcp の中の関数を直接使う）。"""
import os

from mmd_mcp import bone_state
from mmd_mcp import edit_actions
from mmd_mcp import file_operations as files
from mmd_mcp import playback
from mmd_mcp import scene_controls as scene
from mmd_mcp import timeline
from mmd_mcp.bone_controls import get_selected_bone_transform
from mmd_mcp.bone_selection import select_bone
from mmd_mcp.ui_state import UIReader, get_ui_state
from mmd_mcp.windows import list_windows

from . import mmd_memory, vmd

# MMD の中のモデルのデータでの、読み込んだファイルの場所（UTF-16・256 文字）。
# MMDPlugin のヘッダ（MMDModelData::file_path・9.31 の解析）の位置で、9.32 でもそのまま読めた（11-03）。
MODEL_FILE_PATH = 9544


class MMDLink:
    def __init__(self, hwnd=None):
        self._hwnd = hwnd

    @property
    def hwnd(self):
        if self._hwnd:
            return self._hwnd
        wins = [w.public_info() for w in list_windows()]
        if not wins:
            raise RuntimeError("MMD が起動していません")
        if len(wins) > 1:
            raise RuntimeError(f"MMD が {len(wins)} 個起動しています。1 つにしてください")
        return wins[0]["hwnd"]

    @property
    def key(self):
        """相手の MMD の見分け（プロセス番号と起動時刻。MMD を開き直すと変わる）。"""
        hwnd = self.hwnd
        wins = [w for w in list_windows() if w.hwnd == hwnd]
        if not wins:
            raise RuntimeError("MMD が閉じられました")
        return f"{wins[0].pid}-{wins[0].process_started:.0f}"

    def state(self):
        s = get_ui_state(self.hwnd)
        return {"frame": s["displayed_frame"]["value"], "model": s["model_selector"]["selected_name"],
                "model_selected": not s["model_selector"]["camera_light_accessory_selected"]}

    def selected_model(self):
        """MMD で選択中のモデルの名前と、読み込んだファイルの場所。モデル以外が選ばれていれば None。

        MMD のメモリを読むので、mmd-mcp と同じく検証済みの MMD 9.32 x64 の実行ファイルでだけ動く。
        画面のモデル欄の名前とメモリの名前を突き合わせ、合わなければ止める。
        """
        hwnd = self.hwnd
        _, selector_index, name = UIReader(hwnd).anchor()  # モデル欄だけ読む（get_ui_state は全部読むので 0.6 秒かかる）
        if selector_index <= 0:  # 0 はカメラ・照明・アクセサリ
            return None
        target = next((w for w in list_windows() if w.hwnd == hwnd), None)
        if target is None:
            raise RuntimeError("MMD が閉じられました")
        memory = bone_state.BoneMemory(target)
        try:
            main = memory.pointer(memory.base + bone_state.MAIN_POINTER_RVA)
            slot = memory.integer(main + bone_state.SELECTED_MODEL)
            if not 0 <= slot < 255:
                return None
            model = memory.pointer(main + bone_state.MODEL_TABLE + slot * 8)
            if not model:
                return None
            names = {bone_state.decode_name(memory.read(model + offset, 50))
                     for offset in (bone_state.MODEL_NAME_JA, bone_state.MODEL_NAME_EN)}
            path = memory.read(model + MODEL_FILE_PATH, 512).decode("utf-16-le", errors="replace").split("\0", 1)[0]
        finally:
            memory.close()
        if name not in names:
            raise RuntimeError(f"MMD のモデル欄（{name}）と中のモデルが合いません。もう一度選び直してください")
        return {"name": name, "path": path}

    def current_frame(self):
        """MMD で今いるフレーム（タイムラインの上の現在フレームの欄）。読めなければ None。"""
        text = UIReader(self.hwnd).edit(417)
        return int(text) if text and text.strip().isdigit() else None

    def selected_key_frames(self):
        """タイムラインで選んでいるボーンのキーのフレーム（昇順）。選んでいなければ空。

        「選んだキーの間」の範囲に使う。前は MMD の範囲選択の欄（タイムラインの下の開始〜終了フレーム）を読んでいたが、
        場所が分かりにくく、キーを選ぶ方が MMD の操作として自然なので替えた（11-04 マスター）。
        """
        return self.key_scan()[0]

    def key_scan(self, with_names=False):
        """(選んでいるキーのフレーム, 骨の名前 → キーのフレーム。with_names が False なら None)。mmd_memory.MotionReader.scan。"""
        reader = mmd_memory.MotionReader(self.hwnd)
        try:
            return reader.scan(with_names)
        finally:
            reader.close()

    def read_motion(self, path):
        """選択中のモデルのモーションを MMD のメモリから読み、VMD にして path に書く（「元に戻す」の控え）。読んだ vmd.Motion を返す。

        中身は MMD の書き出しと同じ（11-04、体のキー 2317・表情 69・表示/IK を突き合わせて一致。補間の各行の末尾の詰め物だけ違う）。
        書き出しのダイアログ（2.3 秒）と違って 0.06 秒で、0F にキーが無くてもフレームが詰まらない。
        """
        model = self.selected_model()
        if model is None:
            raise RuntimeError("MMD でモデルを選んでください")
        morphs, iks = mmd_memory.read_pmx_names(model["path"])
        reader = mmd_memory.MotionReader(self.hwnd)
        try:
            motion = reader.read(morphs, iks)
        finally:
            reader.close()
        vmd.write(path, motion)
        return motion

    def export_motion(self, path):
        """選択中のモデルのモーションを丸ごと書き出す。MMD は選択したキーだけを書き出す（何も選んでいないと断る）ので、先に全部選ぶ。"""
        r = timeline.select_range(0, 999999, "全ﾌﾚｰﾑ", self.hwnd)
        if r.get("status") != "completed":
            raise RuntimeError(f"MMD で全部のキーを選択できませんでした: {r.get('status')} {r.get('dialogs', '')}")
        r = files.export_file("motion", path, True, self.hwnd)
        if r.get("status") != "completed":
            raise RuntimeError(f"MMD からモーションを書き出せませんでした: {r.get('status')} {r.get('dialogs', '')}")

    def check_model(self, model):
        """選ばれているモデルが model（PMX の場所）でなければ止める。キーを消す前・控えを取る前に呼ぶ。"""
        selected = self.selected_model()
        if selected is None or os.path.normcase(os.path.abspath(selected["path"])) != os.path.normcase(os.path.abspath(model)):
            now = selected["name"] if selected else "モデル以外"
            raise RuntimeError(f"始めた時と違うモデル（{now}）が選ばれています。キーは消していません。"
                               f"「{os.path.splitext(os.path.basename(model))[0]}」を選んでから、もう一度押してください")

    def load_motion(self, path, frame=0, model=None, restore=None):
        """選択中のモデルのモーションを、VMD の中身でまるごと置き換える。

        MMD の読み込みは足し込み（ファイルにあるキーだけ上書きし、他のキーは残す）なので、先にボーンと表情のキーを全部消す。
        「表示･IK･外親」の行は消さない（外部親は VMD に入らないので、消すと戻らない。11-09）。
        読み込みは今のフレームの分ずれるので frame（ふつう 0）へ移ってから読む。
        model: 読み込む先のモデルの PMX の場所。キーを消す直前に、選ばれているモデルがこれかを確かめ、違えば何も消さずに止める
               （生成の途中で別のモデルを選ぶと、そのモデルのキーを全部消して前のモデルの動きを入れていた。11-07 Codex のレビュー）。
        restore: キーを消した後で読み込みに失敗した時に、読み込み直すバックアップ（消したキーを戻す）。
        """
        # 再生中は MMD の場面を編集できない（mmd-mcp が断る）。生成した動きを再生して確かめている途中で「元に戻す」や
        # 「生成」を押すことがあるので、先に止める（11-04 マスター「元に戻すを押すとたまに Stop MMD playback が出る」）
        if playback.get(self.hwnd)["playing"]:
            playback.set_playback(False, hwnd=self.hwnd)
        if not self.state()["model_selected"]:
            raise RuntimeError("MMD でカメラ・照明・アクセサリが選ばれています。モデルを選んでからもう一度押してください")
        if model is not None:
            self.check_model(model)
        path = os.path.abspath(path)
        if not os.path.isfile(path):   # 消す前に確かめる
            raise RuntimeError(f"読み込むファイルがありません。キーは消していません: {path}")
        # 読み込むフレームへは、消す前に移る（消した後で移れずに止まると、戻しが走らずキーが消えたままになっていた。11-07）
        self.set_frame(frame)
        # 消すのはボーンと表情の行だけ。「全ﾌﾚｰﾑ」で消すと「表示･IK･外親」の行も消え、外部親の設定が全部外れる
        # （VMD には外部親の欄が無いので、読み込み直しても戻らない）。表示/IK のキーは残し、VMD の同じキーで上書きされる
        # （11-09 第一動作報告「ナカワリを使うと既存の外部親が全部解除される」。Tda式ミク＋ダミーボーンで再現・切り分けた）
        r = self._delete_keys("全ボーンﾌﾚｰﾑ")
        if r.get("status") != "completed":
            raise RuntimeError(f"MMD で今のキーを消せませんでした: {r.get('status')} {r.get('dialogs', '')}")
        try:   # ボーンを消した後は、何で止まっても下の戻しを通す（表情を消せなかった時も）
            r = self._delete_keys("全表情ﾌﾚｰﾑ")
            if r.get("status") == "completed" and self.current_frame() != frame:
                self.set_frame(frame)
        except Exception as e:
            r = {"status": type(e).__name__, "dialogs": str(e)}
        if r.get("status") == "completed":
            r = self._load_vmd(path)
        if r.get("status") != "completed":
            # MMD が「このファイルは Vocaloid Motion Data file ではありません」などの窓を出していると、閉じるまで操作できず、
            # 戻しの読み込みも止まる（11-07 本物の MMD で、壊れた VMD を読ませて確かめた）。ボタン 1 つのお知らせの窓だけ閉じる
            notices = self._dismiss_notices(r)
            why = "・".join(notices) or f"{r.get('status')} {r.get('dialogs', '')}".strip()
            if restore is None:
                raise RuntimeError(f"MMD にモーションを読み込めませんでした: {why}")
            try:
                self.set_frame(frame)
            except Exception as e:
                back = {"status": type(e).__name__, "dialogs": str(e)}
            else:
                back = self._load_vmd(os.path.abspath(restore))
            if back.get("status") == "completed":
                raise RuntimeError(f"MMD にモーションを読み込めませんでした（{why}）。消したキーは、バックアップから戻しました")
            raise RuntimeError(f"MMD にモーションを読み込めず（{why}）、バックアップも読み込めませんでした。"
                               f"MMD の「ファイル」→「モーションデータ読込」で、次のファイルを読み込んでください: {os.path.abspath(restore)}")

    @staticmethod
    def _dismiss_notices(result, timeout=3.0):
        """mmd-mcp の返事（dialog_requires_action）にある、ボタンが 1 つだけのお知らせの窓を閉じて、その文を返す。ほかの窓は触らない。"""
        import time

        import win32gui
        texts, closing = [], []
        for d in result.get("dialogs") or []:
            if not isinstance(d, dict):
                continue
            controls = d.get("controls") or []
            buttons = [c for c in controls if c.get("class") == "Button"]
            if len(buttons) != 1 or any(c.get("class") == "Edit" for c in controls):
                continue
            texts += [c["text"] for c in controls if c.get("class") == "Static" and c.get("text")]
            win32gui.PostMessage(buttons[0]["hwnd"], 0xF5, 0, 0)   # BM_CLICK
            closing.append(d["hwnd"])
        deadline = time.monotonic() + timeout
        while closing and time.monotonic() < deadline:
            closing = [h for h in closing if win32gui.IsWindow(h) and win32gui.IsWindowVisible(h)]
            time.sleep(0.1)
        return texts

    def _delete_keys(self, track):
        """タイムラインの範囲選択で track（「全ボーンﾌﾚｰﾑ」など）の 0〜999999F を選んで消す。mmd-mcp の返事を返す。"""
        r = timeline.select_range(0, 999999, track, self.hwnd)
        if r.get("status") == "completed":
            r = edit_actions.perform(["delete_keys"], self.hwnd)
        return r

    def _load_vmd(self, path):
        """mmd-mcp で VMD を読み込む。例外（ファイルが無い・MMD の画面が読めないなど）も失敗の返事にする（キーを消した後の戻しを通すため）。
        モデル名が長いと出る「〜用のモーションデータです 続行しますか？」は OK で進める（_accept_other_model）。"""
        try:
            r = files.load_file("motion", path, self.hwnd)
        except Exception as e:
            # mmd-mcp は、パスを送った後に閉じかけのファイルの窓を調べて落ちることがある（GetParent の 1400。11-10 に
            # 長い名前の確認の窓が出る時に 5 回中 1 回）。その時は確認の窓が出ていれば、そこから続ける
            r = self._confirm_after_error(e)
            if r is None:
                # 確認の窓も出ていない。パスは送った後なので、読み込みそのものは済んでいることが多い（11-10 に検証用の MMD で、
                # ふつうの名前のモデルでも数十回に 1〜2 回。前は失敗と見て、バックアップを重ねて読み込み、エラーの窓を出していた）。
                # MMD の中身を見て、ファイルのキーが全部入っていれば読み込めている
                if self._loaded_after_error(path):
                    from . import applog
                    applog.write(f"mmd-mcp の読み込みが例外で返りましたが、MMD にはファイルのキーが入っていました（読み込めたと見ます）: {e}")
                    return {"status": "completed", "path_submitted": True, "verified_after_error": str(e)}
                return {"status": type(e).__name__, "dialogs": str(e)}
        if r.get("status") == "dialog_requires_action" and r.get("path_submitted"):
            r = self._accept_other_model(r)
        return r

    def _confirm_after_error(self, error, wait=3.0):
        """load_file が例外で返った時に、MMD に確認の窓が出ていれば、それを dialog_requires_action の返事の形にする。無ければ None。"""
        import time
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                targets = [w for w in list_windows() if w.hwnd == self.hwnd]
                dialogs = files.owned_dialogs(targets[0]) if len(targets) == 1 else []
            except Exception:
                dialogs = []
            if dialogs:
                return {"status": "dialog_requires_action", "path_submitted": True, "dialogs": dialogs, "error": str(error)}
            time.sleep(0.1)
        return None

    def _loaded_after_error(self, path, wait=10.0):
        """load_file が例外で返り、確認の窓も出ていない時に、読み込みが実は済んでいるかを MMD のメモリで確かめる。

        読み込む前にボーンのキーを全部消している（load_motion）ので、ファイルのボーンのキー（骨・フレーム）が MMD に全部あれば、
        読み込めている。読み込めていなければ、MMD に残っているのは消せない 0F のキーだけなので、0F より後ろのキーが見つからない。
        読み込みの途中かもしれないので、wait 秒までくり返し見る。0F のキーしか無いファイルは見分けられないので False。
        """
        import time

        try:
            want = {(k.name, k.frame) for k in vmd.read(path).bones}
        except Exception:
            return False
        if not any(frame > 0 for _name, frame in want):
            return False
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                model = self.selected_model()
                morphs, iks = mmd_memory.read_pmx_names(model["path"])
                reader = mmd_memory.MotionReader(self.hwnd)
                try:
                    got = {(k.name, k.frame) for k in reader.read(morphs, iks).bones}
                finally:
                    reader.close()
                if want <= got:
                    return True
            except Exception:   # 読み込みの途中・窓が出入りしている。次でまた見る
                pass
            time.sleep(0.3)
        return False

    def _accept_other_model(self, result, timeout=60.0):
        """VMD の読み込みで「このファイルは ○○ 用のモーションデータです／同じボーン名のモーションのみを取り込む事になります／
        続行しますか？」（OK・キャンセル）が出た時だけ、OK を押して読み込みが終わるまで待つ。それ以外の窓なら result をそのまま返す。

        VMD のモデル名は 20 バイト（cp932）までなので、名前の長いモデルは MMD が書き出した VMD でも名前が合わず、毎回この確認が出る
        （11-10 動作報告。名前を 52 バイトにした Tda式ミクで再現）。読み込むのは、選んでいるモデルから書き出して作った VMD
        （load_motion の前に check_model で確かめている）なので、OK でよい。ボーン名で取り込むのは、名前が合う時と同じ。
        """
        import time

        import pywintypes
        import win32gui

        def confirm(d):
            """その窓が「〜用のモーションデータです 続行しますか？」なら (OK のボタン, 文)。違えば None。"""
            if d.get("title") != "モーションデータ読込":
                return None
            controls = d.get("controls") or []
            texts = [c.get("text") or "" for c in controls if c.get("class") == "Static"]
            ok = [c for c in controls if c.get("class") == "Button" and c.get("id") == 1]
            if len(ok) != 1 or not any("用のモーションデータです" in t and "続行しますか" in t for t in texts):
                return None
            return ok[0]["hwnd"], texts

        dialogs = [d for d in result.get("dialogs") or [] if isinstance(d, dict)]
        if len(dialogs) != 1 or confirm(dialogs[0]) is None:
            return result
        # UIReader は確認の窓が開いていると作れない（「modal dialog open」）ので、list_windows から取る
        targets = [w for w in list_windows() if w.hwnd == self.hwnd]
        if len(targets) != 1:
            return result
        target, texts, pressed = targets[0], confirm(dialogs[0])[1], set()
        deadline, quiet = time.monotonic() + timeout, None
        # 窓は毎回取り直す。窓が出入りする途中で Windows の関数が失敗することがある（11-10 に 1 回、OK を押す前に落ちた）ので、
        # 失敗したらその回は飛ばして次で取り直す
        while time.monotonic() < deadline:
            try:
                now = files.owned_dialogs(target)
                others = [d for d in now if confirm(d) is None]
                if others:   # 別の窓が出た（ほかの窓は押さない）
                    return {"status": "dialog_requires_action", "path_submitted": True, "dialogs": others}
                waiting = [d for d in now if d["hwnd"] not in pressed]
                for d in waiting:
                    win32gui.PostMessage(confirm(d)[0], 0xF5, 0, 0)   # BM_CLICK
                    pressed.add(d["hwnd"])
                if now or not win32gui.IsWindowEnabled(self.hwnd):   # 窓が消えるのを待つ・読み込み中
                    quiet = None
                else:
                    get_ui_state(self.hwnd)
                    quiet = quiet or time.monotonic()
                    if time.monotonic() - quiet >= 0.3:
                        return {"status": "completed", "path_submitted": True, "accepted": texts}
            except (pywintypes.error, ValueError, RuntimeError):
                quiet = None
            time.sleep(0.1)
        return {"status": "timeout", "path_submitted": True, "note": "OK を押した後、読み込みが終わりませんでした"}

    def set_frame(self, frame, tries=3, wait=0.5):
        """MMD の今のフレームを frame にする。

        mmd-mcp はフレームの欄に数字を入れてすぐ読み直し、数字とモデルの欄が合わないと止める。モーションを読み込んだ直後は
        MMD が忙しく、合わないことがある（11-07 マスター。生成の最後で「MMD did not display the requested frame in the same
        model context.」）。合わない時（RuntimeError）だけ、少し待ってやり直す。再生中などの止め（ValueError）はそのまま上げる。
        """
        import time
        for i in range(tries):
            try:
                return scene.set_frame(frame, self.hwnd)
            except RuntimeError:
                if i == tries - 1:
                    raise
                time.sleep(wait)

    def return_to(self, frame):
        """押した時のフレームへ戻す。動きはもう入っているので、戻せなくても止めない。戻せなかった時は理由の文を返す。"""
        try:
            self.set_frame(frame)
        except Exception as e:
            return str(e)
        return None

    def bone_value(self, name, frame):
        """あるフレームでの骨の表示値（位置 x,y,z・回転の度）。骨の選択が変わる。"""
        self.set_frame(frame)
        select_bone(name, None, self.hwnd)
        t = get_selected_bone_transform(self.hwnd)
        p = t["position"]
        return (p["x"], p["y"], p["z"])
