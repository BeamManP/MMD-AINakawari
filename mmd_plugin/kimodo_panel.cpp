#include "kimodo_panel.h"

#include <algorithm>

extern "C" IMAGE_DOS_HEADER __ImageBase;

namespace {
constexpr wchar_t kClass[] = L"MMDKimodo.Panel";   // Python（mmdkimodo/panel.py）はこの名前でパネルを探す
constexpr wchar_t kCaption[] = L"Kimodo操作";
constexpr int kCameraButton = 536;   // 3D 画面の下の帯の「カメラ編／モデル編」。下の段の操作パネルはこの下にある
// 下の段のパネルの上端は「カメラ編」の下端から 26px 下（11-03 モデル用のモードで 807 → 833 を実測）。
// カメラ用のモードではその間（y 808 前後）にも部品があるので、部品の上端からは決めない
constexpr int kStripGap = 26;
constexpr int kMinWidth = 420;   // これより狭いと部品が並ばないので隠す
constexpr int kMaxWidth = 820;
constexpr int kMinHeight = 130;
constexpr int kCaptionHeight = 18;
constexpr int kButtonsWidth = 110;
// 部品の番号（mmdkimodo/panel.py と同じ）
constexpr int kEngine = 101;
constexpr int kRange = 102;
constexpr int kPrompt = 103;
constexpr int kGenerate = 104;
constexpr int kUndo = 105;
constexpr int kDetails = 106;
constexpr int kStatus = 107;
constexpr int kPromptLabel = 108;
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

HWND KimodoPanel::add(const wchar_t* cls, const wchar_t* text, DWORD style, int id, DWORD ex_style) {
    const HWND control = CreateWindowExW(ex_style, cls, text, WS_CHILD | WS_VISIBLE | style, 0, 0, 10, 10, panel_,
                                         reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)), instance(), nullptr);
    if (control && font_) SendMessageW(control, WM_SETFONT, reinterpret_cast<WPARAM>(font_), FALSE);
    return control;
}

bool KimodoPanel::create(HWND mmd, std::function<void(int)> on_command) {
    mmd_ = mmd;
    on_command_ = std::move(on_command);
    WNDCLASSW wc{};
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = proc;
    wc.hInstance = instance();
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.lpszClassName = kClass;
    RegisterClassW(&wc);  // MMD 1 つにプラグインは 1 つなので、登録も 1 回
    panel_ = CreateWindowExW(0, kClass, kCaption, WS_CHILD | WS_CLIPSIBLINGS | WS_CLIPCHILDREN, 0, 0, kMinWidth, 100,
                             mmd_, nullptr, instance(), this);
    if (!panel_) return false;
    if (const HWND camera = GetDlgItem(mmd_, kCameraButton)) {
        font_ = reinterpret_cast<HFONT>(SendMessageW(camera, WM_GETFONT, 0, 0));
    }
    const HWND engine = add(L"COMBOBOX", L"", CBS_DROPDOWNLIST | WS_TABSTOP | WS_VSCROLL, kEngine);
    SendMessageW(engine, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(L"プロンプトで作る"));
    SendMessageW(engine, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(L"中割り"));
    SendMessageW(engine, CB_SETCURSEL, 0, 0);
    add(L"BUTTON", L"選んだキーの間", BS_AUTOCHECKBOX | WS_TABSTOP, kRange);
    add(L"STATIC", L"プロンプト（英語・行ごとに「45: 動き」でそのフレームから）", SS_OWNERDRAW, kPromptLabel);
    add(L"EDIT", L"", WS_TABSTOP | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_WANTRETURN, kPrompt, WS_EX_CLIENTEDGE);
    add(L"BUTTON", L"生成", BS_PUSHBUTTON | WS_TABSTOP, kGenerate);
    add(L"BUTTON", L"元に戻す", BS_PUSHBUTTON | WS_TABSTOP, kUndo);
    add(L"BUTTON", L"詳しく…", BS_PUSHBUTTON | WS_TABSTOP, kDetails);
    add(L"STATIC", L"MMDKimodo を起動中…", SS_OWNERDRAW, kStatus);
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
    if (label_brush_) DeleteObject(label_brush_);
    label_brush_ = nullptr;
    UnregisterClassW(kClass, instance());
}

void KimodoPanel::request_layout() {
    if (panel_) PostMessageW(panel_, kLayoutMessage, 0, 0);
}

// 下の段の一番右のパネルの右に置く。右に kMinWidth が取れなければ隠す。
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
    const int width = std::min(kMaxWidth, static_cast<int>(client.right) - x - 4);
    const bool fits = strip.right > 0 && width >= kMinWidth && client.bottom - y >= kMinHeight;
    if (!fits) {
        if (IsWindowVisible(panel_)) ShowWindow(panel_, SW_HIDE);
        placed_ = {};
        return;
    }
    const RECT want{x, y, x + width, client.bottom};
    if (!EqualRect(&want, &placed_) || !IsWindowVisible(panel_)) {
        SetWindowPos(panel_, HWND_TOP, want.left, want.top, want.right - want.left, want.bottom - want.top,
                     SWP_NOACTIVATE | SWP_SHOWWINDOW);
        placed_ = want;
        arrange(want.right - want.left, want.bottom - want.top);
    }
}

// 部品を並べる: 左に切り替え・範囲・プロンプト、右にボタン、下に状態の 1 行。
void KimodoPanel::arrange(int width, int height) {
    const int pad = 8;
    const int top = kCaptionHeight + 6;
    const int right = width - pad - kButtonsWidth;   // 右のボタンの列の左端
    const int status_top = height - 22;
    auto place = [this](int id, int x, int y, int w, int h) {
        SetWindowPos(GetDlgItem(panel_, id), nullptr, x, y, std::max(1, w), std::max(1, h), SWP_NOZORDER | SWP_NOACTIVATE);
    };
    place(kEngine, pad, top, 160, 200);   // 高さは開いた時の一覧の高さ。幅は「プロンプトで作る」が切れない幅（130 だと切れた）
    place(kRange, pad + 170, top + 2, right - pad - 180, 18);
    place(kPromptLabel, pad, top + 28, right - pad * 2, 14);
    place(kPrompt, pad, top + 44, right - pad * 2, status_top - (top + 44) - 4);
    place(kGenerate, right, top, kButtonsWidth, 44);
    place(kUndo, right, top + 50, kButtonsWidth, 24);
    place(kDetails, right, top + 78, kButtonsWidth, 24);
    place(kStatus, pad, status_top, width - pad * 2, 16);
    // 範囲のチェックの字の背景は、その高さのグラデーションの色（隣のパネルの字と同じく背景になじませる）
    if (label_brush_) DeleteObject(label_brush_);
    label_brush_ = CreateSolidBrush(color_at(top + 10));
    InvalidateRect(panel_, nullptr, TRUE);
}

COLORREF KimodoPanel::color_at(int y) const {
    RECT r;
    GetClientRect(panel_, &r);
    const int height = std::max(1, static_cast<int>(r.bottom));
    y = std::max(0, std::min(y, height));
    return RGB(kTop[0] + (kBottom[0] - kTop[0]) * y / height, kTop[1] + (kBottom[1] - kTop[1]) * y / height,
               kTop[2] + (kBottom[2] - kTop[2]) * y / height);
}

void KimodoPanel::paint() {
    PAINTSTRUCT ps;
    const HDC dc = BeginPaint(panel_, &ps);
    RECT r;
    GetClientRect(panel_, &r);
    for (int y = 0; y < r.bottom; ++y) {
        const RECT line{0, y, r.right, y + 1};
        const HBRUSH brush = CreateSolidBrush(color_at(y));
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

// 字の部品（プロンプトの見出し・状態の 1 行）は、背景のグラデーションの上に白い字で描く。
// 字は Python が WM_SETTEXT で書き換える（SS_OWNERDRAW は書き換えで描き直しが来る）
void KimodoPanel::draw_label(const DRAWITEMSTRUCT* item) {
    const RECT in_panel = client_rect_of(item->hwndItem, panel_);
    for (int y = item->rcItem.top; y < item->rcItem.bottom; ++y) {
        const RECT line{item->rcItem.left, y, item->rcItem.right, y + 1};
        const HBRUSH brush = CreateSolidBrush(color_at(in_panel.top + y));
        FillRect(item->hDC, &line, brush);
        DeleteObject(brush);
    }
    wchar_t text[512]{};
    GetWindowTextW(item->hwndItem, text, 512);
    SetBkMode(item->hDC, TRANSPARENT);
    SetTextColor(item->hDC, item->CtlID == kStatus ? RGB(255, 255, 200) : RGB(220, 230, 230));
    const HGDIOBJ old = font_ ? SelectObject(item->hDC, font_) : nullptr;
    RECT r = item->rcItem;
    DrawTextW(item->hDC, text, -1, &r, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX);
    if (old) SelectObject(item->hDC, old);
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
        case WM_DRAWITEM:
            self->draw_label(reinterpret_cast<const DRAWITEMSTRUCT*>(lparam));
            return TRUE;
        case WM_CTLCOLORSTATIC:
        case WM_CTLCOLORBTN:
            if (reinterpret_cast<HWND>(lparam) == GetDlgItem(hwnd, kRange) && self->label_brush_) {
                const HDC dc = reinterpret_cast<HDC>(wparam);
                SetTextColor(dc, RGB(255, 255, 255));
                SetBkColor(dc, self->color_at(kCaptionHeight + 16));
                return reinterpret_cast<LRESULT>(self->label_brush_);
            }
            break;
        case WM_COMMAND:
            if (HIWORD(wparam) == BN_CLICKED && (LOWORD(wparam) == kGenerate || LOWORD(wparam) == kUndo
                                                 || LOWORD(wparam) == kDetails) && self->on_command_) {
                self->on_command_(LOWORD(wparam));
            }
            return 0;
        default:
            break;
        }
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}
