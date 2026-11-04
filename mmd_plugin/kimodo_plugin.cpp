// MMDKimodo の MMDPlugin 用プラグイン。MMD のメニューバー（ヘルプの右）に「MMDKimodo」を足し、
// 「Kimodo の窓を開く」で Python の窓（mmdkimodo.app）を開く。
// 窓がもう動いていれば「この MMD の窓を開いて」と知らせ、動いていなければ Python を起動する。
// 下の段の右の空き地には「Kimodo操作」パネル（kimodo_panel.cpp）を置く。パネルの中身は Python の窓が読み書きするので、
// MMD の起動時に Python の窓を隠したまま立ち上げておく（--attach）。
// Python の場所は、この DLL の横の MMDKimodo.ini に書く。
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <share.h>
#include <cstdarg>
#include <cstdio>
#include <cwchar>
#include <string>

#include "kimodo_panel.h"
#include "mmd_plugin.h"

#ifndef _WIN64
#error x64 でビルドしてください。
#endif

extern "C" IMAGE_DOS_HEADER __ImageBase;

namespace {
constexpr wchar_t kTitle[] = L"MMDKimodo";
constexpr wchar_t kOpenLabel[] = L"Kimodo の窓を開く";
constexpr wchar_t kHubClass[] = L"MMDKimodo.Hub";       // 動いている Python の窓の目印（app.py と同じ）
constexpr wchar_t kOpenMessage[] = L"MMDKimodo.Open.v1";
constexpr wchar_t kAttachMessage[] = L"MMDKimodo.Attach.v1";   // この MMD の窓を隠したまま作って（パネル用）
constexpr wchar_t kPanelMessage[] = L"MMDKimodo.Panel.v1";     // パネルのボタンが押された（lparam はボタンの番号）
constexpr wchar_t kPanelClass[] = L"MMDKimodo.Panel";          // kimodo_panel.cpp のパネル
constexpr int kDetailsButton = 106;                            // kimodo_panel.cpp の「詳しく…」
constexpr int kStatusLabel = 107;                              // kimodo_panel.cpp の状態の 1 行

std::wstring module_dir() {
    wchar_t path[MAX_PATH]{};
    GetModuleFileNameW(reinterpret_cast<HMODULE>(&__ImageBase), path, MAX_PATH);
    std::wstring dir = path;
    return dir.substr(0, dir.find_last_of(L"\\/"));
}

void show_error(HWND owner, const std::wstring& text) {
    MessageBoxW(owner, text.c_str(), kTitle, MB_OK | MB_ICONERROR);
}

// MMDKimodo.ini に debug=1 がある時だけ、DLL の横の MMDKimodo.log に書く。
FILE* g_log = nullptr;

void log_line(const char* format, ...) {
    if (!g_log) return;
    SYSTEMTIME t;
    GetLocalTime(&t);
    std::fprintf(g_log, "%02d:%02d:%02d.%03d [%lu] ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds, GetCurrentThreadId());
    va_list args;
    va_start(args, format);
    std::vfprintf(g_log, format, args);
    va_end(args);
    std::fputc('\n', g_log);
    std::fflush(g_log);
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

class KimodoPlugin;
KimodoPlugin* g_plugin = nullptr;
HHOOK g_hook = nullptr;
LRESULT CALLBACK get_message_hook(int code, WPARAM wparam, LPARAM lparam);

class KimodoPlugin : public MMDPluginDLL3 {
public:
    const char* getPluginTitle() const override { return "MMDKimodo"; }

    void start() override {
        hwnd_ = getHWND();
        const std::wstring dir = module_dir();
        if (GetPrivateProfileIntW(L"MMDKimodo", L"debug", 0, (dir + L"\\MMDKimodo.ini").c_str()) == 1) {
            g_log = _wfsopen((dir + L"\\MMDKimodo.log").c_str(), L"a", _SH_DENYNO);  // 動いている間も外から読めるように
        }
        log_line("start hwnd=%p mmd-ui-thread=%lu", static_cast<void*>(hwnd_), GetWindowThreadProcessId(hwnd_, nullptr));
        const HMENU bar = GetMenu(hwnd_);
        const int help = bar ? help_position(bar) : -1;
        if (help < 0) {
            show_error(hwnd_, L"メニューバーに「ヘルプ」が見つからないので、MMDKimodo のメニューを出せませんでした。");
            return;
        }
        open_id_ = createWM_APP_ID();  // プラグイン同士でぶつからない番号を MMDPlugin からもらう
        if (open_id_ < 0) {
            show_error(hwnd_, L"MMDPlugin からメニューの番号をもらえませんでした。");
            return;
        }
        const HMENU popup = CreatePopupMenu();
        AppendMenuW(popup, MF_STRING, static_cast<UINT_PTR>(open_id_), kOpenLabel);
        MENUITEMINFOW info{};
        info.cbSize = sizeof(info);
        info.fMask = MIIM_STRING | MIIM_SUBMENU;
        info.hSubMenu = popup;
        info.dwTypeData = const_cast<wchar_t*>(kTitle);
        InsertMenuItemW(bar, help + 1, TRUE, &info);
        DrawMenuBar(hwnd_);
        // メニューの WM_COMMAND は Post で届く。MMDPlugin 0.41 は Send の受け口（WH_CALLWNDPROC）しか回してくれず、
        // GetMsgProc・MsgProc・WndProc(hwnd, …) には何も来なかった（2026-11-03 記録で確認）。なので自分で取り出しのフックを掛ける。
        g_plugin = this;
        g_hook = SetWindowsHookExW(WH_GETMESSAGE, get_message_hook, reinterpret_cast<HINSTANCE>(&__ImageBase),
                                   GetWindowThreadProcessId(hwnd_, nullptr));
        if (!g_hook) show_error(hwnd_, L"メニューの受け口を作れませんでした（エラー " + std::to_wstring(GetLastError()) + L"）。");
        log_line("menu added id=0x%x at %d hook=%p", open_id_, help + 1, static_cast<void*>(g_hook));
        if (panel_.create(hwnd_, [this](int button) { on_panel(button); })) {
            attach();
        } else {
            log_line("panel failed %lu", GetLastError());
        }
    }

    // MMD の窓の大きさが変わったら、パネルの位置を直す（Send で来るので MMDPlugin の受け口に届く）。
    void WndProc(CWPSTRUCT* param) override {
        if (param && param->hwnd == hwnd_ && param->message == WM_SIZE) panel_.request_layout();
    }

    void stop() override {
        log_line("stop");
        panel_.destroy();
        if (g_hook) UnhookWindowsHookEx(g_hook);
        g_hook = nullptr;
        g_plugin = nullptr;
        if (g_log) {
            std::fclose(g_log);
            g_log = nullptr;
        }
    }

    // 取り出された（PM_REMOVE）メッセージを見る。自分の項目の WM_COMMAND なら開き、MMD には渡さない。
    void on_message(MSG* message) {
        if (message->message != WM_COMMAND || message->hwnd != hwnd_ || HIWORD(message->wParam) != 0
            || open_id_ < 0 || LOWORD(message->wParam) != static_cast<WORD>(open_id_)) return;
        message->message = WM_NULL;
        open_window();
    }

private:
    static HWND hub() { return FindWindowExW(HWND_MESSAGE, nullptr, kHubClass, nullptr); }

    void open_window() {
        log_line("open_window");
        if (const HWND h = hub()) {
            PostMessageW(h, RegisterWindowMessageW(kOpenMessage), reinterpret_cast<WPARAM>(hwnd_), 0);
            return;
        }
        launch(L"--open", true);
    }

    // パネル用に、この MMD の窓を隠したまま作ってもらう。Python が動いていなければ起動する（失敗は記録だけ。メニューからも開ける）
    void attach() {
        log_line("attach");
        if (const HWND h = hub()) {
            PostMessageW(h, RegisterWindowMessageW(kAttachMessage), reinterpret_cast<WPARAM>(hwnd_), 0);
            return;
        }
        launch(L"--attach", false);
    }

    // パネルのボタン。中身（プロンプト・範囲）は Python がパネルから読むので、番号だけ知らせる
    void on_panel(int button) {
        log_line("panel button %d", button);
        if (button == kDetailsButton) {
            open_window();
            return;
        }
        if (const HWND h = hub()) {
            PostMessageW(h, RegisterWindowMessageW(kPanelMessage), reinterpret_cast<WPARAM>(hwnd_), button);
            return;
        }
        // Python が終わっていた。立ち上げ直して、もう一度押してもらう
        attach();
        if (const HWND panel = FindWindowExW(hwnd_, nullptr, kPanelClass, nullptr)) {
            SetDlgItemTextW(panel, kStatusLabel, L"MMDKimodo を起動しています。少ししてからもう一度押してください");
        }
    }

    // Python の窓を起動する。どの MMD かを --open（窓を出す）か --attach（隠したまま）で渡す。
    void launch(const wchar_t* how, bool show_errors) {
        const std::wstring ini = module_dir() + L"\\MMDKimodo.ini";
        wchar_t python[MAX_PATH]{}, home[MAX_PATH]{};
        GetPrivateProfileStringW(L"MMDKimodo", L"python", L"", python, MAX_PATH, ini.c_str());
        GetPrivateProfileStringW(L"MMDKimodo", L"home", L"", home, MAX_PATH, ini.c_str());
        if (!*python || !*home) {
            log_line("launch: python/home missing");
            if (show_errors) show_error(hwnd_, L"MMDKimodo.ini に python と home を書いてください:\n" + ini);
            return;
        }
        wchar_t args[96]{};
        swprintf_s(args, L" -m mmdkimodo.app %s %llu", how, static_cast<unsigned long long>(reinterpret_cast<UINT_PTR>(hwnd_)));
        std::wstring command = L"\"" + std::wstring(python) + L"\"" + args;
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        PROCESS_INFORMATION process{};
        if (!CreateProcessW(python, &command[0], nullptr, nullptr, FALSE, 0, nullptr, home, &startup, &process)) {
            log_line("launch failed %lu", GetLastError());
            if (show_errors) show_error(hwnd_, L"MMDKimodo を起動できませんでした（エラー " + std::to_wstring(GetLastError()) + L"）:\n"
                              + python + L"\n作業フォルダ: " + home);
            return;
        }
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
    }

    HWND hwnd_ = nullptr;
    int open_id_ = -1;
    KimodoPanel panel_;
};

LRESULT CALLBACK get_message_hook(int code, WPARAM wparam, LPARAM lparam) {
    if (code == HC_ACTION && wparam == PM_REMOVE && lparam && g_plugin) {
        g_plugin->on_message(reinterpret_cast<MSG*>(lparam));
    }
    return CallNextHookEx(nullptr, code, wparam, lparam);
}
}  // namespace

int version() { return 3; }

MMDPluginDLL3* create3(IDirect3DDevice9*) { return new KimodoPlugin(); }

void destroy3(MMDPluginDLL3* p) { delete p; }
