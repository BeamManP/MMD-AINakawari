// MMD の下の段の右の空き地に出す「Kimodo操作」パネル。空き地が狭い時は隠れる（メニューからは開ける）。
// パネルは部品を並べるだけで、中身（プロンプト・範囲・状態）は Python の窓（mmd_ainakawari.app）が 0.5 秒ごとに読み書きする。
// 部品の番号は mmd_ainakawari/panel.py と同じ。
#pragma once
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <functional>
#include <string>

class NakawariPanel {
public:
    // MMD の窓の子として作る。on_command はボタンが押された時に、ボタンの番号で呼ぶ。
    // samples は「サンプル」で出すプロンプトの一覧のファイル（mmd_ainakawari/prompt_samples.txt。押すたびに読む）
    bool create(HWND mmd, std::function<void(int)> on_command, std::wstring samples);
    void destroy();
    // MMD の窓の大きさが変わった時に呼ぶ。MMD が自分の部品を並べ直した後で位置を直す。
    void request_layout();
    // MMD が取り出したメッセージを、MMD が見る前に見る（プラグインの WH_GETMESSAGE の受け口から）。
    // プロンプト欄宛てのキーはここで処理して WM_NULL にし、MMD のショートカットにさせない。
    // 自分で処理したら true。プロンプト欄の外を押したら、フォーカスを MMD に戻す（MMD が描く画面は押してもフォーカスが動かない）
    bool filter(MSG* message);
    // プロンプト欄（フォーカスがここにある間は MMD のショートカットを止める。nakawari_plugin.cpp の quiet_get_key_state）
    HWND prompt() const { return panel_ ? GetDlgItem(panel_, 103) : nullptr; }

private:
    static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam);
    void layout();
    bool camera_mode() const;
    void arrange(int width, int height);
    void paint();
    void draw(HDC dc);
    void draw_label(const DRAWITEMSTRUCT* item);
    COLORREF color_at(int y) const;
    HWND add(const wchar_t* cls, const wchar_t* text, DWORD style, int id, DWORD ex_style = 0);
    void show_samples();

    HWND mmd_ = nullptr;
    HWND panel_ = nullptr;
    HFONT font_ = nullptr;   // MMD のボタンの字体を一回り小さくしたもの（自分で作って消す）。ボタンだけは MMD の字体のまま
    bool status_alert_ = false;   // 状態の 1 行を赤で描く（Python が kAlertMessage で頼む。セットアップ前の案内など）
    RECT placed_{};
    std::function<void(int)> on_command_;
    std::wstring samples_;
};
