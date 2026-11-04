// MMD の下の段の右の空き地に出す「Kimodo操作」パネル。空き地が狭い時は隠れる（メニューからは開ける）。
// パネルは部品を並べるだけで、中身（プロンプト・範囲・状態）は Python の窓（mmdkimodo.app）が 0.5 秒ごとに読み書きする。
// 部品の番号は mmdkimodo/panel.py と同じ。
#pragma once
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include <functional>

class KimodoPanel {
public:
    // MMD の窓の子として作る。on_command はボタンが押された時に、ボタンの番号で呼ぶ。
    bool create(HWND mmd, std::function<void(int)> on_command);
    void destroy();
    // MMD の窓の大きさが変わった時に呼ぶ。MMD が自分の部品を並べ直した後で位置を直す。
    void request_layout();

private:
    static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam);
    void layout();
    void arrange(int width, int height);
    void paint();
    void draw(HDC dc);
    void draw_label(const DRAWITEMSTRUCT* item);
    COLORREF color_at(int y) const;
    HWND add(const wchar_t* cls, const wchar_t* text, DWORD style, int id, DWORD ex_style = 0);

    HWND mmd_ = nullptr;
    HWND panel_ = nullptr;
    HFONT font_ = nullptr;   // MMD のボタンの字体を一回り小さくしたもの（自分で作って消す）。ボタンだけは MMD の字体のまま
    HBRUSH label_brush_ = nullptr;
    RECT placed_{};
    std::function<void(int)> on_command_;
};
