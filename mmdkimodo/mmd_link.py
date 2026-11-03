"""開いている MMD とのやり取り（mmd-mcp の中の関数を直接使う）。"""
import os

from mmd_mcp import edit_actions
from mmd_mcp import file_operations as files
from mmd_mcp import scene_controls as scene
from mmd_mcp import timeline
from mmd_mcp.bone_controls import get_selected_bone_transform
from mmd_mcp.bone_selection import select_bone
from mmd_mcp.ui_state import get_ui_state
from mmd_mcp.windows import list_windows


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
