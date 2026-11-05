// AIナカワリ の MMDPlugin 用プラグイン。MMD のメニューバー（ヘルプの右）に「AIナカワリ」を足し、
// 「AIナカワリの窓を開く」で Python の窓（mmd_ainakawari.app）を開く。
// 窓がもう動いていれば「この MMD の窓を開いて」と知らせ、動いていなければ Python を起動する。
// 下の段の右の空き地には「Kimodo操作」パネル（nakawari_panel.cpp）を置く。パネルの中身は Python の窓が読み書きするので、
// MMD の起動時に Python の窓を隠したまま立ち上げておく（--attach）。
// Python の場所は、この DLL の横の MMD-AINakawari.ini に書く（相対の場所なら DLL のフォルダから。配布の zip はこの形）。
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <share.h>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <string>

#include "nakawari_panel.h"
#include "mmd_plugin.h"

#ifndef _WIN64
#error x64 でビルドしてください。
#endif

extern "C" IMAGE_DOS_HEADER __ImageBase;

namespace {
constexpr wchar_t kTitle[] = L"AIナカワリ";
constexpr wchar_t kOpenLabel[] = L"AIナカワリの窓を開く";
constexpr wchar_t kHubClass[] = L"AINakawari.Hub";       // 動いている Python の窓の目印（app.py と同じ）
constexpr wchar_t kOpenMessage[] = L"AINakawari.Open.v1";
constexpr wchar_t kAttachMessage[] = L"AINakawari.Attach.v1";   // この MMD の窓を隠したまま作って（パネル用）
constexpr wchar_t kPanelMessage[] = L"AINakawari.Panel.v1";     // パネルのボタンが押された（lparam はボタンの番号）
constexpr wchar_t kPanelClass[] = L"AINakawari.Panel";          // nakawari_panel.cpp のパネル
constexpr int kDetailsButton = 106;                            // nakawari_panel.cpp の「詳しく…」
constexpr int kStatusLabel = 107;                              // nakawari_panel.cpp の状態の 1 行

std::wstring module_dir() {
    wchar_t path[MAX_PATH]{};
    GetModuleFileNameW(reinterpret_cast<HMODULE>(&__ImageBase), path, MAX_PATH);
    std::wstring dir = path;
    return dir.substr(0, dir.find_last_of(L"\\/"));
}

// MMD-AINakawari.ini の場所の値。相対の場所（配布の zip の python\pythonw.exe・app）は、この DLL のフォルダから読む。
// 書いていなければ空を返す
std::wstring ini_path(const wchar_t* key) {
    wchar_t value[MAX_PATH]{};
    GetPrivateProfileStringW(L"MMD-AINakawari", key, L"", value, MAX_PATH, (module_dir() + L"\\MMD-AINakawari.ini").c_str());
    if (!*value) return std::wstring();
    const bool absolute = (value[0] == L'\\' || value[0] == L'/') || (value[0] && value[1] == L':');
    const std::wstring joined = absolute ? std::wstring(value) : module_dir() + L"\\" + value;
    wchar_t full[MAX_PATH]{};
    const DWORD n = GetFullPathNameW(joined.c_str(), MAX_PATH, full, nullptr);
    return (n > 0 && n < MAX_PATH) ? std::wstring(full) : joined;
}

void show_error(HWND owner, const std::wstring& text) {
    MessageBoxW(owner, text.c_str(), kTitle, MB_OK | MB_ICONERROR);
}

// MMD-AINakawari.ini に debug=1 がある時だけ、DLL の横の MMD-AINakawari.log に書く。
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

// MMD はショートカットのキーを GetKeyState で「今押されているか」見ている（11-05、プロンプト欄で i を打つと MMD の
// 「i」が効いた。キーの知らせを WM_NULL にしても、押されている記録は取り出した時に更新されるので止まらない）。
// なので MMD の実行ファイルが呼ぶ GetKeyState を差し替え、パネルのプロンプト欄にフォーカスがある間は「押されていない」と答える。
// 欄そのもの（Windows のエディット）は user32 の中で GetKeyState を呼ぶので、差し替えの影響を受けない
using GetKeyStateFn = SHORT(WINAPI*)(int);
GetKeyStateFn g_get_key_state = nullptr;   // 本物
GetKeyStateFn* g_key_state_slot = nullptr; // MMD の呼び先の表の、GetKeyState の欄
HWND g_prompt = nullptr;

SHORT WINAPI quiet_get_key_state(int key) {
    if (g_prompt && GetFocus() == g_prompt) return 0;
    return g_get_key_state(key);
}

// module が import している dll!name の呼び先の表の欄。無ければ nullptr。
void** import_slot(HMODULE module, const char* dll, const char* name) {
    auto* base = reinterpret_cast<BYTE*>(module);
    const auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    const auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    const IMAGE_DATA_DIRECTORY& dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!dir.VirtualAddress) return nullptr;
    for (auto* desc = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(base + dir.VirtualAddress); desc->Name; ++desc) {
        if (_stricmp(reinterpret_cast<char*>(base + desc->Name), dll) != 0 || !desc->OriginalFirstThunk) continue;
        auto* names = reinterpret_cast<IMAGE_THUNK_DATA*>(base + desc->OriginalFirstThunk);
        auto* slots = reinterpret_cast<IMAGE_THUNK_DATA*>(base + desc->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++slots) {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) continue;
            const auto* by_name = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(base + names->u1.AddressOfData);
            if (std::strcmp(reinterpret_cast<const char*>(by_name->Name), name) == 0) {
                return reinterpret_cast<void**>(&slots->u1.Function);
            }
        }
    }
    return nullptr;
}

bool write_slot(void** slot, void* value) {
    DWORD old = 0;
    if (!VirtualProtect(slot, sizeof(void*), PAGE_READWRITE, &old)) return false;
    *slot = value;
    VirtualProtect(slot, sizeof(void*), old, &old);
    return true;
}

void quiet_keys_in(HWND prompt) {
    g_prompt = prompt;
    void** slot = import_slot(GetModuleHandleW(nullptr), "USER32.dll", "GetKeyState");
    if (!slot || *slot == reinterpret_cast<void*>(quiet_get_key_state)) {
        log_line("GetKeyState: import not found");
        return;
    }
    g_get_key_state = reinterpret_cast<GetKeyStateFn>(*slot);
    if (write_slot(slot, reinterpret_cast<void*>(quiet_get_key_state))) {
        g_key_state_slot = reinterpret_cast<GetKeyStateFn*>(slot);
        // この DLL を MMD が終わるまで外さない。戻すのに失敗した時（や戻す前に外された時）に、MMD の呼び先が
        // 外した後の場所を指して落ちないように（11-05 Codex のレビュー）
        HMODULE self = nullptr;
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_PIN,
                           reinterpret_cast<LPCWSTR>(&quiet_get_key_state), &self);
        log_line("GetKeyState: replaced");
    } else {
        log_line("GetKeyState: VirtualProtect failed %lu", GetLastError());
    }
}

void restore_keys() {
    g_prompt = nullptr;   // 戻せなくても、これで差し替えた方は本物と同じ答えを返す
    if (g_key_state_slot && write_slot(reinterpret_cast<void**>(g_key_state_slot), reinterpret_cast<void*>(g_get_key_state))) {
        g_key_state_slot = nullptr;
    } else if (g_key_state_slot) {
        log_line("GetKeyState: restore failed %lu", GetLastError());
    }
}

class NakawariPlugin;
NakawariPlugin* g_plugin = nullptr;
HHOOK g_hook = nullptr;
LRESULT CALLBACK get_message_hook(int code, WPARAM wparam, LPARAM lparam);

class NakawariPlugin : public MMDPluginDLL3 {
public:
    const char* getPluginTitle() const override { return "MMD-AINakawari"; }

    void start() override {
        hwnd_ = getHWND();
        const std::wstring dir = module_dir();
        if (GetPrivateProfileIntW(L"MMD-AINakawari", L"debug", 0, (dir + L"\\MMD-AINakawari.ini").c_str()) == 1) {
            g_log = _wfsopen((dir + L"\\MMD-AINakawari.log").c_str(), L"a", _SH_DENYNO);  // 動いている間も外から読めるように
        }
        log_line("start hwnd=%p mmd-ui-thread=%lu", static_cast<void*>(hwnd_), GetWindowThreadProcessId(hwnd_, nullptr));
        const HMENU bar = GetMenu(hwnd_);
        const int help = bar ? help_position(bar) : -1;
        if (help < 0) {
            show_error(hwnd_, L"メニューバーに「ヘルプ」が見つからないので、AIナカワリ のメニューを出せませんでした。");
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
        if (panel_.create(hwnd_, [this](int button) { on_panel(button); }, samples_path())) {
            quiet_keys_in(panel_.prompt());
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
        restore_keys();
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
    // パネルのプロンプト欄宛てのキーも、パネルで処理して MMD には渡さない（NakawariPanel::filter）。
    void on_message(MSG* message) {
        if (panel_.filter(message)) return;
        if (message->message != WM_COMMAND || message->hwnd != hwnd_ || HIWORD(message->wParam) != 0
            || open_id_ < 0 || LOWORD(message->wParam) != static_cast<WORD>(open_id_)) return;
        message->message = WM_NULL;
        open_window();
    }

private:
    static HWND hub() { return FindWindowExW(HWND_MESSAGE, nullptr, kHubClass, nullptr); }

    // パネルの「サンプル」の一覧。MMD-AINakawari.ini の home（AIナカワリ のフォルダ）の中にある
    static std::wstring samples_path() {
        const std::wstring home = ini_path(L"home");
        return home.empty() ? std::wstring() : home + L"\\mmd_ainakawari\\prompt_samples.txt";
    }

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
            SetDlgItemTextW(panel, kStatusLabel, L"AIナカワリ を起動しています。少ししてからもう一度押してください");
        }
    }

    // Python の窓を起動する。どの MMD かを --open（窓を出す）か --attach（隠したまま）で渡す。
    void launch(const wchar_t* how, bool show_errors) {
        const std::wstring ini = module_dir() + L"\\MMD-AINakawari.ini";
        const std::wstring python = ini_path(L"python"), home = ini_path(L"home");
        if (python.empty() || home.empty()) {
            log_line("launch: python/home missing");
            if (show_errors) show_error(hwnd_, L"MMD-AINakawari.ini に python と home を書いてください:\n" + ini);
            return;
        }
        wchar_t args[96]{};
        swprintf_s(args, L" -m mmd_ainakawari.app %s %llu", how, static_cast<unsigned long long>(reinterpret_cast<UINT_PTR>(hwnd_)));
        std::wstring command = L"\"" + python + L"\"" + args;
        STARTUPINFOW startup{};
        startup.cb = sizeof(startup);
        PROCESS_INFORMATION process{};
        if (!CreateProcessW(python.c_str(), &command[0], nullptr, nullptr, FALSE, 0, nullptr, home.c_str(), &startup, &process)) {
            log_line("launch failed %lu", GetLastError());
            if (show_errors) show_error(hwnd_, L"AIナカワリ を起動できませんでした（エラー " + std::to_wstring(GetLastError()) + L"）:\n"
                              + python + L"\n作業フォルダ: " + home);
            return;
        }
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
    }

    HWND hwnd_ = nullptr;
    int open_id_ = -1;
    NakawariPanel panel_;
};

LRESULT CALLBACK get_message_hook(int code, WPARAM wparam, LPARAM lparam) {
    if (code == HC_ACTION && wparam == PM_REMOVE && lparam && g_plugin) {
        g_plugin->on_message(reinterpret_cast<MSG*>(lparam));
    }
    return CallNextHookEx(nullptr, code, wparam, lparam);
}
}  // namespace

int version() { return 3; }

MMDPluginDLL3* create3(IDirect3DDevice9*) { return new NakawariPlugin(); }

void destroy3(MMDPluginDLL3* p) { delete p; }
