// MMD の下の段の右の空き地に出す「Kimodo 操作」パネル。空き地が狭い時は隠れる（メニューからは開ける）。
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
    // MMD の窓の子として作る。on_open は「Kimodo の窓を開く」が押された時に呼ぶ。
    bool create(HWND mmd, std::function<void()> on_open);
    void destroy();
    // MMD の窓の大きさが変わった時に呼ぶ。MMD が自分の部品を並べ直した後で位置を直す。
    void request_layout();

private:
    static LRESULT CALLBACK proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam);
    void layout();
    void paint();

    HWND mmd_ = nullptr;
    HWND panel_ = nullptr;
    HWND open_button_ = nullptr;
    HFONT font_ = nullptr;   // MMD のボタンの字体を借りる（自分では消さない）
    RECT placed_{};
    std::function<void()> on_open_;
};
