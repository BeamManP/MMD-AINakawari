#include "kimodo_panel.h"

#include <algorithm>

extern "C" IMAGE_DOS_HEADER __ImageBase;

namespace {
constexpr wchar_t kClass[] = L"MMDKimodo.Panel";
constexpr wchar_t kCaption[] = L"Kimodo操作";
constexpr int kCameraButton = 536;   // 3D 画面の下の帯の「カメラ編／モデル編」。下の段の操作パネルはこの下にある
// 下の段のパネルの上端は「カメラ編」の下端から 26px 下（11-03 モデル用のモードで 807 → 833 を実測）。
// カメラ用のモードではその間（y 808 前後）にも部品があるので、部品の上端からは決めない
constexpr int kStripGap = 26;
constexpr int kWidth = 170;
constexpr int kCaptionHeight = 18;
constexpr int kOpenButton = 1;
constexpr UINT kLayoutMessage = WM_APP + 1;
constexpr UINT_PTR kLayoutTimer = 1;  // カメラ用のモードにすると下の段が右に伸びるので、時々測り直す
// 隣のパネルと同じ縦のグラデーション（ボーン操作は 49,49,99 → 22,22,45）で、色だけ青緑にする。
constexpr int kTop[3] = {49, 99, 99};
constexpr int kBottom[3] = {22, 45, 45};

HINSTANCE instance() { return reinterpret_cast<HINSTANCE>(&__ImageBase); }

RECT client_rect_of(HWND child, HWND parent) {
    RECT r;
    GetWindowRect(child, &r);
    MapWindowPoints(nullptr, parent, reinterpret_cast<POINT*>(&r), 2);
    return r;
}

// 下の段に並ぶ MMD の部品の右端。
struct Strip {
    HWND mmd;
    HWND skip;
    int top;
    int right = 0;
};

BOOL CALLBACK measure(HWND child, LPARAM param) {
    auto* strip = reinterpret_cast<Strip*>(param);
    if (GetParent(child) != strip->mmd || child == strip->skip || !IsWindowVisible(child)) return TRUE;
    const RECT r = client_rect_of(child, strip->mmd);
    if (r.top >= strip->top) strip->right = std::max(strip->right, static_cast<int>(r.right));
    return TRUE;
}
}  // namespace

bool KimodoPanel::create(HWND mmd, std::function<void()> on_open) {
    mmd_ = mmd;
    on_open_ = std::move(on_open);
    WNDCLASSW wc{};
    wc.lpfnWndProc = proc;
    wc.hInstance = instance();
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.lpszClassName = kClass;
    RegisterClassW(&wc);  // MMD 1 つにプラグインは 1 つなので、登録も 1 回
    panel_ = CreateWindowExW(0, kClass, kCaption, WS_CHILD | WS_CLIPSIBLINGS | WS_CLIPCHILDREN, 0, 0, kWidth, 100,
                             mmd_, nullptr, instance(), this);
    if (!panel_) return false;
    if (const HWND camera = GetDlgItem(mmd_, kCameraButton)) {
        font_ = reinterpret_cast<HFONT>(SendMessageW(camera, WM_GETFONT, 0, 0));
    }
    open_button_ = CreateWindowExW(0, L"BUTTON", L"Kimodo の窓を開く", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                                   8, kCaptionHeight + 8, kWidth - 16, 26, panel_,
                                   reinterpret_cast<HMENU>(static_cast<INT_PTR>(kOpenButton)), instance(), nullptr);
    if (font_) SendMessageW(open_button_, WM_SETFONT, reinterpret_cast<WPARAM>(font_), FALSE);
    SetTimer(panel_, kLayoutTimer, 500, nullptr);
    request_layout();
    return true;
}

void KimodoPanel::destroy() {
    if (panel_) {
        KillTimer(panel_, kLayoutTimer);
        DestroyWindow(panel_);
        panel_ = nullptr;
    }
    UnregisterClassW(kClass, instance());
}

void KimodoPanel::request_layout() {
    if (panel_) PostMessageW(panel_, kLayoutMessage, 0, 0);
}

// 下の段の一番右のパネルの右に置く。右に kWidth が取れなければ隠す。
void KimodoPanel::layout() {
    const HWND camera = GetDlgItem(mmd_, kCameraButton);
    Strip strip{mmd_, panel_, 0};
    if (camera && IsWindowVisible(camera)) {
        strip.top = client_rect_of(camera, mmd_).bottom + kStripGap;
        EnumChildWindows(mmd_, measure, reinterpret_cast<LPARAM>(&strip));
    }
    RECT client;
    GetClientRect(mmd_, &client);
    // 隣のパネルは部品の右端から 2px 先まで枠で、黒 1px・灰色の隙間 2px・次のパネルの黒 1px と並ぶ
    const int x = strip.right + 6;
    const int y = strip.top;
    const bool fits = strip.right > 0 && client.right - x >= kWidth && client.bottom - y > kCaptionHeight + 40;
    if (!fits) {
        if (IsWindowVisible(panel_)) ShowWindow(panel_, SW_HIDE);
        placed_ = {};
        return;
    }
    const RECT want{x, y, x + kWidth, client.bottom};
    if (!EqualRect(&want, &placed_) || !IsWindowVisible(panel_)) {
        SetWindowPos(panel_, HWND_TOP, want.left, want.top, want.right - want.left, want.bottom - want.top,
                     SWP_NOACTIVATE | SWP_SHOWWINDOW);
        placed_ = want;
    }
}

void KimodoPanel::paint() {
    PAINTSTRUCT ps;
    const HDC dc = BeginPaint(panel_, &ps);
    RECT r;
    GetClientRect(panel_, &r);
    const int height = std::max(1, static_cast<int>(r.bottom));
    for (int y = 0; y < r.bottom; ++y) {
        const int c[3] = {kTop[0] + (kBottom[0] - kTop[0]) * y / height, kTop[1] + (kBottom[1] - kTop[1]) * y / height,
                          kTop[2] + (kBottom[2] - kTop[2]) * y / height};
        const RECT line{0, y, r.right, y + 1};
        const HBRUSH brush = CreateSolidBrush(RGB(c[0], c[1], c[2]));
        FillRect(dc, &line, brush);
        DeleteObject(brush);
    }
    FrameRect(dc, &r, static_cast<HBRUSH>(GetStockObject(BLACK_BRUSH)));
    RECT caption{0, 1, r.right, kCaptionHeight};
    SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, RGB(255, 255, 255));
    const HGDIOBJ old = font_ ? SelectObject(dc, font_) : nullptr;
    DrawTextW(dc, kCaption, -1, &caption, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    if (old) SelectObject(dc, old);
    EndPaint(panel_, &ps);
}

LRESULT CALLBACK KimodoPanel::proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_NCCREATE) {
        SetWindowLongPtrW(hwnd, GWLP_USERDATA,
                          reinterpret_cast<LONG_PTR>(reinterpret_cast<CREATESTRUCTW*>(lparam)->lpCreateParams));
    }
    auto* self = reinterpret_cast<KimodoPanel*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (self && self->panel_ == hwnd) {
        switch (message) {
        case WM_PAINT:
            self->paint();
            return 0;
        case WM_ERASEBKGND:
            return 1;
        case WM_TIMER:
            if (wparam == kLayoutTimer) self->layout();
            return 0;
        case kLayoutMessage:
            self->layout();
            return 0;
        case WM_COMMAND:
            if (LOWORD(wparam) == kOpenButton && HIWORD(wparam) == BN_CLICKED && self->on_open_) self->on_open_();
            return 0;
        default:
            break;
        }
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}
