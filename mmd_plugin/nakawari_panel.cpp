#include "nakawari_panel.h"

#include <algorithm>
#include <cwchar>
#include <cstdio>
#include <string>
#include <utility>
#include <vector>

extern "C" IMAGE_DOS_HEADER __ImageBase;

namespace {
constexpr wchar_t kClass[] = L"AINakawari.Panel";   // Python（mmd_ainakawari/panel.py）はこの名前でパネルを探す
constexpr wchar_t kCaption[] = L"AIナカワリ簡易操作";
constexpr int kCameraButton = 536;   // 3D 画面の下の帯の「カメラ編／モデル編」。字体を借りる・今のモードを見る
constexpr wchar_t kModelModeText[] = L"モデル編";   // カメラ用のモードの時の、このボタンの字
// 下の段のパネルの上端は、各パネルの見出しの「－」ボタン（14×14）の 2px 上（11-04 カメラ用のモードで 834 → 832、下端は 986）。
// 前は「カメラ編」の下端＋26px で決めていたが、カメラ用のモードではカメラ編が 3D 画面の下（606）に上がるので、
// パネルが 170px 上から始まって窓の下まで伸びていた（11-04 マスター「クソデカサイズ」）
constexpr wchar_t kFoldText[] = L"－";
constexpr int kFoldSize = 14;
constexpr int kFoldGap = 2;
// 三行式（11-05 マスター）: モード選択と範囲の字・プロンプト 1 行（下に「サンプル」）・生成／元に戻す／詳細、と下に状態の 1 行。
// 横は MMD のパネル 1〜2 枚分。窓が狭くて入りきらない時は、MMD のほかのパネルと同じく右端で切れて見える（隠さない）
constexpr int kWidth = 240;
constexpr int kMinVisible = 40;  // 右に見えるのがこれより狭い時だけ隠す
constexpr int kFontHeight = 10;  // MMD の字（ＭＳ Ｐゴシック・高さ 12）より一回り小さく（11-04 マスター）
constexpr int kMinHeight = 110;
constexpr int kCaptionHeight = 16;
// 部品の番号（mmd_ainakawari/panel.py と同じ）
constexpr int kEngine = 101;
constexpr int kRange = 102;
constexpr int kPrompt = 103;
constexpr int kGenerate = 104;
constexpr int kUndo = 105;
constexpr int kDetails = 106;
constexpr int kStatus = 107;
constexpr int kSamples = 108;          // 「サンプル」。押すとプロンプトの一覧が出る（英語が苦手な人向け。11-05 マスター）
constexpr UINT kFirstSample = 1000;    // 一覧の項目の番号の始まり
constexpr UINT kLayoutMessage = WM_APP + 1;
// Python が部品の押せる・押せないを頼む（wparam = 部品の番号・lparam = 押せるなら 1）。mmd_ainakawari/panel.py の ENABLE_MESSAGE。
// EnableWindow を外から呼ぶと、相手が答えるまで待って期限を付けられないので、ここで呼ぶ（11-05 Codex のレビュー）
constexpr UINT kEnableMessage = WM_APP + 2;
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

// 下の段のパネルの見出しの「－」ボタンのうち、一番上のものの上端。無ければ -1。
BOOL CALLBACK find_fold(HWND child, LPARAM param) {
    auto* strip = reinterpret_cast<Strip*>(param);
    if (GetParent(child) != strip->mmd || !IsWindowVisible(child)) return TRUE;
    const RECT r = client_rect_of(child, strip->mmd);
    if (r.right - r.left != kFoldSize || r.bottom - r.top != kFoldSize) return TRUE;
    wchar_t text[4]{};
    GetWindowTextW(child, text, 4);
    if (wcscmp(text, kFoldText) == 0 && (strip->top < 0 || r.top < strip->top)) strip->top = r.top;
    return TRUE;
}
}  // namespace

HWND NakawariPanel::add(const wchar_t* cls, const wchar_t* text, DWORD style, int id, DWORD ex_style) {
    const HWND control = CreateWindowExW(ex_style, cls, text, WS_CHILD | WS_VISIBLE | style, 0, 0, 10, 10, panel_,
                                         reinterpret_cast<HMENU>(static_cast<INT_PTR>(id)), instance(), nullptr);
    if (control && font_) SendMessageW(control, WM_SETFONT, reinterpret_cast<WPARAM>(font_), FALSE);
    return control;
}

bool NakawariPanel::create(HWND mmd, std::function<void(int)> on_command, std::wstring samples) {
    mmd_ = mmd;
    on_command_ = std::move(on_command);
    samples_ = std::move(samples);
    WNDCLASSW wc{};
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = proc;
    wc.hInstance = instance();
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.lpszClassName = kClass;
    RegisterClassW(&wc);  // MMD 1 つにプラグインは 1 つなので、登録も 1 回
    panel_ = CreateWindowExW(0, kClass, kCaption, WS_CHILD | WS_CLIPSIBLINGS | WS_CLIPCHILDREN, 0, 0, kWidth, 100,
                             mmd_, nullptr, instance(), this);
    if (!panel_) return false;
    // MMD のボタンの字体（ＭＳ Ｐゴシック）を写して、高さだけ一回り小さくする
    LOGFONTW lf{};
    const HWND camera = GetDlgItem(mmd_, kCameraButton);
    const HFONT mmd_font = camera ? reinterpret_cast<HFONT>(SendMessageW(camera, WM_GETFONT, 0, 0)) : nullptr;
    if (!mmd_font || !GetObjectW(mmd_font, sizeof(lf), &lf)) wcscpy_s(lf.lfFaceName, L"ＭＳ Ｐゴシック");
    lf.lfHeight = kFontHeight;
    lf.lfWidth = 0;
    font_ = CreateFontIndirectW(&lf);
    const HWND engine = add(L"COMBOBOX", L"", CBS_DROPDOWNLIST | WS_TABSTOP | WS_VSCROLL, kEngine);
    // 中の動きを作るモデルの名前（11-05 マスター）。0 が窓の「Kimodo」、1 が「MotionBricks」のタブ
    SendMessageW(engine, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(L"Kimodo"));
    SendMessageW(engine, CB_ADDSTRING, 0, reinterpret_cast<LPARAM>(L"MotionBricks"));
    SendMessageW(engine, CB_SETCURSEL, 0, 0);
    // 範囲は字で出すだけ（Python が「選んだキー 90〜120F」などを書く）。前はチェックで切り替えていた（11-05 マスター「チェックも無しで」）
    add(L"STATIC", L"", SS_OWNERDRAW, kRange);
    // プロンプトは 1 行。区間は「run / 45: stop」のように「 / 」でつなぐ（窓の方では行に分かれる。mmd_ainakawari/panel.py）。
    // MMD の入力欄と同じく、細い枠の平らな欄（立体の枠 WS_EX_CLIENTEDGE だと MMD の中で浮いた）
    add(L"EDIT", L"", WS_TABSTOP | WS_BORDER | ES_AUTOHSCROLL, kPrompt);
    // ボタンは MMD のボタン（再生・登録など。ＭＳ Ｐゴシック 12）と同じ字にする（11-05 マスター）。字体は MMD のを借りる（消さない）
    for (const auto& b : {std::make_pair(L"サンプルから選ぶ ▼", kSamples), std::make_pair(L"生　成", kGenerate),
                          std::make_pair(L"元に戻す", kUndo), std::make_pair(L"詳　細", kDetails)}) {
        const HWND button = add(L"BUTTON", b.first, BS_PUSHBUTTON | WS_TABSTOP, b.second);
        if (mmd_font) SendMessageW(button, WM_SETFONT, reinterpret_cast<WPARAM>(mmd_font), FALSE);
    }
    add(L"STATIC", L"AIナカワリ を起動中…", SS_OWNERDRAW, kStatus);
    SetTimer(panel_, kLayoutTimer, 500, nullptr);
    request_layout();
    return true;
}

void NakawariPanel::destroy() {
    if (panel_) {
        KillTimer(panel_, kLayoutTimer);
        DestroyWindow(panel_);
        panel_ = nullptr;
    }
    if (font_) DeleteObject(font_);
    font_ = nullptr;
    UnregisterClassW(kClass, instance());
}

void NakawariPanel::request_layout() {
    if (panel_) PostMessageW(panel_, kLayoutMessage, 0, 0);
}

// 「サンプル」: prompt_samples.txt を読んで、種類ごとの子の一覧を「サンプル」の下に出す。選んだら英語の文をプロンプト欄に入れる
// （欄の中身は Python が 0.5 秒ごとに窓へ写す）。押すたびに読むので、ファイルを書き換えればすぐ反映される
void NakawariPanel::show_samples() {
    std::wstring text;
    FILE* f = nullptr;
    if (!samples_.empty() && _wfopen_s(&f, samples_.c_str(), L"rb") == 0 && f) {
        std::string bytes;
        char buffer[4096];
        for (size_t n; (n = fread(buffer, 1, sizeof(buffer), f)) > 0;) bytes.append(buffer, n);
        fclose(f);
        if (bytes.size() >= 3 && bytes.compare(0, 3, "\xEF\xBB\xBF") == 0) bytes.erase(0, 3);   // UTF-8 の BOM
        const int n = MultiByteToWideChar(CP_UTF8, 0, bytes.data(), static_cast<int>(bytes.size()), nullptr, 0);
        text.resize(n);
        MultiByteToWideChar(CP_UTF8, 0, bytes.data(), static_cast<int>(bytes.size()), &text[0], n);
    }
    const HMENU menu = CreatePopupMenu();
    HMENU group = nullptr;
    std::vector<std::wstring> prompts;
    size_t start = 0;
    while (start < text.size()) {
        size_t end = text.find(L'\n', start);
        if (end == std::wstring::npos) end = text.size();
        std::wstring line = text.substr(start, end - start);
        start = end + 1;
        while (!line.empty() && (line.back() == L'\r' || line.back() == L' ')) line.pop_back();
        if (line.empty() || line[0] == L'#') continue;
        if (line.front() == L'[' && line.back() == L']') {   // [種類]
            group = CreatePopupMenu();
            AppendMenuW(menu, MF_POPUP, reinterpret_cast<UINT_PTR>(group), line.substr(1, line.size() - 2).c_str());
            continue;
        }
        const size_t colon = line.find(L'：');   // 動作：英語のプロンプト
        if (colon == std::wstring::npos) continue;
        prompts.push_back(line.substr(colon + 1));
        AppendMenuW(group ? group : menu, MF_STRING, kFirstSample + prompts.size() - 1, line.c_str());
    }
    if (prompts.empty()) {
        AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, (L"サンプルの一覧が読めません: " + samples_).c_str());
    }
    RECT r;
    GetWindowRect(GetDlgItem(panel_, kSamples), &r);
    // 下の段の一番下なので、一覧はボタンの上に開く
    const UINT chosen = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_LEFTALIGN | TPM_BOTTOMALIGN | TPM_NONOTIFY, r.left, r.top, 0, panel_, nullptr);
    DestroyMenu(menu);   // 子の一覧も一緒に消える
    if (chosen >= kFirstSample && chosen - kFirstSample < prompts.size()) {
        SetDlgItemTextW(panel_, kPrompt, prompts[chosen - kFirstSample].c_str());
    }
}

bool NakawariPanel::filter(MSG* message) {
    if (!panel_) return false;
    const HWND prompt = GetDlgItem(panel_, kPrompt);
    const UINT m = message->message;
    if (m == WM_LBUTTONDOWN || m == WM_RBUTTONDOWN || m == WM_MBUTTONDOWN || m == WM_NCLBUTTONDOWN) {
        // プロンプト欄の外を押したら、フォーカスを MMD に戻す（押した先が入力欄などなら、その部品が自分でフォーカスを取る）
        if (message->hwnd != prompt && GetFocus() == prompt) SetFocus(mmd_);
        return false;
    }
    if (message->hwnd != prompt) return false;
    if (m == WM_KEYDOWN && message->wParam == VK_RETURN) {   // Enter で生成
        message->message = WM_NULL;
        SendMessageW(panel_, WM_COMMAND, MAKEWPARAM(kGenerate, BN_CLICKED), reinterpret_cast<LPARAM>(GetDlgItem(panel_, kGenerate)));
        return true;
    }
    if (m == WM_KEYDOWN && message->wParam == VK_ESCAPE) {   // Esc でフォーカスを外す
        message->message = WM_NULL;
        SetFocus(mmd_);
        return true;
    }
    if (m == WM_CHAR && (message->wParam == L'\r' || message->wParam == 27)) {   // Enter・Esc の文字は捨てる（欄で鳴らさない）
        message->message = WM_NULL;
        return true;
    }
    if ((m >= WM_KEYFIRST && m <= WM_KEYLAST) || (m >= WM_IME_STARTCOMPOSITION && m <= WM_IME_KEYLAST)) {
        // MMD はキーの知らせをメッセージの取り出しの所でまとめて見てショートカットにする（キーの表は無い。11-05 調べ）。
        // なので欄への届けはここで済ませ、MMD には何も無い知らせとして返す
        TranslateMessage(message);
        DispatchMessageW(message);
        message->message = WM_NULL;
        return true;
    }
    return false;
}

// カメラ・照明・アクセサリのモード（カメラ用）か。3D 画面の下の「カメラ編／モデル編」ボタンは今と逆のモードの名前を出すので、
// 「モデル編」と出ていればカメラ用のモード（11-04 に測った。モデルの欄で「カメラ・照明・アクセサリ」を選んだ時も同じ）。
// Kimodo はモデルのモーションを作るので、カメラ用のモードではパネルを出さない（11-05 マスター）
bool NakawariPanel::camera_mode() const {
    wchar_t text[16]{};
    const HWND toggle = GetDlgItem(mmd_, kCameraButton);
    return toggle && GetWindowTextW(toggle, text, 16) && wcscmp(text, kModelModeText) == 0;
}

// 下の段の一番右のパネルの右に、隣のパネルと上端・下端をそろえて置く。
// 右に kWidth が取れない時も置いて、窓の右端で切れて見えるようにする（MMD のほかのパネルと同じ）。
void NakawariPanel::layout() {
    Strip strip{mmd_, panel_, -1};
    EnumChildWindows(mmd_, find_fold, reinterpret_cast<LPARAM>(&strip));
    if (strip.top >= 0) {
        strip.top -= kFoldGap;
        EnumChildWindows(mmd_, measure, reinterpret_cast<LPARAM>(&strip));
    }
    RECT client;
    GetClientRect(mmd_, &client);
    // 隣のパネルは部品の右端から 2px 先まで枠で、黒 1px・灰色の隙間 2px・次のパネルの黒 1px と並ぶ。
    // 下端も隣と同じく窓の下端の 2px 上まで（黒の枠が 986・窓の下端 989）
    const int x = strip.right + 6;
    const int y = strip.top;
    const int bottom = static_cast<int>(client.bottom) - 2;
    const bool fits = strip.top >= 0 && strip.right > 0 && client.right - x >= kMinVisible && bottom - y >= kMinHeight;
    if (!fits || camera_mode()) {
        if (IsWindowVisible(panel_)) {
            // 隠す欄にフォーカスが残ると、MMD のショートカットが止まったままになる（GetKeyState の差し替え）
            if (IsChild(panel_, GetFocus())) SetFocus(mmd_);
            ShowWindow(panel_, SW_HIDE);
        }
        placed_ = {};
        return;
    }
    const RECT want{x, y, x + kWidth, bottom};
    if (!EqualRect(&want, &placed_) || !IsWindowVisible(panel_)) {
        SetWindowPos(panel_, HWND_TOP, want.left, want.top, want.right - want.left, want.bottom - want.top,
                     SWP_NOACTIVATE | SWP_SHOWWINDOW);
        placed_ = want;
        arrange(want.right - want.left, want.bottom - want.top);
    }
}

// 部品を三行に並べる: 1 行目にモード選択と「選んだキー」、2 行目にプロンプト、3 行目にボタン、下に状態の 1 行。
// 大きさは MMD のパネルに合わせる（ボタン・切り替えは高さ 20px 前後）
void NakawariPanel::arrange(int width, int height) {
    const int pad = 6;
    const int top = kCaptionHeight + 4;
    const int inner = width - pad * 2;
    const int button = (inner - 8) / 3;
    auto place = [this](int id, int x, int y, int w, int h) {
        // 古い絵を写さない（作った時の 10×10 の灰色が写って、モード選択がマウスを乗せるまで灰色のままだった。11-05 マスター）
        SetWindowPos(GetDlgItem(panel_, id), nullptr, x, y, std::max(1, w), std::max(1, h),
                     SWP_NOZORDER | SWP_NOACTIVATE | SWP_NOCOPYBITS);
    };
    place(kEngine, pad, top, 92, 120);   // 高さは開いた時の一覧の高さ
    place(kRange, pad + 98, top + 2, inner - 98, 16);
    place(kPrompt, pad, top + 26, inner, 18);
    place(kSamples, pad, top + 47, inner, 20);   // プロンプト欄のすぐ下
    place(kGenerate, pad, top + 72, button, 24);
    place(kUndo, pad + button + 4, top + 72, button, 24);
    place(kDetails, pad + (button + 4) * 2, top + 72, inner - (button + 4) * 2, 24);
    place(kStatus, pad, std::min(top + 102, height - 18), inner, 14);
    RedrawWindow(panel_, nullptr, nullptr, RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_ALLCHILDREN);   // 子の部品まで描き直す
}

COLORREF NakawariPanel::color_at(int y) const {
    RECT r;
    GetClientRect(panel_, &r);
    const int height = std::max(1, static_cast<int>(r.bottom));
    y = std::max(0, std::min(y, height));
    return RGB(kTop[0] + (kBottom[0] - kTop[0]) * y / height, kTop[1] + (kBottom[1] - kTop[1]) * y / height,
               kTop[2] + (kBottom[2] - kTop[2]) * y / height);
}

void NakawariPanel::paint() {
    PAINTSTRUCT ps;
    const HDC dc = BeginPaint(panel_, &ps);
    draw(dc);
    EndPaint(panel_, &ps);
}

// 背景（グラデーション・枠・見出し）を描く。WM_PAINT のほか、Windows 10 風のコンボボックスが自分の後ろの背景を
// 親に描かせる時（WM_PRINTCLIENT）にも使う
void NakawariPanel::draw(HDC dc) {
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
}

// 字の部品（範囲・状態の 1 行）は、背景のグラデーションの上に白い字で描く。
// 字は Python が WM_SETTEXT で書き換える（SS_OWNERDRAW は書き換えで描き直しが来る）
void NakawariPanel::draw_label(const DRAWITEMSTRUCT* item) {
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

LRESULT CALLBACK NakawariPanel::proc(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_NCCREATE) {
        SetWindowLongPtrW(hwnd, GWLP_USERDATA,
                          reinterpret_cast<LONG_PTR>(reinterpret_cast<CREATESTRUCTW*>(lparam)->lpCreateParams));
    }
    auto* self = reinterpret_cast<NakawariPanel*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    if (self && self->panel_ == hwnd) {
        switch (message) {
        case WM_PAINT:
            self->paint();
            return 0;
        case WM_ERASEBKGND:
            return 1;
        case WM_PRINTCLIENT:
            self->draw(reinterpret_cast<HDC>(wparam));
            return 0;
        case WM_TIMER:
            if (wparam == kLayoutTimer) self->layout();
            return 0;
        case kEnableMessage:
            if (const HWND item = GetDlgItem(hwnd, static_cast<int>(wparam))) EnableWindow(item, lparam != 0);
            return 0;
        case kLayoutMessage:
            self->layout();
            return 0;
        case WM_DRAWITEM:
            self->draw_label(reinterpret_cast<const DRAWITEMSTRUCT*>(lparam));
            return TRUE;
        case WM_COMMAND:
            if (HIWORD(wparam) == BN_CLICKED && LOWORD(wparam) == kSamples) self->show_samples();
            if (HIWORD(wparam) == BN_CLICKED && (LOWORD(wparam) == kGenerate || LOWORD(wparam) == kUndo
                                                 || LOWORD(wparam) == kDetails) && self->on_command_) {
                self->on_command_(LOWORD(wparam));
            }
            // ボタン・チェック・モード選択を使ったら、フォーカスを MMD に戻す（ボタンに残るとスペースキーで押され、MMD のショートカットも
            // ボタン宛てになる）
            if ((HIWORD(wparam) == BN_CLICKED && LOWORD(wparam) != kPrompt) || (LOWORD(wparam) == kEngine && HIWORD(wparam) == CBN_CLOSEUP)) {
                SetFocus(self->mmd_);
            }
            return 0;
        default:
            break;
        }
    }
    return DefWindowProcW(hwnd, message, wparam, lparam);
}
