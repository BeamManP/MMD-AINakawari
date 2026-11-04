"""開いている MMD とのやり取り（mmd-mcp の中の関数を直接使う）。"""
import os

from mmd_mcp import bone_state
from mmd_mcp import edit_actions
from mmd_mcp import file_operations as files
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

    def range_selection(self):
        """MMD の範囲選択の欄（タイムラインの下の開始〜終了フレーム）。MMD の初期値は 0〜999999。読めなければ None。"""
        reader = UIReader(self.hwnd)
        start, end = reader.edit(425), reader.edit(426)
        if not (start and end and start.strip().isdigit() and end.strip().isdigit()):
            return None
        return int(start), int(end)

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

    def load_motion(self, path, frame=0):
        """選択中のモデルのモーションを、VMD の中身でまるごと置き換える。

        MMD の読み込みは足し込み（ファイルにあるキーだけ上書きし、他のキーは残す）なので、先に全部のキーを消す。
        読み込みは今のフレームの分ずれるので frame（ふつう 0）へ移ってから読む。
        """
        if not self.state()["model_selected"]:
            raise RuntimeError("MMD でカメラ・照明・アクセサリが選ばれています。モデルを選んでからもう一度押してください")
        path = os.path.abspath(path)
        r = timeline.select_range(0, 999999, "全ﾌﾚｰﾑ", self.hwnd)
        if r.get("status") == "completed":
            r = edit_actions.perform(["delete_keys"], self.hwnd)
        if r.get("status") != "completed":
            raise RuntimeError(f"MMD で今のキーを消せませんでした: {r.get('status')} {r.get('dialogs', '')}")
        scene.set_frame(frame, self.hwnd)
        r = files.load_file("motion", path, self.hwnd)
        if r.get("status") != "completed":
            raise RuntimeError(f"MMD にモーションを読み込めませんでした: {r.get('status')} {r.get('dialogs', '')}")

    def set_frame(self, frame):
        scene.set_frame(frame, self.hwnd)

    def bone_value(self, name, frame):
        """あるフレームでの骨の表示値（位置 x,y,z・回転の度）。骨の選択が変わる。"""
        scene.set_frame(frame, self.hwnd)
        select_bone(name, None, self.hwnd)
        t = get_selected_bone_transform(self.hwnd)
        p = t["position"]
        return (p["x"], p["y"], p["z"])
