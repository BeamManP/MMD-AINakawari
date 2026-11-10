// MMM のツールバーの「AIナカワリ」のボタン。押すと窓（AINakawariForm）を出す。窓は 1 つだけ（2 回目は前に出す）。
// Python の場所は、この DLL の横の MMM-AINakawari.ini に書く（MMD 版の MMD-AINakawari.ini と同じ形）:
//   [MMM-AINakawari]
//   python=E:\Projects\mmd-mcp\.venv\Scripts\python.exe   ← 出力を読むので pythonw.exe でなく python.exe
//   home=E:\Projects\MMDKimodo                            ← mmd_ainakawari のあるフォルダ
using System;
using System.Drawing;
using System.Windows.Forms;
using MikuMikuPlugin;

namespace AINakawariMMM
{
    public class AINakawariCommand : ICommandPlugin
    {
        public Guid GUID => new Guid("3C9A51E2-7B44-4E0F-9D6A-2F18C4B0A7D5");
        public IWin32Window ApplicationForm { get; set; }
        public Scene Scene { get; set; }
        public string Description => "AIナカワリ（MMM 版・試作）: 選んだキーの間を AI が埋めます";
        public Image Image => null;
        public Image SmallImage => null;
        public string Text => "AI" + Environment.NewLine + "ナカワリ";
        public string EnglishText => "AI" + Environment.NewLine + "Nakawari";

        static AINakawariForm form;

        public void Run(CommandArgs e)
        {
            e.Cancel = true;   // 窓を出すだけで、ここでは場面を変えない（変更の印を立てない）
            if (form == null || form.IsDisposed)
            {
                form = new AINakawariForm();
                form.Show(ApplicationForm);
            }
            else
            {
                if (form.WindowState == FormWindowState.Minimized) form.WindowState = FormWindowState.Normal;
                form.Activate();
            }
        }

        public void Dispose()
        {
            try { form?.Close(); } catch { }
        }
    }
}
