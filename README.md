# AIナカワリ（MMD-AINakawari）

MMD（MikuMikuDance）で打ったキーとキーの間を、AI が中割りして埋めるプラグインです。
タイムラインでキーを選んで、右下の「AIナカワリ簡易操作」で「生成」を押すだけ。間のフレームのキーが、MMD のタイムラインにそのまま入ります。

![MMD の右下の簡易操作パネル](docs/images/panel_in_mmd.png)

中の動きを作るのは、NVIDIA の 2 つのモデルです。

- **Kimodo**: 英語の文（プロンプト）から動きを作る。打ったキーのポーズを通りながら、「踊る」「手を振る」などの動きで間を埋める
- **MotionBricks**: プロンプト無しで、キーからキーへの自然な中割りを作る

| 生成の前（30・60・90F にキー） | 生成の後（30〜90F を作り直した） |
|---|---|
| ![生成の前](docs/images/timeline_before.png) | ![生成の後](docs/images/timeline_after.png) |

> [!WARNING]
> **開発版です。** インストーラーはまだ無く、入れるのに Python の環境を 3 つ作る必要があります（下の「インストール」）。
> 本プロジェクトは NVIDIA とは関係のない個人の制作物です。

## できること

| | 内容 |
|---|---|
| **AI 中割り（MotionBricks）** | プロンプト無しで、キーとキーの間（17〜57 フレーム）をつなぐ。キーごとに止まる／勢いのまま通る、手首だけ普通の補間、を選べる |
| **プロンプトで作る（Kimodo）** | 英語の文で動きを指定して、キーの間を埋める。区間ごとに違う文も書ける（`run / 45: stop` なら 45F から stop。区間の始まりのすぐ後ろにキーがあると、つながりを保つため 1 つ後ろへ自動でずれる）。詳細の窓では「最後のキーの後ろに続きを足す」「キーのポーズを使わずプロンプトだけで作る」もできる |
| **選んだキーの間だけ作り直す** | タイムラインで選んだキーの最初から最後までを作り直す。範囲の外の動きは補間曲線ごと保ち（ずれは移動 0.05・回転 0.5° まで。曲線で表せない急な所は、範囲の外にもキーが増えることがある）、範囲の端は外の動きにつながる |
| **キー以外の手がかり**（Kimodo） | 全ての親だけのキーは「腰がそこを通る」目印、足ＩＫ・腕の IK だけのキーは「手足がそこに来る」目印になる（MotionBricks の中割りでは使わない） |
| **なめらかに止まる** | 最後のキーでぴたっと止まらず、MotionBricks で自然に減速して止まる |
| **元に戻す** | 生成の前のモーションに 1 回で戻す |
| **サンプルのプロンプト** | 英語が苦手でも、「前へ歩く：A person walks forward.」のような一覧から選べる（6 種類・43 個） |
| **低負荷モード** | VRAM 8GB の GPU でも動く（文の読み取りを CPU で行う）。VRAM 20GB 以上なら高速モードも選べる |

## 動く環境

| | 必要なもの | 確かめた環境 |
|---|---|---|
| OS | Windows 10／11（64bit） | Windows 11 |
| MMD | MikuMikuDance 9.32 x64（日本語版） | 9.32 x64 |
| プラグインの土台 | [MMDPlugin](https://bowlroll.net/file/121761) ver0.41 64bit | 0.41 |
| GPU | NVIDIA の GPU。GTX 16 シリーズ／RTX 20 シリーズ以降、VRAM 6GB 以上（高速モードは 20GB 以上） | RTX 3090（24GB） |
| メモリ | 32GB 推奨（低負荷モードは文の読み取りに約 15GB 使う） | 64GB |
| ディスク | 約 30GB（モデルと Python の環境） | |

詳細の窓の「プロンプトで作る」タブの下に、この PC の GPU とメモリで動くかの判定が出ます。

## インストール（開発版）

今は、Kimodo・MotionBricks・窓の 3 つの Python 環境を手で作ります。置き場所は、下の手順の場所（`F:\kimodo`・`F:\motionbricks`）に決め打ちになっています。違う場所に置く時は、`mmd_ainakawari/pipeline.py`（`KIMODO_*`・`SOMA_JSON`）・`mmd_ainakawari/smooth_stop.py`（`MB_*`）・`mmd_ainakawari/app.py`（`SERVER_CMD`）と、高速モードを使うなら `tools/start_textencoder.cmd` の中の場所を書き換えてください（設定ファイルにするのは次の作業です）。

### 1. MMDPlugin を入れる
[MMDPlugin](https://bowlroll.net/file/121761)（おいがみ さん）の説明書のとおり、`d3d9.dll`・`d3dx9_43.dll`・`MMDPlugin.dll` を MMD のフォルダに置きます。MME も使う時は、MME 一式を `plugin\mme\` に移します。

### 2. Kimodo を入れる
1. [Kimodo](https://github.com/nv-tlabs/kimodo) を `F:\kimodo\repo` に clone し、[公式の手順](https://research.nvidia.com/labs/sil/projects/kimodo/docs/getting_started/installation.html)で Python 3.10 の環境を `F:\kimodo\.venv` に作ります
2. 文の読み取りに使う [Meta-Llama-3-8B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct) は、Hugging Face で利用の申請（Meta のライセンスへの同意）が要ります。申請が通ったら、Kimodo の環境で `F:\kimodo\.venv\Scripts\hf.exe auth login` を実行してログインしておきます
3. モデルは、最初に生成した時に `F:\kimodo\hf_cache` に入ります（約 17GB）
4. このリポジトリを clone し、そのフォルダで骨格のファイルを書き出します:
   ```bat
   mkdir F:\kimodo\tools
   F:\kimodo\.venv\Scripts\python.exe tools\export_skeleton.py F:\kimodo\tools\somaskel30.json
   ```
5. 高速モード（VRAM 20GB 以上）を使う時は、`tools\start_textencoder.cmd` を `F:\kimodo\` に置きます（詳細の窓の「サーバーを起動」がこれを開きます）

### 3. MotionBricks を入れる
[Git LFS](https://git-lfs.com/) と [uv](https://docs.astral.sh/uv/) を入れてから:
```bat
git clone https://github.com/NVlabs/motionbricks F:\motionbricks
cd /d F:\motionbricks
git lfs pull
uv sync
```
最初に動かした時だけ、GPU に合わせた TensorRT の準備に数分かかります。

### 4. 窓の Python を用意する
窓は [mmd-mcp](https://github.com/BeamManP/mmd-mcp) の MMD とのやりとりの部品を使います（Visual Studio 2022／Build Tools の「C++ によるデスクトップ開発」が要ります）。
```bat
git clone https://github.com/BeamManP/mmd-mcp
cd mmd-mcp
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e . numpy
cmd /c scripts\build_native.cmd
```

### 5. プラグインを MMD に入れる
1. 手順 2 で clone したこのリポジトリのフォルダで作業します
2. `mmd_plugin\build.cmd` でプラグインをビルドします（MMDPlugin の開発用ファイル `mmdplugin_dev_ver0.41_x64` の中身を `work\mmdplugin\dev` に置くか、その場所を環境変数 `AINAKAWARI_SDK` で渡します）
3. できた `mmd_plugin\bin\MMD-AINakawari.dll` を、MMD の `plugin\MMD-AINakawari\` に置きます
4. 同じフォルダに `mmd_plugin\MMD-AINakawari.ini.example` を `MMD-AINakawari.ini` として置き、`python`（手順 4 の `.venv\Scripts\pythonw.exe`）と `home`（このリポジトリのフォルダ）を書きます

MMD を起動して、メニューバーに「AIナカワリ」、下の段の右に「AIナカワリ簡易操作」が出れば入っています。

![MMD の下の段に並んだ簡易操作パネル](docs/images/bottom_strip.png)

## 使い方

### 簡易操作パネル（MMD の右下）

![簡易操作パネル](docs/images/panel.png)

1. MMD でモデルを選び、いつもどおりポーズを付けてキーを打ちます
2. タイムラインで、作り直したい範囲の**最初と最後のキーを選びます**（四角で囲む、またはタイムラインの下の「範囲選択」。どのボーンの行でもかまいません）。パネルに「選んだキー 30〜90F」と出ます
3. 左上で作り方を選びます
   - **Kimodo**: プロンプト（英語）に動きを書きます。分からない時は「**サンプルから選ぶ ▼**」から選べます
   - **MotionBricks**: プロンプトは要りません（欄は灰色になります）
4. 「**生　成**」（またはプロンプト欄で Enter）。下の 1 行に「生成中…」→「できました」と出たら、MMD で再生して確かめます
5. 気に入らなければ「**元に戻す**」か、プロンプトを変えてもう一度「生成」

- パネルの「生成」は、いつも「キーの間を埋める」で作ります。ほかの作り方や seed などの細かい設定は「**詳　細**」の窓で
- 範囲が「選んだキーの間」（既定）の時は、キーを 2 つ以上選ぶまで「生成」は押せません。詳細の窓で範囲を「全部」にすると、パネルも全部のキーで作ります（パネルの字が「全部のキー」になります）
- プロンプト欄に打っている間は、MMD のショートカットキーは効きません。欄の外（タイムラインなど）を押すか Esc で戻ります
- カメラ・照明・アクセサリのモードの時は、パネルは出ません

![サンプルの一覧](docs/images/samples.png)

### 詳細の窓（パネルの「詳　細」か、メニューの「AIナカワリ」）

![詳細の窓](docs/images/window.png)

| 欄 | 中身 |
|---|---|
| 右上の動作モード | **低負荷モード**（既定・VRAM 8GB の GPU でも動く）／**高速モード**（VRAM 20GB 以上。テキスト読み取りサーバーを先に起動） |
| タブ | **プロンプトで作る**（Kimodo）／**中割り**（MotionBricks） |
| やりたいこと | **キーの間を埋める**／**続きを足す**（最後のキーの後ろへ）／**プロンプトだけで作る**（キーのポーズを使わない） |
| プロンプト | 行ごとに「そのフレームから次の行まで」の動き。「＋ 今のフレームで区切る」で行が増える。「サンプルから選ぶ ▼」もある |
| 詳しい設定 | 手数・seed・テキストの効き・キーの効き・後処理・センターの動きを使う |
| 範囲 | **選んだキーの間**（既定）／**全部**（最初のキーから最後のキーまで） |

パネルと詳細の窓は、プロンプトと作り方（Kimodo／MotionBricks）がつながっています。どちらで打っても同じです。

### うまく作るコツ
- プロンプトは英語で、「A person ＋ 動詞」の形が効きます（例: `A person waves with their right hand.`）。日本語はほとんど効きません
- キーは 20 個くらいまでが目安です。多いとキーに縛られて動きが硬くなります
- Kimodo は 1 区間 300 フレーム（10 秒）まで（範囲の外の勢いをつなぐ数フレームも数えるので、選ぶ範囲はそれより少し短めに）。長い時は範囲を分けて作ります
- 最初の 1 回は、モデルの読み込みで 40〜60 秒ほど余分にかかります（低負荷モード）。2 回目からは 10〜15 秒前後です

## 分かっている制限
- **PMX のモデルだけ**に対応しています（PMD は非対応）。標準ボーン（センター・上半身・腕・ひじ・足ＩＫなど）があるモデルが前提で、無いモデルはエラーで止まります
- 指・表情・髪などは作りません（MMD の補間のまま）
- キーのポーズの差が大きいと、前腕・手首が 1 フレームで大きく回ることがあります（中割りなら「手首は普通の補間」で抑えられます）
- 物理演算をオフにしたキーは、生成や「元に戻す」でオンに戻ることがあります（未確認）
- MMD 9.32 x64 の日本語版でしか確かめていません（MMD のメモリから直接読む所があるため、ほかの版では動きません）

## ライセンスとクレジット
- このリポジトリのコード: （公開前に決めます）
- スクリーンショットのモデル: Tda式初音ミクV4X（Tda さん）。初音ミクは クリプトン・フューチャー・メディア株式会社 のキャラクターです
- [Kimodo](https://github.com/nv-tlabs/kimodo)（NVIDIA）: コードは Apache-2.0、モデルは [NVIDIA Open Model License](https://huggingface.co/nvidia/Kimodo-SOMA-RP-v1.2)
- [MotionBricks](https://github.com/NVlabs/motionbricks)（NVIDIA）: コードは Apache-2.0、モデルは NVIDIA Open Model Agreement
- [Meta-Llama-3-8B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct)（Meta）: Meta Llama 3 Community License（Kimodo が文の読み取りに使う）
- [LLM2Vec](https://huggingface.co/McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp)（McGill-NLP）
- [MMDPlugin](https://bowlroll.net/file/121761)（おいがみ さん）
- [mmd-mcp](https://github.com/BeamManP/mmd-mcp)（MIT-0 ほか）

モデルはこのリポジトリには入っていません。それぞれの配布元の条件に同意して取得してください。

## 開発の記録
仕組み・踏んだ問題・確かめた数字は [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) にまとめています。
