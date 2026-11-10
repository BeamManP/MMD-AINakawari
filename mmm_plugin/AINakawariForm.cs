// AIナカワリ（MMM 版）の窓。中割り（MotionBricks）か Kimodo（プロンプト）を選んで「生成」。
// 生成は python -m mmd_ainakawari.mmm_run を別のプロセスで動かし、その出力を 1 行ずつ下の欄に出す（最後の行が「OK: …」か「NG: …」）。
// キーの読み書きは mmm_run が MMM の中の橋渡し（MmmBridge.dll）に頼むので、この窓は MMM の場面に触らない。
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace AINakawariMMM
{
    class AINakawariForm : Form
    {
        readonly RadioButton mb = new RadioButton { Text = "中割り（MotionBricks・プロンプトなし）", AutoSize = true, Checked = true };
        readonly RadioButton km = new RadioButton { Text = "Kimodo（英語のプロンプトで作る）", AutoSize = true };
        readonly TextBox prompt = new TextBox { Text = "A person moves naturally between poses.", Width = 460, Enabled = false };
        readonly Button generate = new Button { Text = "生成", Width = 110, Height = 32 };
        readonly Button undo = new Button { Text = "元に戻す", Width = 110, Height = 32 };
        readonly TextBox log = new TextBox { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, WordWrap = true, BackColor = SystemColors.Window };
        readonly Label status = new Label { AutoSize = false, Height = 22, TextAlign = ContentAlignment.MiddleLeft };
        Process proc;
        bool committing;   // 書き戻しが始まった（ここからは中断しない）
        bool answered;     // OK・NG の行が来た（来なかった時だけ、エラーの出力の最後を見せる）
        bool cancelled;

        public AINakawariForm()
        {
            Text = "AIナカワリ（MMM 版・試作）";
            Font = new Font("Yu Gothic UI", 9.5f);
            ClientSize = new Size(520, 420);
            MinimumSize = new Size(480, 360);
            FormBorderStyle = FormBorderStyle.Sizable;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;

            var how = new Label { Text = "MMM のタイムラインで、作り直す範囲の最初と最後のキーを選んでから押してください。", AutoSize = true, MaximumSize = new Size(490, 0) };
            var top = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, Dock = DockStyle.Top, AutoSize = true, Padding = new Padding(10, 10, 10, 0), WrapContents = false };
            top.Controls.Add(how);
            top.Controls.Add(mb);
            top.Controls.Add(km);
            top.Controls.Add(prompt);
            var buttons = new FlowLayoutPanel { FlowDirection = FlowDirection.LeftToRight, AutoSize = true, Margin = new Padding(0, 8, 0, 4) };
            buttons.Controls.Add(generate);
            buttons.Controls.Add(undo);
            top.Controls.Add(buttons);
            status.Dock = DockStyle.Bottom;
            status.Padding = new Padding(10, 0, 0, 0);
            var logPanel = new Panel { Dock = DockStyle.Fill, Padding = new Padding(10, 4, 10, 4) };
            log.Dock = DockStyle.Fill;
            logPanel.Controls.Add(log);
            Controls.Add(logPanel);
            Controls.Add(status);
            Controls.Add(top);

            km.CheckedChanged += (s, e) => prompt.Enabled = km.Checked;
            generate.Click += (s, e) => { if (proc == null) Start(false); else Cancel(); };
            undo.Click += (s, e) => { if (proc == null) Start(true); };
            FormClosing += (s, e) =>
            {
                if (proc != null && !proc.HasExited)
                {
                    e.Cancel = true;
                    status.Text = "生成中は閉じられません。終わるか、中断してから閉じてください";
                }
            };
            status.Text = "待機中";
        }

        static string Ini(string key)
        {
            var dir = Path.GetDirectoryName(typeof(AINakawariForm).Assembly.Location);
            var sb = new StringBuilder(1024);
            GetPrivateProfileString("MMM-AINakawari", key, "", sb, sb.Capacity, Path.Combine(dir, "MMM-AINakawari.ini"));
            var v = sb.ToString().Trim();
            return v.Length == 0 ? null : (Path.IsPathRooted(v) ? v : Path.GetFullPath(Path.Combine(dir, v)));
        }

        [DllImport("kernel32", CharSet = CharSet.Unicode)]
        static extern int GetPrivateProfileString(string section, string key, string def, StringBuilder ret, int size, string path);

        void Start(bool isUndo)
        {
            var python = Ini("python");
            var home = Ini("home");
            if (python == null || home == null || !File.Exists(python) || !Directory.Exists(home))
            {
                MessageBox.Show(this, "MMM-AINakawari.ini に python と home を書いてください（この DLL の横）。\n今の値: python=" + python + "\nhome=" + home,
                                "AIナカワリ", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return;
            }
            var args = "-X utf8 -m mmd_ainakawari.mmm_run";
            if (isUndo) args += " --undo";
            else if (km.Checked) args += " --engine kimodo --prompt \"" + prompt.Text.Replace("\"", "'") + "\"";
            else args += " --engine motionbricks";
            var psi = new ProcessStartInfo(python, args)
            {
                WorkingDirectory = home, UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            Append("―――――――――――――――");
            committing = answered = cancelled = false;
            try
            {
                proc = new Process { StartInfo = psi, EnableRaisingEvents = true };
                proc.OutputDataReceived += (s, e) => { if (e.Data != null) Ui(() => OnLine(e.Data)); };
                proc.ErrorDataReceived += (s, e) => { if (e.Data != null) Ui(() => LogError(e.Data)); };
                proc.Exited += (s, e) => Ui(Finished);
                proc.Start();
                proc.BeginOutputReadLine();
                proc.BeginErrorReadLine();
            }
            catch (Exception ex)
            {
                proc = null;
                Append("始められませんでした: " + ex.Message);
                return;
            }
            status.Text = isUndo ? "元に戻しています…" : "生成中…（書き戻しの前までは「中断」できます）";
            generate.Text = "中断";
            undo.Enabled = false;
            mb.Enabled = km.Enabled = prompt.Enabled = false;
        }

        void OnLine(string line)
        {
            if (line.StartsWith("OK: ") || line.StartsWith("NG: "))
            {
                answered = true;
                status.Text = line.Substring(4);
                Append(line.Substring(4));
                return;
            }
            if (line.Contains("に読み込み中"))   // runner の「MMD に読み込み中…」。ここから書き戻し（中断しない）
            {
                committing = true;
                generate.Enabled = false;
                status.Text = "MMM に書き戻しています…";
                line = line.Replace("MMD に読み込み中", "MMM に書き戻し中");
            }
            Append(line.Replace("MMD から", "MMM から").Replace("MMD で再生", "MMM で再生"));
        }

        // エラーの出力は、最後の数行（traceback の終わり）だけ出す。中身は NG の行に出る
        string lastErr;
        void LogError(string line) { lastErr = line; }

        void Cancel()
        {
            if (proc == null || committing) return;
            cancelled = true;
            try { proc.Kill(); } catch { }
            Append("中断しました（MMM のキーはそのままです）");
            status.Text = "中断しました（MMM のキーはそのままです）";
        }

        void Finished()
        {
            int code = -1;
            try { code = proc.ExitCode; } catch { }
            if (code != 0 && lastErr != null && !answered && !cancelled) Append("（記録の最後: " + lastErr + "）");
            proc = null;
            lastErr = null;
            generate.Text = "生成";
            generate.Enabled = true;
            undo.Enabled = true;
            mb.Enabled = km.Enabled = true;
            prompt.Enabled = km.Checked;
            if (status.Text.StartsWith("生成中") || status.Text.StartsWith("元に戻して")) status.Text = code == 0 ? "終わりました" : "止まりました";
        }

        void Append(string line)
        {
            log.AppendText(line + Environment.NewLine);
        }

        void Ui(Action a)
        {
            if (IsDisposed) return;
            try { BeginInvoke(a); } catch (InvalidOperationException) { }
        }
    }
}
