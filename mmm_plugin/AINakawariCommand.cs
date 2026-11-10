// MMM のツールバーの「AIナカワリ」のボタン。押すと MMD 版と同じ AIナカワリ の窓（Python の app.py）を、この MMM 用に開く。
// MMD のプラグイン（mmd_plugin/nakawari_plugin.cpp）と同じく pythonw -m mmd_ainakawari.app --open <MMM の窓> で起動する。
// 窓がもう動いていれば、起動した側が動いている窓に「この窓を開いて」と知らせて終わる（app.py の main・_notify_running）。
// Python の場所は、この DLL の横の MMM-AINakawari.ini に書く（MMD 版の MMD-AINakawari.ini と同じ形）:
//   [MMM-AINakawari]
//   python=E:\Projects\mmd-mcp\.venv\Scripts\pythonw.exe   ← python.exe と書いてあれば、横の pythonw.exe を使う
//   home=E:\Projects\MMDKimodo                             ← mmd_ainakawari のあるフォルダ
// キーの読み書きは、別に入れる橋渡し（mmm-mcp の MmmBridge.dll）を通す。
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using MikuMikuPlugin;

namespace AINakawariMMM
{
    public class AINakawariCommand : ICommandPlugin
    {
        public Guid GUID => new Guid("3C9A51E2-7B44-4E0F-9D6A-2F18C4B0A7D5");
        public IWin32Window ApplicationForm { get; set; }
        public Scene Scene { get; set; }
        public string Description => "AIナカワリ（MMM 版）: 選んだキーの間を AI が埋めます";
        public Image Image => null;
        public Image SmallImage => null;
        public string Text => "AI" + Environment.NewLine + "ナカワリ";
        public string EnglishText => "AI" + Environment.NewLine + "Nakawari";

        public void Run(CommandArgs e)
        {
            e.Cancel = true;   // 窓を開くだけで、ここでは場面を変えない（変更の印を立てない）
            var python = Ini("python");
            var home = Ini("home");
            if (python != null && Path.GetFileName(python).Equals("python.exe", StringComparison.OrdinalIgnoreCase))
            {
                var w = Path.Combine(Path.GetDirectoryName(python), "pythonw.exe");   // 黒い窓を出さない
                if (File.Exists(w)) python = w;
            }
            if (python == null || home == null || !File.Exists(python) || !Directory.Exists(home))
            {
                MessageBox.Show(ApplicationForm, "MMM-AINakawari.ini に python と home を書いてください（MMM の Plugins の MMM-AINakawari.dll の横）。\n"
                                + "今の値: python=" + python + "\nhome=" + home, "AIナカワリ", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
            // 窓の持ち主にする MMM の窓。ApplicationForm は MMM の本体のフォーム
            var hwnd = ApplicationForm?.Handle ?? IntPtr.Zero;
            try
            {
                var psi = new ProcessStartInfo(python, "-m mmd_ainakawari.app --open " + hwnd.ToInt64())
                {
                    WorkingDirectory = home, UseShellExecute = false,
                };
                // ini の instance（開発版を配布版と並べて動かす時。app.py の AINAKAWARI_INSTANCE）
                var instance = Ini("instance", raw: true);
                if (instance != null) psi.EnvironmentVariables["AINAKAWARI_INSTANCE"] = instance;
                Process.Start(psi);
            }
            catch (Exception ex)
            {
                MessageBox.Show(ApplicationForm, "AIナカワリ を起動できませんでした: " + ex.Message + "\n" + python + "\n作業フォルダ: " + home,
                                "AIナカワリ", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        // raw: 場所でない値（そのまま返す）。場所の値は、相対なら DLL のフォルダから
        static string Ini(string key, bool raw = false)
        {
            var dir = Path.GetDirectoryName(typeof(AINakawariCommand).Assembly.Location);
            var sb = new StringBuilder(1024);
            GetPrivateProfileString("MMM-AINakawari", key, "", sb, sb.Capacity, Path.Combine(dir, "MMM-AINakawari.ini"));
            var v = sb.ToString().Trim();
            if (v.Length == 0) return null;
            return raw ? v : (Path.IsPathRooted(v) ? v : Path.GetFullPath(Path.Combine(dir, v)));
        }

        [DllImport("kernel32", CharSet = CharSet.Unicode)]
        static extern int GetPrivateProfileString(string section, string key, string def, StringBuilder ret, int size, string path);

        public void Dispose() { }
    }
}
