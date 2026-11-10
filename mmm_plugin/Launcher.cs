// AIナカワリ の窓（Python の app.py）を起こす・知らせる所。ツールバーのボタンとパネルで共通。
// MMD のプラグイン（mmd_plugin/nakawari_plugin.cpp）と同じ形: 窓が動いていれば Hub（見えない窓）に知らせ、無ければ起動する。
// 設定は DLL の横の MMM-AINakawari.ini（python・home・開発の時だけ instance）。
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace AINakawariMMM
{
    static class Launcher
    {
        public const string PanelMessage = "AINakawari.Panel.v1";   // app.py の PANEL_MESSAGE（wparam = 相手の窓・lparam = ボタンの番号）

        static string Dir => Path.GetDirectoryName(typeof(Launcher).Assembly.Location);

        // raw: 場所でない値（そのまま返す）。場所の値は、相対なら DLL のフォルダから
        public static string Ini(string key, bool raw = false)
        {
            var sb = new StringBuilder(1024);
            GetPrivateProfileString("MMM-AINakawari", key, "", sb, sb.Capacity, Path.Combine(Dir, "MMM-AINakawari.ini"));
            var v = sb.ToString().Trim();
            if (v.Length == 0) return null;
            return raw ? v : (Path.IsPathRooted(v) ? v : Path.GetFullPath(Path.Combine(Dir, v)));
        }

        public static string Home => Ini("home");
        public static string Instance => Ini("instance", raw: true);

        // 窓を動かす Python。python.exe と書いてあれば、横の pythonw.exe（黒い窓を出さない）
        public static string Python
        {
            get
            {
                var python = Ini("python");
                if (python != null && Path.GetFileName(python).Equals("python.exe", StringComparison.OrdinalIgnoreCase))
                {
                    var w = Path.Combine(Path.GetDirectoryName(python), "pythonw.exe");
                    if (File.Exists(w)) python = w;
                }
                return python;
            }
        }

        // 設定の誤りの文（無ければ null）
        public static string Problem()
        {
            var python = Python;
            var home = Home;
            if (python == null || home == null || !File.Exists(python) || !Directory.Exists(home))
                return "MMM-AINakawari.ini に python と home を書いてください（MMM の Plugins の MMM-AINakawari.dll の横）。\n今の値: python=" + python + "\nhome=" + home;
            return null;
        }

        // how: "--open"（窓を出す）か "--attach"（隠したまま作る。パネル用）。hwnd は MMM の本体の窓
        public static string Launch(string how, IntPtr hwnd)
        {
            var problem = Problem();
            if (problem != null) return problem;
            var psi = new ProcessStartInfo(Python, "-m mmd_ainakawari.app " + how + " " + hwnd.ToInt64())
            {
                WorkingDirectory = Home, UseShellExecute = false,
            };
            if (Instance != null) psi.EnvironmentVariables["AINAKAWARI_INSTANCE"] = Instance;   // app.py の AINAKAWARI_INSTANCE
            try { Process.Start(psi); return null; }
            catch (Exception ex) { return "AIナカワリ を起動できませんでした: " + ex.Message + "\n" + Python + "\n作業フォルダ: " + Home; }
        }

        // 動いている窓の Hub（見えない窓）。無ければ IntPtr.Zero
        public static IntPtr Hub()
        {
            var cls = "AINakawari.Hub" + (Instance != null ? "." + Instance : "");
            return FindWindowEx(HWND_MESSAGE, IntPtr.Zero, cls, null);
        }

        // パネルのボタン（生成・元に戻す）を Hub に知らせる。Hub が無ければ false
        public static bool Notify(IntPtr hwnd, int button)
        {
            var hub = Hub();
            if (hub == IntPtr.Zero) return false;
            PostMessage(hub, RegisterWindowMessage(PanelMessage), hwnd, (IntPtr)button);
            return true;
        }

        static readonly IntPtr HWND_MESSAGE = new IntPtr(-3);
        [DllImport("kernel32", CharSet = CharSet.Unicode)]
        static extern int GetPrivateProfileString(string section, string key, string def, StringBuilder ret, int size, string path);
        [DllImport("user32", CharSet = CharSet.Unicode)]
        static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string cls, string title);
        [DllImport("user32", CharSet = CharSet.Unicode)]
        static extern uint RegisterWindowMessage(string name);
        [DllImport("user32")]
        static extern bool PostMessage(IntPtr hwnd, uint msg, IntPtr w, IntPtr l);
    }
}
