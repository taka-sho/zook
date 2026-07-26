# 使い方

archdiagram は `build`/`validate`/`icons`/`preview`/`export-drawio`/`sync`/`from-mermaid` の7つのサブコマンドを持ちます。

```bash
archdiagram --help
```

## build — PowerPoint を生成する

```bash
archdiagram build <input.yaml> -o <output.pptx>
```

- `input.yaml` — [YAML入力仕様](yaml-guide.md)に従った構成定義ファイル
- `-o, --output` — 出力する `.pptx` のパス(必須)
- `--registry` — 独自レジストリで組み込みレジストリを上書き([アイコン・レジストリ](icons.md)参照)
- `--strict` — Warning が1件でもあれば非ゼロ終了する(既定では Fatal のときのみ非ゼロ終了)
- `--format {text,json,github}` — 出力形式(後述)

## validate — レンダリングせずに検証だけ行う

`build` から実際の pptx 生成(python-pptx 呼び出し)を除いたものです。スキーマ検証・意味検証・重なり検知はすべて行われるため、LLM が生成した YAML を素早く検証するループに向いています。

```bash
archdiagram validate diagram.yaml
archdiagram validate diagram.yaml --strict          # Warningも失敗扱いにする
archdiagram validate diagram.yaml --format json      # CI向けの機械可読出力
```

## icons list — 登録済みアイコン・コンテナ種別を一覧表示

```bash
archdiagram icons list                  # aws/gcp/azure すべて
archdiagram icons list --provider gcp    # 特定プロバイダのみ
archdiagram icons list --format json
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
archdiagram preview diagram.yaml -o diagram.png
```

## export-drawio / sync — draw.ioで手直しして継続的に管理する

生成した構成図を[draw.io](https://www.diagrams.net/)で手直しし、その位置・サイズの変更をYAMLに機械的に反映できます。詳細な運用フローは[draw.io連携](drawio-sync.md)を参照してください。

```bash
archdiagram export-drawio diagram.yaml -o diagram.drawio   # draw.ioで開ける形式で書き出す
# ... draw.io で位置・サイズを調整して保存 ...
archdiagram sync diagram.yaml diagram.drawio -o diagram.yaml # 変更をYAMLに反映
```

## from-mermaid — Mermaidフローチャートから変換する

[Mermaid](https://mermaid.js.org/)の`flowchart`/`graph`記法をarchdiagramのYAMLに変換します。詳細は[Mermaidフローチャートのインポート](mermaid-import.md)を参照してください。

```bash
archdiagram from-mermaid diagram.mmd -o diagram.yaml
```

## 独自アイコン・スタイルで上書きする

`--registry` オプション(`build`/`validate`/`icons list`/`preview`/`export-drawio`/`sync` 共通)で、組み込みレジストリの上に独自のアイコン・枠スタイル定義を重ねられます。同じキーを定義するとユーザー側が優先されます。ユーザーレジストリの `provider` フィールドで、どのプロバイダに重ねるかが決まります(既定 `aws`)。

```bash
archdiagram build diagram.yaml -o diagram.pptx --registry my-registry.yaml
```

`my-registry.yaml` は [`icon-registry.schema.json`](https://github.com/taka-sho/archtecture-diagram-generator/blob/main/docs/icon-registry.schema.json) に従った形式です。詳細は[アイコン・レジストリ](icons.md)を参照してください。

## エラーハンドリング {: #error-handling }

archdiagram は「構造的な破綻」と「描画上の軽微な問題」を明確に区別します(CI/CD での利用を想定した設計)。

### Fatal(標準エラー出力 + 非ゼロ終了)

以下は生成を即座に中止します。

- YAML が JSON Schema に違反している(必須フィールド欠落・型不一致・未知フィールド・`x`/`y` の片方のみ指定 など)
- element の `id` が重複している
- `links` の `from`/`to` が存在しない `id` を参照している
- `link.fromSide`/`toSide` を両方指定し、かつ軸(`top`/`bottom` の垂直と `left`/`right` の水平)が矛盾している

```bash
$ archdiagram build broken.yaml -o out.pptx
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
$ archdiagram build diagram.yaml -o out.pptx
Warning: unknown type 'QuantumFlux' for node 'mystery'; using placeholder icon
Warning: element 'web' overlaps element 'cache'
Wrote out.pptx
```

### 機械可読な出力(`--format`)

`build`/`validate`/`export-drawio`/`sync`/`from-mermaid` は `--format json`(1行のJSONオブジェクト)、`--format github`(GitHub Actions の `::warning::`/`::error::` アノテーション)にも対応しています。

```bash
$ archdiagram validate diagram.yaml --format json
{"status": "warning", "warnings": ["unknown type 'QuantumFlux' for node 'mystery'; using placeholder icon"]}
```

CI/CD パイプラインからは、終了コード(`--strict` 併用可)や `--format` の出力でゲートを掛けられます。

## 生成される PowerPoint について

- VPC → AZ → サービスのような入れ子構造は、PowerPoint 上でも階層グループとして生成されます。各階層を個別にドラッグ・編集できます。
- コネクタ(矢印)は矩形図形(アイコン・コンテナ枠)同士の接続点に接続され、図形移動にある程度追従します(詳細は[内部設計メモ](design-notes.md)を参照)。
- 生成される図は「後編集の起点」として十分な品質を目標としており、完璧な自動レイアウトは行いません。重なりの一部(自動配置 vs 明示座標)は自動で回避されますが、それ以外の重なりは Warning として検出されるのみで、PowerPoint 上で手直しする前提です。
