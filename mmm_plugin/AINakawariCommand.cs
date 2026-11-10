// MMM のツールバーの「AIナカワリ」のボタンと、プラグインのタブのパネル（AINakawariPanel）。
// ボタンは MMD 版と同じ AIナカワリ の窓（Python の app.py）を、この MMM 用に開く（Launcher.Launch("--open")）。
// パネルは MMD の右下のパネルと同じ部品で、窓が中身を同期する。MMM は起動時にパネルを作ってプラグインのタブに入れる（IHaveUserControl）。
using System;
using System.Drawing;
using System.Windows.Forms;
using MikuMikuPlugin;

namespace AINakawariMMM
{
    public class AINakawariCommand : ICommandPlugin, IHaveUserControl
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
            var problem = Launcher.Launch("--open", ApplicationForm?.Handle ?? IntPtr.Zero);
            if (problem != null) MessageBox.Show(ApplicationForm, problem, "AIナカワリ", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }

        public UserControl CreateControl() => new AINakawariPanel();

        public void Dispose() { }
    }
}
