// MMD のメニューバーに「MMDKimodo」を足し、押された項目を外の Python に知らせる。
// Python が MMD の UI スレッドに限ったフックで読み込ませる。MMD の内部メモリには触らない。
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cwchar>

#ifndef _WIN64
#error x64 でビルドしてください。
#endif

namespace {
constexpr std::uint32_t kMagic = 0x4e4d4b4d;  // "MKMN"
constexpr std::uint32_t kVersion = 1;
constexpr int kMaxItems = 16;
constexpr UINT kFirstId = 0xB700;  // MMAccel は 50000 番台。重なりは付ける時に確かめる
constexpr wchar_t kTitle[] = L"MMDKimodo";

struct Request {
    std::uint32_t magic;
    std::uint32_t version;
    std::uint64_t hwnd;     // MMD のメインの窓
    std::uint64_t notify;   // 押された時に知らせる Python 側の窓
    std::int32_t command;   // 1 付ける, 2 外す
    std::int32_t item_count;
    wchar_t items[kMaxItems][32];  // "-" は区切り線
    volatile LONG status;   // 0 待ち, 1 実行中, 2 完了, 負はエラー
    std::int32_t position;  // 付けた位置
};
static_assert(sizeof(Request) == 1064, "Python とのやり取りの大きさが合いません");
static_assert(offsetof(Request, status) == 1056, "Python とのやり取りの並びが合いません");

HMENU g_popup = nullptr;
HWND g_main = nullptr;
HWND g_notify = nullptr;
int g_count = 0;

UINT notify_message() {
    static const UINT message = RegisterWindowMessageW(L"MMDKimodo.MenuCommand.v1");
    return message;
}

bool is_title(HMENU bar, int position) {
    wchar_t text[64]{};
    GetMenuStringW(bar, position, text, 64, MF_BYPOSITION);
    return std::wcscmp(text, kTitle) == 0;
}

// MMD 自身の「ヘルプ」の位置。英語表示では「Help」。
int help_position(HMENU bar) {
    const int n = GetMenuItemCount(bar);
    for (int i = 0; i < n; ++i) {
        wchar_t text[64]{};
        GetMenuStringW(bar, i, text, 64, MF_BYPOSITION);
        if (std::wcsncmp(text, L"ヘルプ", 3) == 0 || std::wcsncmp(text, L"Help", 4) == 0) return i;
    }
    return -1;
}

// 足す番号が MMD や他の拡張のメニューと重なっていないか、子メニューまでたどって確かめる。
bool ids_free(HMENU menu, int count) {
    const int n = GetMenuItemCount(menu);
    for (int i = 0; i < n; ++i) {
        if (const HMENU sub = GetSubMenu(menu, i)) {
            if (!ids_free(sub, count)) return false;
            continue;
        }
        const UINT id = GetMenuItemID(menu, i);
        if (id != static_cast<UINT>(-1) && id >= kFirstId && id < kFirstId + static_cast<UINT>(count)) return false;
    }
    return true;
}

// 前に落ちた時の残りも含め、「MMDKimodo」の見出しを全部外す。
void remove_menus(HMENU bar) {
    for (int i = GetMenuItemCount(bar) - 1; i >= 0; --i) {
        if (is_title(bar, i)) DeleteMenu(bar, i, MF_BYPOSITION);  // 子メニューも一緒に壊れる
    }
    g_popup = nullptr;
    g_count = 0;
}

LONG attach(Request* request, HWND hwnd, HMENU bar) {
    if (request->item_count < 1 || request->item_count > kMaxItems) return -3;
    remove_menus(bar);
    const int help = help_position(bar);
    if (help < 0) return -6;
    if (!ids_free(bar, request->item_count)) return -4;
    const HMENU popup = CreatePopupMenu();
    if (!popup) return -5;
    for (int i = 0; i < request->item_count; ++i) {
        request->items[i][31] = L'\0';
        if (std::wcscmp(request->items[i], L"-") == 0) AppendMenuW(popup, MF_SEPARATOR, 0, nullptr);
        else AppendMenuW(popup, MF_STRING, kFirstId + i, request->items[i]);
    }
    MENUITEMINFOW info{};
    info.cbSize = sizeof(info);
    info.fMask = MIIM_STRING | MIIM_SUBMENU;
    info.hSubMenu = popup;
    info.dwTypeData = const_cast<wchar_t*>(kTitle);
    const int position = help + 1;  // ヘルプの右。MMAccel・MMEffect はその後ろへずれる
    if (!InsertMenuItemW(bar, position, TRUE, &info)) {
        DestroyMenu(popup);
        return -5;
    }
    DrawMenuBar(hwnd);
    g_popup = popup;
    g_main = hwnd;
    g_notify = reinterpret_cast<HWND>(request->notify);
    g_count = request->item_count;
    request->position = position;
    return 2;
}

LONG run(Request* request, HWND hwnd) {
    if (request->magic != kMagic || request->version != kVersion
        || request->hwnd != reinterpret_cast<std::uintptr_t>(hwnd)) return -1;
    DWORD process = 0;
    if (GetWindowThreadProcessId(hwnd, &process) != GetCurrentThreadId()
        || process != GetCurrentProcessId()) return -2;
    const HMENU bar = GetMenu(hwnd);
    if (!bar) return -2;
    if (request->command == 1) return attach(request, hwnd, bar);
    if (request->command == 2) {
        remove_menus(bar);
        DrawMenuBar(hwnd);
        g_notify = nullptr;
        return 2;
    }
    return -3;
}

void handle_request(HWND hwnd, WPARAM nonce) {
    wchar_t name[128]{};
    swprintf_s(name, L"Local\\MMDKimodo.Menu.v1.%lu.%016llx", GetCurrentProcessId(),
               static_cast<unsigned long long>(nonce));
    const HANDLE mapping = OpenFileMappingW(FILE_MAP_READ | FILE_MAP_WRITE, FALSE, name);
    if (!mapping) return;
    if (const auto request = static_cast<Request*>(MapViewOfFile(mapping, FILE_MAP_READ | FILE_MAP_WRITE, 0, 0, sizeof(Request)))) {
        if (request->magic == kMagic && InterlockedCompareExchange(&request->status, 1, 0) == 0) {
            InterlockedExchange(&request->status, run(request, hwnd));
        }
        UnmapViewOfFile(request);
    }
    CloseHandle(mapping);
}

// 自分の項目なら Python に知らせる。how は 1 = Post で届いた, 2 = Send で届いた。
bool forward_command(HWND hwnd, WPARAM wparam, int how) {
    const UINT id = LOWORD(wparam);
    if (!g_popup || hwnd != g_main || HIWORD(wparam) != 0
        || id < kFirstId || id >= kFirstId + static_cast<UINT>(g_count)) return false;
    if (g_notify && IsWindow(g_notify)) PostMessageW(g_notify, notify_message(), id - kFirstId, how);
    return true;
}
}  // namespace

// 付ける・外すの依頼（Send で来る）と、Send で来たメニューの通知を受ける。
extern "C" __declspec(dllexport) LRESULT CALLBACK MenuCallWndProc(int code, WPARAM wparam, LPARAM lparam) {
    if (code == HC_ACTION && lparam) {
        const auto message = reinterpret_cast<const CWPSTRUCT*>(lparam);
        static const UINT request_message = RegisterWindowMessageW(L"MMDKimodo.MenuControl.v1");
        if (request_message && message->message == request_message && message->wParam && message->lParam == 0) {
            handle_request(message->hwnd, message->wParam);
        } else if (message->message == WM_COMMAND) {
            forward_command(message->hwnd, message->wParam, 2);
        }
    }
    return CallNextHookEx(nullptr, code, wparam, lparam);
}

// Post で来たメニューの通知を受け、MMD には渡さない。
extern "C" __declspec(dllexport) LRESULT CALLBACK MenuGetMsgProc(int code, WPARAM wparam, LPARAM lparam) {
    if (code == HC_ACTION && wparam == PM_REMOVE && lparam) {
        const auto message = reinterpret_cast<MSG*>(lparam);
        if (message->message == WM_COMMAND && forward_command(message->hwnd, message->wParam, 1)) {
            message->message = WM_NULL;
        }
    }
    return CallNextHookEx(nullptr, code, wparam, lparam);
}
