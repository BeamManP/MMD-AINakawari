// MMM のプラグインのタブに出す「AIナカワリ」のパネル。MMD の右下のパネル（mmd_plugin/nakawari_panel.cpp）と同じ部品・同じ番号。
// パネルは部品を並べるだけで、中身（プロンプト・範囲・状態・ボタンの押せる押せない）は Python の窓（app.py）が 0.5 秒ごとに読み書きする
// （mmd_ainakawari/panel.py。MMM では、本体の窓の中を奥まで探して、目印の字 AINakawari.Panel を持つ窓をパネルとみなす）。
// 番号で部品を探す GetDlgItem は直下の子しか見ないので、部品はパネルの直下に並べる。
using System;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace AINakawariMMM
{
    class AINakawariPanel : UserControl
    {
        // 部品の番号（panel.py・nakawari_panel.cpp と同じ）
        const int ENGINE = 101, RANGE = 102, PROMPT = 103, GENERATE = 104, UNDO = 105, DETAILS = 106, STATUS = 107, SAMPLES = 108;
        const int WM_APP = 0x8000, ENABLE_MESSAGE = WM_APP + 2, ALERT_MESSAGE = WM_APP + 3, WM_SETTEXT = 0x000C;
        public const string Marker = "AINakawari.Panel";   // panel.py の CLASS（MMM では窓の字で探す）

        readonly ComboBox engine = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList };
        readonly SyncLabel range = new SyncLabel { AutoSize = false };
        readonly TextBox prompt = new TextBox();
        readonly SyncButton samples = new SyncButton { Text = "サンプルから選ぶ ▼" };
        readonly SyncButton generate = new SyncButton { Text = "生　成" };
        readonly SyncButton undo = new SyncButton { Text = "元に戻す" };
        readonly SyncButton details = new SyncButton { Text = "詳　細" };
        readonly SyncLabel status = new SyncLabel { AutoSize = false, Text = "AIナカワリ を起動中…" };
        readonly Timer attachTimer = new Timer { Interval = 15000 };   // MMM の起動の 15 秒後に窓を起こす（起動直後に MMM を読むと落ちたことがある）
        bool alert;

        public AINakawariPanel()
        {
            Text = Marker;
            Size = new Size(240, 250);
            Font = new Font("Yu Gothic UI", 9f);
            engine.Items.AddRange(new object[] { "Kimodo", "MotionBricks" });   // 0 が窓の「Kimodo」、1 が「MotionBricks」のタブ
            engine.SelectedIndex = 0;
            int x = 6, w = 226, y = 6;
            var title = new Label { Text = "AIナカワリ", AutoSize = false, Font = new Font(Font, FontStyle.Bold) };
            Place(title, x, ref y, w, 18);
            Place(engine, x, ref y, w, 24);
            Place(range, x, ref y, w, 18);
            Place(prompt, x, ref y, w, 24);
            Place(samples, x, ref y, w, 26);
            generate.SetBounds(x, y, 110, 30); undo.SetBounds(x + 116, y, 110, 30); y += 34;
            Place(details, x, ref y, w, 26);
            Place(status, x, ref y, w, 44);
            Controls.AddRange(new Control[] { title, engine, range, prompt, samples, generate, undo, details, status });

            generate.Click += (s, e) => Press(GENERATE);
            undo.Click += (s, e) => Press(UNDO);
            details.Click += (s, e) => Report(Launcher.Launch("--open", Host));
            samples.Click += (s, e) => ShowSamples();
            attachTimer.Tick += (s, e) =>
            {
                attachTimer.Stop();
                if (Launcher.Hub() == IntPtr.Zero && Host != IntPtr.Zero) Report(Launcher.Launch("--attach", Host));
            };
            // 部品に番号を付ける（WinForms は付けないので、窓の側の GetDlgItem で探せるように）。
            // 部品の窓は、プラグインのタブが初めて開かれた時に作られる（それまでは窓が無く、窓の側からも見えない）
            HandleCreated += (s, e) =>
            {
                SetId(engine, ENGINE); SetId(range, RANGE); SetId(prompt, PROMPT); SetId(generate, GENERATE);
                SetId(undo, UNDO); SetId(details, DETAILS); SetId(status, STATUS); SetId(samples, SAMPLES);
            };
            // 窓を起こすのは、タブが開かれるのを待たない（MMM の本体の窓に入った時から数える）
            ParentChanged += (s, e) => { if (Parent != null && !attachTimer.Enabled && Launcher.Hub() == IntPtr.Zero) attachTimer.Start(); };
        }

        static void Place(Control c, int x, ref int y, int w, int h) { c.SetBounds(x, y, w, h); y += h + 4; }

        static void SetId(Control c, int id) => SetWindowLongPtr(c.Handle, -12, (IntPtr)id);   // GWLP_ID

        // パネルが入っている MMM の本体の窓（窓の持ち主・Hub への知らせに使う）
        IntPtr Host => FindForm()?.Handle ?? IntPtr.Zero;

        void Press(int button)
        {
            if (Launcher.Notify(Host, button)) return;
            // 窓が終わっていた。立ち上げ直して、もう一度押してもらう（MMD のパネルと同じ）
            Report(Launcher.Launch("--attach", Host));
            status.Text = "AIナカワリ を起動しています。少ししてからもう一度押してください";
        }

        void Report(string problem)
        {
            if (problem != null) MessageBox.Show(FindForm(), problem, "AIナカワリ", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }

        // サンプルの一覧（mmd_ainakawari/prompt_samples.txt。押すたびに読む。書き方は MMD のパネルと同じ）
        void ShowSamples()
        {
            var menu = new ContextMenuStrip();
            ToolStripMenuItem group = null;
            var path = Launcher.Home == null ? null : Path.Combine(Launcher.Home, "mmd_ainakawari", "prompt_samples.txt");
            try
            {
                foreach (var raw in File.ReadAllLines(path, Encoding.UTF8))
                {
                    var line = raw.TrimEnd();
                    if (line.Length == 0 || line.StartsWith("#")) continue;
                    if (line.StartsWith("[") && line.EndsWith("]")) { group = new ToolStripMenuItem(line.Substring(1, line.Length - 2)); menu.Items.Add(group); continue; }
                    int colon = line.IndexOf('：');
                    if (colon < 0) continue;
                    var text = line.Substring(colon + 1);
                    var item = new ToolStripMenuItem(line, null, (s, e) => prompt.Text = text);
                    if (group != null) group.DropDownItems.Add(item); else menu.Items.Add(item);
                }
            }
            catch (Exception ex) { menu.Items.Add(new ToolStripMenuItem("サンプルの一覧が読めません: " + path + "（" + ex.Message + "）") { Enabled = false }); }
            menu.Show(samples, new Point(0, samples.Height));
        }

        protected override void WndProc(ref Message m)
        {
            if (m.Msg == ENABLE_MESSAGE)   // 窓が頼む「部品を押せる・押せないにする」（wparam = 番号・lparam = 押せるか）
            {
                var item = Find((int)m.WParam);
                if (item != null) item.Enabled = m.LParam != IntPtr.Zero;
                m.Result = IntPtr.Zero;
                return;
            }
            if (m.Msg == ALERT_MESSAGE)    // 状態の 1 行を赤で描くか（セットアップ前の案内など）
            {
                alert = m.LParam != IntPtr.Zero;
                status.ForeColor = alert ? Color.Firebrick : SystemColors.ControlText;
                m.Result = IntPtr.Zero;
                return;
            }
            base.WndProc(ref m);
        }

        Control Find(int id)
        {
            foreach (Control c in Controls) if (GetWindowLongPtr(c.Handle, -12) == (IntPtr)id) return c;
            return null;
        }

        // 外から WM_SETTEXT で字を書かれた時に描き直すラベル・ボタン（WinForms は自分で描くので、そのままだと古い字のまま）
        class SyncLabel : Label
        {
            bool inSet;
            protected override void WndProc(ref Message m)
            {
                base.WndProc(ref m);
                if (m.Msg == WM_SETTEXT && !inSet)
                {
                    inSet = true;
                    try { Text = Marshal.PtrToStringUni(m.LParam) ?? ""; Invalidate(); } finally { inSet = false; }
                }
            }
        }

        class SyncButton : Button
        {
            bool inSet;
            protected override void WndProc(ref Message m)
            {
                base.WndProc(ref m);
                if (m.Msg == WM_SETTEXT && !inSet)
                {
                    inSet = true;
                    try { Text = Marshal.PtrToStringUni(m.LParam) ?? ""; Invalidate(); } finally { inSet = false; }
                }
            }
        }

        [DllImport("user32", EntryPoint = "SetWindowLongPtrW")]
        static extern IntPtr SetWindowLongPtr(IntPtr hwnd, int index, IntPtr value);
        [DllImport("user32", EntryPoint = "GetWindowLongPtrW")]
        static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);
    }
}
