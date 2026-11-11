# リリースの手順

版を上げて配る時に毎回たどる手順。2026-11-11 に 0.3.2・0.3.3 を出した時の実際の流れをまとめた。
リリースのたびの作業は 3 つ（11-11 マスター）: **GitHub の更新**・**エフェクト置き場の配布リンクの更新**・**告知ポストの提示**。

## 0. 前提
- 直しは main に載せる。作業中のブランチ（例 work/mmm）の物を混ぜない
- 作業フォルダ（`E:\Projects\MMDKimodo`）は別のブランチや未コミットの物を抱えていることが多いので、切り替えずに **main 用の作業ツリーを別フォルダに出す**
- 組み立てには Python 3.10.12 以上が要る。PATH の python（3.10.9）は足りないので、mmd-mcp の `.venv`（3.10.14）を使う
- 確かめ用のスクリプトは配布物と同じ Python（`work\release\stage\MMD-AINakawari\python\python.exe`）で回す

## 1. main 用の作業ツリーを出す
```powershell
git worktree add ..\MMDKimodo-main main
New-Item -ItemType Junction -Path ..\MMDKimodo-main\work -Target E:\Projects\MMDKimodo\work
```
`work` をジャンクションで元の `work` に向けると、Kimodo の場所の設定（`paths.json`）・確かめに使う生成結果・
組み立てのキャッシュ（`work\release\cache`）・MMDPlugin の SDK（`work\mmdplugin\dev`）・prebuilt（`work\prebuilt`）を、
どれも写さずにそのまま使える。できた zip も、いつもの `work\release\` に置かれる。

作業ツリーの中で直す時は、作業フォルダで直した差分を当てる:
```powershell
git diff -- <直したファイル> > fix.patch      # 作業フォルダで
git -C ..\MMDKimodo-main apply fix.patch
```

## 2. 確かめる
```powershell
$py = 'E:\Projects\MMDKimodo\work\release\stage\MMD-AINakawari\python\python.exe'
Get-ChildItem ..\MMDKimodo-main\tests\check_*.py | ForEach-Object { & $py -X utf8 $_.FullName | Select-Object -Last 1 }
```
不具合の直しには、直す前に落ちて直した後に通る確かめを `tests\check_<中身>_<日付>.py` で足す
（直す前の確かめは `git stash push -- <ファイル>` で戻して回す）。

## 3. コミットと版上げ（2 コミット）
1. 直しのコミット（何が起きていたか・原因・どう確かめたか）
2. `mmd_ainakawari\__init__.py` の `__version__` を上げるコミット（「0.x.y にする（〜の直し）」）

セットアップの段（`installer\steps.py` の段の版）を変えたかを確かめておく。変えていなければ、更新した人はセットアップのやり直しが要らない（告知とノートに書く）。

## 4. zip を組み立てる（数分。裏で回す）
```powershell
Set-Location ..\MMDKimodo-main
& E:\Projects\mmd-mcp\.venv\Scripts\python.exe -X utf8 tools\release\build_release.py --mmdplugin E:\Downloads\MMDPlugin_v0.41_x64.zip --mmd-mcp E:\Projects\mmd-mcp
```
できた物: `work\release\MMD-AINakawari-0.x.y.zip` と `build_0.x.y.log`。最後に「確かめています: 同梱の Python で窓の部品を読み込む」→ `ok` が出る。

zip を点検する:
- `MMD-AINakawari/app/mmd_ainakawari/__init__.py` の版
- 直したファイルに直しが入っているか
- `MMD-AINakawari/BUILD.json` の `commit` が main の先頭で、`dirty: false`
- sha256（`Get-FileHash <zip> -Algorithm SHA256`）

## 5. ノートと告知の下書き（`work\release\`）
- `notes_0.x.y.md`: 前の版のノートの形をそのまま使う（「0.x.y から変わった所」→「更新の仕方」→「動く環境」→ sha256）。issue の直しは `#番号` でリンクする
- `x_post_0.x.y.md`: memory「x-update-post-format」の形（1 行目「AIナカワリ 0.x.y に更新しました」→ 変わった所 →（使い方の一言）→
  「更新は、MMD を閉じて zip を上から展開 → 「AIナカワリ導入.cmd」だけ。」＋ セットアップのやり直しの有無 → `#AIナカワリ` → 置き場の URL）。
  前の版の告知をまだ出していなければ、まとめた案も置く
- issue があれば、返事の文案（`issueN_reply.md`）。投稿はマスターの名前で出るので、見てもらってから

## 6. GitHub の更新
```powershell
git -C ..\MMDKimodo-main tag -a v0.x.y -m "AIナカワリ 0.x.y" <版上げのコミット>
git -C ..\MMDKimodo-main push origin main
git -C ..\MMDKimodo-main push origin v0.x.y
gh release create v0.x.y work\release\MMD-AINakawari-0.x.y.zip --repo BeamManP/MMD-AINakawari --title "AIナカワリ 0.x.y" --notes-file work\release\notes_0.x.y.md --verify-tag
gh release view v0.x.y --repo BeamManP/MMD-AINakawari --json assets --jq '.assets[].digest'   # sha256 が手元と同じか
```
タグは注記つき（`-a`）、リリース名もタグの文と同じ「AIナカワリ 0.x.y」、載せるのは zip 1 個。

## 7. エフェクト置き場の配布リンクの更新
置き場は `BeamManP/BeamMan-MME-Archive`（GitHub Pages。`https://beammanp.github.io/BeamMan-MME-Archive/`）。手元に置いていないので、作業用に取ってくる。
直すのは `data.json` の AIナカワリ の 1 件だけ:

| 欄 | 中身 |
|---|---|
| `title` | `AIナカワリ 0.x.y` |
| `date` | 出した日（`2026/11/11` の形） |
| `file` | `MMD-AINakawari-0.x.y.zip` |
| `url` | `https://github.com/BeamManP/MMD-AINakawari/releases/download/v0.x.y/MMD-AINakawari-0.x.y.zip` |
| `extras` の「リリースノート」 | `https://github.com/BeamManP/MMD-AINakawari/releases/tag/v0.x.y` |
| `size` | zip の大きさが大きく変わった時だけ（MB、1 桁） |
| `title_en`・`notes_en` | 英語の時に出す題と説明（11-11 から置き場に日本語・英語の切り替えがある）。`title_en` は「AI Nakawari 0.x.y」、`notes_en` は `notes` に足した版の行の英語 |

JSON として読めるかを確かめてからコミット（「AIナカワリ を 0.x.y にする（〜）」）して push。
push の後、公開された `data.json` のリンクと、`url` が 302 を返すか（`curl -sSI`）を確かめる。

## 8. 告知ポストの提示
`x_post_0.x.y.md` の文をマスターに渡す。**投稿はマスターがする**（勝手に投稿しない）。

## 9. 片付け
```powershell
cmd /c rmdir ..\MMDKimodo-main\work      # 先にジャンクションだけ外す
git worktree remove ..\MMDKimodo-main
```
**ジャンクションを外さずに作業ツリーを消さない**（本物の `work` の中身まで消える恐れがある）。
作業中のブランチに同じ直しが未コミットで残っている時は、main を取り込む時にそろえる。
