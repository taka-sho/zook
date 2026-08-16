# 使い方

[🇬🇧 English](/zook/usage/){ .md-button }

zook は `build`/`validate`/`doctor`/`diff`/`icons`/`preview`/`export-drawio`/`sync`/`from-mermaid` の9つのサブコマンドを持ちます。

```bash
zook --help
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
zook doctor diagram.yaml -o fixed.yaml          # 解消した YAML を別ファイルに書き出す
zook doctor diagram.yaml --fix                  # 元ファイルを直接書き換える(-o 指定時は無視)
zook doctor diagram.yaml --format json          # 機械可読出力(moves/linkChanges/remaining など)
```

`doctor` は次の4段階で解消します(あとの段階ほど前段の結果に依存するため、この順序です)。

1. **要素の重なり(座標調整)。** `validate` が報告する**兄弟要素どうし・要素とコンテナ見出しの重なり**を、要素をずらして解消します。壊れたコンテナの直下要素に明示座標(x/y)を与えて分離するため、結果の YAML は解消後の配置がそのまま再現されます。
2. **リンク経路(接続辺の割り当て)。** リンクは自前の座標を持たず、経路は両端の位置(この時点で確定済み)と接続辺から決まります。そこで**リンクのノード貫通・見かけ上の直接接続(false edge aliasing)・リンクラベルの衝突**を、`fromSide`/`toSide` を割り当てて解消します。割り当て候補ごとに実際の警告数を数え、**厳密に減るときだけ**採用するので、経路が悪化することはありません。
3. **障害物の退避(座標調整)。** 接続辺を変えても迂回できない貫通(経路がノードを突き抜ける)は、経路を動かせないので**障害物側の要素を経路と垂直方向にどかして**解消します。動かすのは自動配置の要素だけで、移動を実際に適用→段階1・2を再実行→総警告数が**厳密に減ったときだけ**採用し、そうでなければ完全に巻き戻します(この段階でも図が悪化することはありません)。
4. **リンクの迂回(経由点の挿入)。** 障害物が著者指定で動かせない場合は、代わりに**リンク側に経由点(`waypoints`)を挿入して障害物の外側へ迂回**させます。障害物の外接矩形を回る経由点を実際に入れて→総警告数が**厳密に減ったときだけ**採用し、そうでなければ巻き戻します。著者が経路(経由点や接続辺)を明示したリンクは意図とみなし、この迂回の対象にしません。

- 既定は**ドライラン**で、提案する変更を表示するだけです(AGENTS.md の「まず提案し、合意を得てから作る」方針に合わせています)。`-o` か `--fix` を付けたときだけファイルに書き込みます。既存のコメント・キー順序は保持されます([draw.io連携](drawio-sync.md)の `sync` と同じ ruamel ラウンドトリップ)。
- 著者が明示した位置(x/y)・接続辺(fromSide/toSide)・経由点(waypoints)は意図とみなし、上書きしません。移動対象は「著者が明示配置した要素より自動配置の要素を優先」、障害物の退避も**自動配置の要素だけ**、リンクの接続辺割り当て・迂回は「著者が経路を明示していないリンクだけ」を対象にします。
- どの段階でも直せない衝突(例: 障害物も両端も著者指定で、接続辺も固定されている場合)は `remaining` として報告され、`status` は `partial` になります。**キャンバス外座標・未知アイコン**は `doctor` の対象外で、同じく `remaining` に出ます。これらは draw.io での手直しや YAML の編集・レジストリ追加で対応してください([既知の制約](limitations.md)参照)。
- `--strict` を付けると、自動解消しきれない衝突が残った場合(`status: partial`)に非ゼロ終了します。

## diff — 2つの図の構造差分を取る

図を YAML=コードとして扱う zook では、変更を Git でレビューできることが強みです。しかし YAML のテキスト差分は「子要素の並び替え」「マッピングの整形」「自動レイアウトが書き込んだ座標」などのノイズが混ざり、本当に見たい変化が埋もれます。`diff` は2つの図を**意味で比較**します。要素を `id`、リンクを id または両端で対応付け、実際に変わったこと——要素の追加・削除・**コンテナ間の移動(再親付け)**・フィールド単位の変更、リンクの追加・削除・変更、canvas の変更——だけを報告します。

```bash
zook diff old.yaml new.yaml                 # 人間可読の構造差分
zook diff old.yaml new.yaml --format json    # 機械可読(CI・AI向け)
zook diff old.yaml new.yaml --exit-code       # 差分があれば非ゼロ終了(git diff --exit-code 相当)
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

- **デフォルト値の正規化**:片方で省略、もう片方で既定値を明示(例: ノードの `provider: aws`、コンテナの `layout: {direction: grid}`)しても、意味は同じなので差分に出しません。子要素の並び替えも差分になりません。
- **再親付けの検出**:ある要素が別のコンテナへ移った場合、追加+削除ではなく「移動」として1件で報告します(例: `web` を `vpc` から `edge` へ)。テキスト差分では読み取れない構造変化です。
- 両ファイルとも検証(スキーマ・意味)を通る必要があります。Fatal な入力は `error` として報告します。
- `--exit-code` を使うと、CI で「意図しない図の変更を検知したら失敗させる」といったゲートに使えます。

## icons list — 登録済みアイコン・コンテナ種別を一覧表示

```bash
zook icons list                  # aws/gcp/azure すべて
zook icons list --provider gcp    # 特定プロバイダのみ
zook icons list --format json
```

```text
[aws]
  node   EC2                  [Compute] (aliases: ec2, AmazonEC2)
  node   Lambda               [Compute] (aliases: lambda, AWSLambda)
  ...
  group  vpc
  group  cloud
  ...
```

`type` を書き間違えて Warning になる前に、実際に使える名前を確認できます。`--registry` を併用すると、独自レジストリを重ねた状態での一覧になります。

## preview — 軽量PNGプレビュー

PowerPoint も LibreOffice も使わずに、構成をすぐに目で確認できます(Pillow による簡易描画。実際の pptx とは見た目が多少異なります)。

```bash
zook preview diagram.yaml -o diagram.png
```

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

## 独自アイコン・スタイルで上書きする

`--registry` オプション(`build`/`validate`/`doctor`/`icons list`/`preview`/`export-drawio`/`sync` 共通)で、組み込みレジストリの上に独自のアイコン・枠スタイル定義を重ねられます。同じキーを定義するとユーザー側が優先されます。ユーザーレジストリの `provider` フィールドで、どのプロバイダに重ねるかが決まります(既定 `aws`)。

```bash
zook build diagram.yaml -o diagram.pptx --registry my-registry.yaml
```

`my-registry.yaml` は [`icon-registry.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/icon-registry.schema.json) に従った形式です。詳細は[アイコン・レジストリ](icons.md)を参照してください。

## エラーハンドリング {: #error-handling }

zook は「構造的な破綻」と「描画上の軽微な問題」を明確に区別します(CI/CD での利用を想定した設計)。

### Fatal(標準エラー出力 + 非ゼロ終了)

以下は生成を即座に中止します。

- YAML が JSON Schema に違反している(必須フィールド欠落・型不一致・未知フィールド・`x`/`y` の片方のみ指定 など)
- element の `id` が重複している
- `links` の `from`/`to` が存在しない `id` を参照している
- `link.fromSide`/`toSide` を両方指定し、かつ軸(`top`/`bottom` の垂直と `left`/`right` の水平)が矛盾している

```bash
$ zook build broken.yaml -o out.pptx
Error: Duplicate element id(s): web
$ echo $?
1
```

### Warning(標準エラー出力に出力して継続)

以下は警告を出しつつ生成を継続します(終了コードは既定 `0`。`--strict` を付けると `1`)。

- `type` がレジストリで解決できない(未知のサービス名) → プレースホルダーアイコンで描画
- 要素の座標がキャンバス範囲外 → クリップせずそのまま配置
- 要素同士が座標上で重なっている(兄弟要素間) → 計算済みの座標から機械的に矩形の重なりを検出して警告。明示座標の子は自動修正しないが、**自動配置の子は明示座標の兄弟と重なる場合に自動でずらされる**(それでも重なりが解消しない場合のみ警告される)
- 子要素がコンテナ自身のラベル文字の領域と重なっている
- リンク(矢印)の経路、またはリンクラベル自体が、接続先以外の要素・他リンクのラベル・コンテナのラベルと重なっている → 接続点から実際に描画される経路(`straight`/`elbow` は正確、`curved` のみ直線近似)をもとに機械的に判定して警告。コンテナのラベルとの重なりは祖先コンテナであっても除外されない
- 2本の別リンクのZルートが共通ノードの同一接続点で連続し、直接接続に見える(false edge aliasing、詳細は[既知の制約](limitations.md))

いずれも `canvas.overlapMargin`([YAML入力仕様](yaml-guide.md#canvas)参照)を設定すると、文字通りの重なりだけでなく「近すぎる」状態も検知対象にできます。

```bash
$ zook build diagram.yaml -o out.pptx
Warning: unknown type 'QuantumFlux' for node 'mystery'; using placeholder icon
Warning: element 'web' overlaps element 'cache'
Wrote out.pptx
```

### 機械可読な出力(`--format`)

`build`/`validate`/`doctor`/`diff`/`export-drawio`/`sync`/`from-mermaid` は `--format json`(1行のJSONオブジェクト)、`--format github`(GitHub Actions の `::warning::`/`::error::` アノテーション)にも対応しています。

```bash
$ zook validate diagram.yaml --format json
{"status": "warning", "warnings": ["unknown type 'QuantumFlux' for node 'mystery'; using placeholder icon"]}
```

CI/CD パイプラインからは、終了コード(`--strict` 併用可)や `--format` の出力でゲートを掛けられます。

## 生成される PowerPoint について

- VPC → AZ → サービスのような入れ子構造は、PowerPoint 上でも階層グループとして生成されます。各階層を個別にドラッグ・編集できます。
- コネクタ(矢印)は矩形図形(アイコン・コンテナ枠)同士の接続点に接続され、図形移動にある程度追従します(詳細は[内部設計メモ](design-notes.md)を参照)。
- 生成される図は「後編集の起点」として十分な品質を目標としており、完璧な自動レイアウトは行いません。重なりの一部(自動配置 vs 明示座標)は自動で回避されますが、それ以外の重なりは Warning として検出されるのみで、PowerPoint 上で手直しする前提です。
