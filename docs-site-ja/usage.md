# 使い方

[🇬🇧 English](/zook/usage/){ .md-button }

zook のサブコマンドは `build`/`validate`/`doctor`/`diff`/`icons`/`preview`/`export-drawio`/`sync`/`from-mermaid` と、パッケージに同梱した文書・スキーマ・参考パターンを出力する `guide`/`schema`/`patterns`/`init` です。

```bash
zook --help
zook --version
```

## build — PowerPoint を生成する

```bash
zook build <input.yaml> -o <output.pptx>
```

- `input.yaml` — [YAML入力仕様](yaml-guide.md)に従った構成定義ファイル
- `-o, --output` — 出力する `.pptx` のパス(必須)
- `--registry` — 独自レジストリで組み込みレジストリを上書き([アイコン・レジストリ](icons.md)参照)
- `--strict` — Warning が1件でもあれば非ゼロ終了する(既定では Fatal のときのみ非ゼロ終了)
- `--format {text,json,github}` — 出力形式(後述)

## validate — レンダリングせずに検証だけ行う

`build` から実際の pptx 生成(python-pptx 呼び出し)を除いたものです。スキーマ検証・意味検証・重なり検知はすべて行われるため、LLM が生成した YAML を素早く検証するループに向いています。

```bash
zook validate diagram.yaml
zook validate diagram.yaml --strict          # Warningも失敗扱いにする
zook validate diagram.yaml --format json      # CI向けの機械可読出力
```

## doctor — 重なり・リンク経路の衝突を自動で解消する

`validate` は「兄弟要素どうしの重なり」「リンクがノードを貫通している」といった問題を**検出するだけ**で、修正は書き手に委ねられます(座標や接続辺の手直し)。`doctor` はこの検出止まりを一歩進め、同じ座標計算をもとに衝突を実際に解消して結果を提示します(`-o`/`--fix` でそのまま YAML に書き戻します)。生成AIが最も苦手とする「ピクセル単位の座標調整・接続辺の試行錯誤」をツール側が肩代わりする位置づけです。

```bash
zook doctor diagram.yaml                       # ドライラン: 提案する変更を表示するだけ
zook doctor diagram.yaml -o fixed.yaml          # 解消した YAML を別ファイルに書き出す(直す箇所がなくても必ず書き出す)
zook doctor diagram.yaml --fix                  # 変更があったときだけ元ファイルを書き換える(-o 指定時は無視)
zook doctor diagram.yaml --format json          # 機械可読出力(moves/pinned/linkChanges/remaining など)
```

`doctor` は、すべての変更を1つの基準で判断します。`validate` が報告する警告のうち doctor が影響を与えられるものの**重み付き合計**です。要素の重なり、子要素のコンテナからのはみ出し、リンクが自分の端点を貫くことがもっとも重く、ノードを横切るリンクはコンテナの枠を横切るリンクより重く、ラベルの衝突や見かけ上の直接接続は軽く数えます。スライドからのはみ出しや縮小フィットの警告も含むので、要素をスライドの外に押し出すことを「解消」とは扱いません。変更は実際に適用して測り直し、合計が**厳密に減ったときだけ**採用し、そうでなければ完全に巻き戻すので、doctor が図を悪化させることはありません。次の4段階で解消し(あとの段階ほど前段の結果に依存するため、この順序です)、1巡で改善がある限り繰り返します。そのため、出力に対してもう一度 doctor をかけても何も変わりません。

1. **要素の重なり(座標調整)。** **兄弟要素どうしの重なり、要素とコンテナ見出しの重なり、コンテナからはみ出した子要素**を、衝突を解消できる最短距離だけ(右・下・左・上のいずれか)要素を動かして解消します。動かした先はコンテナの内側(最上位ではスライドの内側)に収めます。壊れたコンテナの直下要素に明示座標(x/y)を与えて分離するため、結果の YAML は解消後の配置がそのまま再現されます。
2. **リンク経路(接続辺の割り当て)。** リンクは自前の座標を持たず、経路は両端の位置(この時点で確定済み)と接続辺から決まります。そこで**リンクのノード貫通・自分の端点の貫通・見かけ上の直接接続(false edge aliasing)・リンクラベルの衝突**を、`fromSide`/`toSide` を割り当てて解消します(同じ辺どうしを割り当てると、障害物を回り込むU字経路になります)。候補の評価は差分計算で行い(付け替えるリンクに関係する警告だけを計算し直します)、選んだ候補は全体のチェックで確かめてから採用します。
3. **障害物の退避(座標調整)。** 接続辺を変えても迂回できない貫通は、経路を動かせないので**障害物側の要素を経路と垂直方向に、コンテナの内側にとどめたままどかして**解消します。動かすのは自動配置の要素だけで、移動候補ごとに段階1・2を再実行します。
4. **リンクの迂回(経由点の挿入)。** 障害物が著者指定で動かせない場合は、代わりに**リンクに直角に折れる経由点(`waypoints`)を挿入して障害物の外側へ迂回**させます。著者が経路(経由点や接続辺)を明示したリンクは意図とみなし、この迂回の対象にしません。

- 既定は**ドライラン**で、提案する変更を表示するだけです(AGENTS.md の「まず提案し、合意を得てから作る」方針に合わせています)。`-o` か `--fix` を付けたときだけファイルに書き込みます。`-o PATH` は、直す箇所がなかった場合もバイト単位で同じコピーとして必ず `PATH` を書き出します。そのため `zook doctor d.yaml -o fixed.yaml && zook build fixed.yaml ...` が、存在しないファイルや前回の古いファイルを読むことはありません。`--fix` は、問題のないファイルには手を付けません。既存のコメント・キー順序・ファイル自身のインデントの書き方は保持され、整数の座標は整数のまま書き出します([draw.io連携](drawio-sync.md)の `sync` と同じ ruamel ラウンドトリップ)。
- 著者が明示した接続辺(fromSide/toSide)・経由点(waypoints)は変更しません。移動対象は「著者が明示配置した要素より自動配置の要素を優先」し、重なった2要素が**どちらも**著者の明示配置のときに限り、その一方(後に書かれた方)を動かします。その場合も、図が厳密に改善するときだけです。障害物の退避で動かすのは**自動配置の要素だけ**です。
- 報告には、**`moves`**(描画位置が変わった要素)と **`pinned`**(自動配置だった要素に、今の位置のまま明示座標を書き込んだもの。隣の要素を動かしてもコンテナが配置を詰め直さないようにするためで、見た目は変わりませんがファイルは変わります)、`linkChanges` が含まれます。
- どの段階でも直せなかったものは `remaining` として報告され、`status` は `partial` になります。**未知のアイコン**と、スライドからのはみ出し・縮小フィットの警告も `remaining` に出ます(これらで `status` が `partial` になることはありません)。YAML の編集やレジストリの追加で対応してください([既知の制約](limitations.md)参照)。
- `--strict` を付けると、`remaining` に何か残っている場合に非ゼロ終了します。

## diff — 2つの図の構造差分を取る

図を YAML=コードとして扱う zook では、変更を Git でレビューできることが強みです。しかし YAML のテキスト差分は「マッピングの整形」「明示座標の要素の並び替え」「既定値の書き出し」などのノイズが混ざり、本当に見たい変化が埋もれます。`diff` は2つの図を**意味で比較**します。要素を `id` で、リンクを id、次に両端と属性で対応付け、実際に変わったこと——要素の追加・削除・**コンテナ間の移動(再親付け)**・**並び順の変更**(並び順がそのまま配置になる自動配置の兄弟)・フィールド単位の変更、リンクの追加・削除・変更、canvas の変更——だけを報告します。

```bash
zook diff old.yaml new.yaml                 # 人間可読の構造差分
zook diff old.yaml new.yaml --format json    # 機械可読(CI・AI向け)
zook diff old.yaml new.yaml --exit-code       # 差分があれば終了コード 1(git diff --exit-code 相当)。入力が不正なら 2
```

```text
~ canvas.aspectRatio: "16:9" -> "4:3"
+ api (node Lambda) in vpc
- cache (node ElastiCache) in vpc
> web: moved vpc -> edge
~ db (node RDS): type "RDS" -> "Aurora"; label "Primary DB" -> "Main DB"
+ link api -> db
~ link web -> db: style "straight" -> "elbow"
```

記号は `+` 追加 / `-` 削除 / `>` 移動(再親付け) / `~` 変更 です。

- **デフォルト値の正規化**:片方で省略、もう片方で既定値を明示(ノードの `provider: aws`、コンテナの `layout: {direction: grid}`、`labelPosition: below`、レジストリと同じ枠の色、アイコンの `size: 64` など)しても、意味は同じなので差分に出しません。明示座標の要素の並び替えも差分になりません。自動配置の要素の並び替えは、配置が変わるので差分として報告します。
- **同じ2要素を結ぶリンク**は、属性が完全に一致するものから対応付けます。そのため、2本の並行リンクの片方を消すと削除1件になります。リンクに `id` を付けただけの場合は、追加と削除ではなく id の変更として報告します。
- **再親付けの検出**:ある要素が別のコンテナへ移った場合、追加+削除ではなく「移動」として1件で報告します(例: `web` を `vpc` から `edge` へ)。テキスト差分では読み取れない構造変化です。
- 両ファイルとも検証(スキーマ・意味)を通る必要があります。Fatal な入力は、どちらのファイルかを先頭に付けて(`old diagram old.yaml: ...` / `new diagram new.yaml: ...`)`error` として報告し、終了コード **2** で終わります。`--exit-code` の「差分あり」(1)と取り違えることはありません。
- `--exit-code` を使うと、CI で「意図しない図の変更を検知したら失敗させる」といったゲートに使えます。

## icons list — 登録済みアイコン・コンテナ種別を一覧表示

```bash
zook icons list                  # aws/gcp/azure すべて
zook icons list --provider gcp    # 特定プロバイダのみ
zook icons list --format json
```

```text
[aws]
  node   EC2                  [Compute] (aliases: AmazonEC2)
  node   Lambda               [Compute] (aliases: AWSLambda)
  ...
  group  vpc
  group  cloud
  ...
```

`type` を書き間違えて Warning になる前に、実際に使える名前を確認できます。名前の照合では、大文字小文字・空白・ハイフン・アンダースコア・ドットの違いを無視します(`API Gateway` でも `APIGateway` が見つかります)。`any provider` と付いたアイコン(アクター、Server、Internet など)は、GCP/Azure の図でも使えます。`--registry` を併用すると、独自レジストリを重ねた状態での一覧になります。

## preview — 軽量PNGプレビュー

PowerPoint も LibreOffice も使わずに、構成をすぐに目で確認できます(Pillow による簡易描画。実際の pptx とは見た目が多少異なります)。

```bash
zook preview diagram.yaml -o diagram.png
zook preview diagram.yaml -o diagram.png --format json   # validate と同じ status/warnings を返す
```

出力先は `.png` のパスにしてください。`--format`/`--strict` は `build` と同じように動きます。

文字は、日本語・中国語・韓国語の字形を持つシステムフォント(ヒラギノ、Noto Sans CJK、游ゴシックなど)で描きます。`ZOOK_PREVIEW_FONT` に `.ttf`/`.ttc` を指定すればそのフォントを使います。指定したファイルが読み込めないか CJK の字形を持たない場合は、Warning を出したうえで無視し、通常の候補から選びます。このフォントの英字はスライドの Calibri より少し幅が広いため、ラベルの枠からはみ出す行は少し小さくして枠内に描きます。スライドに収めるための縮小がかかっても、線の太さと矢じりは .pptx と同じく縮小しません。

## export-drawio / sync — draw.ioで手直しして継続的に管理する

生成した構成図を[draw.io](https://www.diagrams.net/)で手直しし、その位置・サイズの変更をYAMLに機械的に反映できます。詳細な運用フローは[draw.io連携](drawio-sync.md)を参照してください。

```bash
zook export-drawio diagram.yaml -o diagram.drawio   # draw.ioで開ける形式で書き出す
# ... draw.io で位置・サイズを調整して保存 ...
zook sync diagram.yaml diagram.drawio -o diagram.yaml # 変更をYAMLに反映
```

## from-mermaid — Mermaidフローチャートから変換する

[Mermaid](https://mermaid.js.org/)の`flowchart`/`graph`記法をzookのYAMLに変換します。詳細は[Mermaidフローチャートのインポート](mermaid-import.md)を参照してください。

```bash
zook from-mermaid diagram.mmd -o diagram.yaml
```

## guide / schema / patterns / init — リポジトリなしで始める

手順・YAML 仕様・参考パターン・JSON Schema はパッケージに同梱されています。そのため、zook を `pipx`/`uv tool` で入れて自分のリポジトリで作業する AI エージェントも、clone せずに参照できます(文書は英語)。

```bash
zook guide                        # 手順を1ステップずつ(AGENTS.md のエージェント向け部分)
zook guide yaml                   # YAML の全仕様。ほかに patterns, usage, limitations, mermaid, drawio
zook schema                       # 図の JSON Schema(--icon-registry で --registry ファイルのもの)
zook patterns list                # 参考アーキテクチャと用途の一覧(--format json も可)
zook patterns show serverless-api # パターン1つの YAML
zook init diagram.yaml            # 小さな有効な雛形
zook init diagram.yaml --pattern container-platform   # パターンから始める(上書きは --force)
```

## 独自アイコン・スタイルで上書きする

`--registry` オプション(`build`/`validate`/`doctor`/`icons list`/`preview`/`export-drawio`/`sync`/`from-mermaid` 共通。複数回指定可)で、組み込みレジストリの上に独自のアイコン・枠スタイル定義を重ねられます。type を定義し直すとフィールド単位でマージされ、ユーザー側の値が優先されます。ユーザーレジストリの `provider` フィールドで、どのプロバイダに重ねるかが決まります(既定 `aws`。独自の語彙なら `custom`)。

```bash
zook build diagram.yaml -o diagram.pptx --registry my-registry.yaml
```

`my-registry.yaml` は [`icon-registry.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/icon-registry.schema.json) に従った形式です(`zook schema --icon-registry` で表示できます)。アイコンファイルには PNG・JPEG・SVG を使えます。詳細は[アイコン・レジストリ](icons.md)を参照してください。

## エラーハンドリング {: #error-handling }

zook は「構造的な破綻」と「描画上の軽微な問題」を明確に区別します(CI/CD での利用を想定した設計)。

### Fatal(標準エラー出力 + 非ゼロ終了)

以下は生成を即座に中止します。

- ファイルを YAML として読めない。構文エラー(行・列付きで報告)、**同じキーの二重記述**(例: `links:` ブロックが2つ。黙って後勝ちにせずエラーにします)、UTF-8 以外の文字コード(UTF-8 の BOM は可)が該当します
- YAML が JSON Schema に違反している(必須フィールド欠落・型不一致・未知フィールド・`x`/`y` の片方のみ指定 など)。違反は1件ずつ正確なパス付きで報告されます(例: `$['elements'][0]['children'][1]['style']['labelPosition']: 'bottom' is not one of [...]`)。YAML が引用符なしの値を数値や真偽値として読んだ場合(`aspectRatio: 16:9` は `969`、`label: no` は `false` になる)は、引用符で囲むよう案内が付きます
- 数値が `.nan`/`.inf`、または極端に大きい(±1,000,000 を超える)
- element の `id` が重複している
- `links` の `from`/`to` が存在しない `id` を参照している
- `link.fromSide`/`toSide` を両方指定し、かつ軸(`top`/`bottom` の垂直と `left`/`right` の水平)が矛盾している
- 入力を読めない(存在しない・読み取り権限がない・ディレクトリである)、または出力先に書き込めない(ディレクトリが存在しない、出力先がディレクトリである など)。`build`/`preview`/`export-drawio`/`from-mermaid` で出力先が入力ファイルそのもの(`sync` では同期元の `.drawio`)になっている場合も含みます。大文字・小文字だけが違う同じファイルへのパスも同様です
- `--registry` のファイルが [`icon-registry.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/icon-registry.schema.json) に合っていない

```bash
$ zook build broken.yaml -o out.pptx
Error: Duplicate element id(s): web
$ echo $?
1
```

### Warning(標準エラー出力に出力して継続)

以下は警告を出しつつ生成を継続します(終了コードは既定 `0`。`--strict` を付けると `1`)。

- `type` がレジストリで解決できない(未知のサービス名) → プレースホルダーアイコンで描画。Warning には近い type の候補や、その type を持つ provider が示される
- アイコンファイルを画像として読めない(PNG・JPEG はそのまま使い、SVG はラスタライズする) → プレースホルダーアイコンで描画
- コンテナの `type` がレジストリにない → 素の枠で描画。Warning には最も近いコンテナ種別が示される(意図して素の枠にしたい場合は `type: group`)
- スライドに収めるのに 70% 未満への縮小が必要になった(既定の `canvas.fit: shrink`。それより軽い縮小は警告しない) → 縮小はしたうえで、キャンバス外に明示座標で置かれた要素があればその名前を示す。座標の打ち間違い(`1200` のつもりの `x: 12000` など)が典型的な原因のため
- `canvas.fit: none` のとき、キャンバスの外に描かれるもの(要素、ノードのラベル、リンクやそのラベル) → クリップせずそのまま配置
- 要素同士が座標上で重なっている(兄弟要素間) → 計算済みの座標から機械的に矩形の重なりを検出して警告。明示座標の子は自動修正しないが、**自動配置の子は明示座標の兄弟と重なる場合に自動でずらされる**(それでも重なりが解消しない場合のみ警告される)
- 子要素がコンテナ自身のラベル文字の領域と重なっている
- 子要素が自分のコンテナからはみ出している(コンテナの明示サイズを超える明示座標や、負の座標)
- リンクの経路が自分の端点ノードを貫いている(例: 下へ向かうリンクに `fromSide: top` を指定した場合)
- リンクのラベルが自分の端点ノードを覆っている。短いリンクの矢じりを隠してしまうラベルは、線の横へ(必要なら端点のアイコンの外側まで)ずらして置くので、この警告はずらす先が見つからない場合にだけ出る
- リンク(矢印)の経路、またはリンクラベル自体が、接続先以外の要素・他リンクのラベル・コンテナのラベルと重なっている → 接続点から実際に描画される経路(`straight`/`elbow` は正確、`curved` のみ直線近似)をもとに機械的に判定して警告。コンテナのラベルとの重なりは祖先コンテナであっても除外されない
- 2本の別リンクのZルートが共通ノードの同一接続点で連続し、直接接続に見える(false edge aliasing、詳細は[既知の制約](limitations.md))

いずれも `canvas.overlapMargin`([YAML入力仕様](yaml-guide.md#canvas)参照)を設定すると、文字通りの重なりだけでなく「近すぎる」状態も検知対象にできます。

```bash
$ zook build diagram.yaml -o out.pptx
Warning: unknown type 'Lamda' for node 'fn' (provider 'aws'); using placeholder icon - did you mean 'Lambda'?
Warning: element 'web' overlaps element 'cache'
Wrote out.pptx
```

### 機械可読な出力(`--format`)

`build`/`validate`/`doctor`/`diff`/`preview`/`export-drawio`/`sync`/`from-mermaid` は `--format json`(標準出力に1行のJSONオブジェクト)、`--format github`(GitHub Actions の `::warning::`/`::error::` アノテーション。複数行のメッセージも1つのアノテーションに収めます)にも対応しています。`icons list --format json` は語彙を JSON で出力します(`github` ではエラーだけがアノテーションになります)。

`--format json` では、`warnings`(doctor では `remaining`)は従来どおりメッセージ文字列の配列です。`details`(`remainingDetails`)は同じ内容を1件ずつ構造化したもので、安定した **`code`**、関係する要素の id(**`elements`**)、関係するリンク(**`links`**。`{"from", "to", "id"}`)を持ちます。ツールや AI は、メッセージを解析しなくても Warning に対処できます。エラーも同様に `errorCode` と `errorDetails` を持ちます(スキーマ違反ごとの `path` と `pointer`、YAML エラーの `line`/`column`、存在しないリンク先の `didYouMean` など)。

```bash
$ zook validate diagram.yaml --format json
{"status": "warning", "warnings": ["unknown type 'Lamda' for node 'fn' ..."], "details": [{"code": "unknown-type", "message": "unknown type 'Lamda' for node 'fn' ...", "elements": ["fn"], "links": []}]}
$ zook validate broken.yaml --format json
{"status": "error", "warnings": [], "details": [], "error": "YAML error in broken.yaml at line 7, column 10: ...", "errorCode": "yaml-syntax", "errorDetails": [{"file": "broken.yaml", "line": 7, "column": 10}]}
```

| Warning の `code` | 意味(`elements` / `links` に入るもの) |
|---|---|
| `unknown-type` / `unknown-container-type` | `type` がレジストリにない。メッセージに近い候補を示す(その要素) |
| `icon-file-missing` / `icon-file-unreadable` | レジストリのアイコンファイルがない、または画像として読めない(その要素) |
| `element-overlap` | 兄弟要素どうしが重なっている(両方) |
| `container-label-overlap` | 要素がコンテナのラベルに重なっている(要素、コンテナ) |
| `outside-container` | 子要素がコンテナの外にはみ出している(子、コンテナ) |
| `link-crosses-element` / `link-crosses-container-label` / `link-crosses-link-label` | リンクの経路が要素・コンテナのラベル・他のリンクのラベルを貫いている(その要素やコンテナ。そのリンクと、相手のリンク) |
| `link-through-own-endpoint` | リンクが自分の端点を貫いて折り返している |
| `link-label-overlaps-element` / `link-label-overlaps-container-label` / `link-labels-overlap` / `link-label-covers-endpoint` | リンクのラベルが何かを覆っている |
| `link-aliasing` | 2本のリンクが同じ直線上で重なり、1本の接続に見える(両方のリンク) |
| `canvas-shrunk` / `off-canvas` | スライドに収めるため 70% 未満に縮小した(キャンバス外に明示座標で置かれた要素)/ `fit: none` でスライドの外に描かれる |
| `registry-alias-ignored` | `--registry` の別名が、別の type の名前と同じ |
| `preview-font-ignored` / `preview-no-cjk-font` | preview のみ。フォントの設定 |
| `sync-…` | `sync` のみ。draw.io で編集されたが同期しない内容(`sync-reparent-ignored`、`sync-label-changed`、`sync-link-added` など) |

| `errorCode` | 意味 |
|---|---|
| `schema` | スキーマ違反(`errorDetails` にそれぞれの `path`・`pointer`・`message`) |
| `yaml-syntax` / `duplicate-key` / `not-utf8` / `not-a-diagram` | ファイルを図として読めない |
| `duplicate-id` / `duplicate-link-id` / `unknown-link-endpoint` / `link-side-axis-mismatch` / `invalid-number` | id・リンク・数値の整合が取れていない |
| `invalid-registry` | `--registry` のファイルがスキーマに合っていない |
| `io-error` / `internal-error` / `fatal` | パスを読み書きできない / zook の不具合 / その他 |

Fatal、読めないファイル、書き込めない出力先など、失敗はすべてこの形で報告され、Python のトレースバックにはなりません。想定外の内部エラーも `internal error: ...` というメッセージで同じ形に報告されます(`ZOOK_DEBUG=1` を設定すると標準エラー出力にトレースバックも出ます。報告にご協力ください)。

CI/CD パイプラインからは、終了コード(`--strict` 併用可)や `--format` の出力でゲートを掛けられます。

### 終了コード

| コード | 意味 |
|---|---|
| `0` | 成功(Warning が出ている場合を含む) |
| `1` | Fatal・エラー。`--strict` 指定時は Warning が1件以上ある場合も(`doctor --strict` では解消しきれない衝突が残った場合)。`diff --exit-code` では差分があること |
| `2` | `diff` のみ: 入力が不正(存在しない・読めない入力ファイルもほかのエラーと同じ扱いで、`1`、`diff` では `2` になります)。未知のオプションなど引数の誤りでも、引数パーサがこのコードを返します |

## 生成される PowerPoint について

- VPC → AZ → サービスのような入れ子構造は、PowerPoint 上でも階層グループとして生成されます。各階層を個別にドラッグ・編集できます。
- コネクタ(矢印)は矩形図形(アイコン・コンテナ枠)同士の接続点に接続され、図形移動にある程度追従します(詳細は[内部設計メモ](design-notes.md)を参照)。
- 生成される図は「後編集の起点」として十分な品質を目標としており、完璧な自動レイアウトは行いません。重なりの一部(自動配置 vs 明示座標)は自動で回避されますが、それ以外の重なりは Warning として検出されるのみで、PowerPoint 上で手直しする前提です。
