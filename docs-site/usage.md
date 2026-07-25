# 使い方

## 基本

```bash
archdiagram <input.yaml> -o <output.pptx>
```

- `input.yaml` — [YAML入力仕様](yaml-guide.md)に従った構成定義ファイル
- `-o, --output` — 出力する `.pptx` のパス(必須)

## 独自アイコン・スタイルで上書きする

`--registry` オプションで、組み込みの AWS レジストリの上に独自のアイコン・枠スタイル定義を重ねられます。同じキーを定義するとユーザー側が優先されます。

```bash
archdiagram diagram.yaml -o diagram.pptx --registry my-registry.yaml
```

`my-registry.yaml` は [`icon-registry.schema.json`](https://github.com/taka-sho/archtecture-diagram-generator/blob/main/docs/icon-registry.schema.json) に従った形式です。詳細は[アイコン・レジストリ](icons.md)を参照してください。

## エラーハンドリング

archdiagram は「構造的な破綻」と「描画上の軽微な問題」を明確に区別します(CI/CD での利用を想定した設計)。

### Fatal(標準エラー出力 + 非ゼロ終了)

以下は生成を即座に中止します。

- YAML が JSON Schema に違反している(必須フィールド欠落・型不一致・未知フィールド・`x`/`y` の片方のみ指定 など)
- element の `id` が重複している
- `links` の `from`/`to` が存在しない `id` を参照している

```bash
$ archdiagram broken.yaml -o out.pptx
Error: Duplicate element id(s): web
$ echo $?
1
```

### Warning(標準エラー出力に出力して継続)

以下は警告を出しつつ生成を継続します(終了コードは `0`)。

- `type` がレジストリで解決できない(未知のサービス名) → プレースホルダーアイコンで描画
- 要素の座標がキャンバス範囲外 → クリップせずそのまま配置
- 要素同士が座標上で重なっている(兄弟要素間) → 計算済みの座標から機械的に矩形の重なりを検出して警告(自動修正はしない)。明示座標・自動配置のどちらで決まった位置でも同じロジックで検出される
- リンク(矢印)の経路が、接続先以外の要素や他リンクのラベルを横切っている → 接続点の座標から線分と矩形の交差を機械的に判定して警告(`style: straight` は正確、`elbow`/`curved` は直線近似のため参考値)

```bash
$ archdiagram diagram.yaml -o out.pptx
Warning: unknown type 'QuantumFlux' for node 'mystery'; using placeholder icon
Warning: element 'web' overlaps element 'cache'
Warning: link 'web' -> 'db' passes through element 'cache'
Wrote out.pptx
```

CI/CD パイプラインからは、この終了コードでゲートを掛けられます(Fatal のみブロックし、Warning は許容する運用を想定)。

## 生成される PowerPoint について

- VPC → AZ → サービスのような入れ子構造は、PowerPoint 上でも階層グループとして生成されます。各階層を個別にドラッグ・編集できます。
- コネクタ(矢印)は矩形図形(アイコン・コンテナ枠)同士の接続点に接続され、図形移動にある程度追従します(詳細は[内部設計メモ](design-notes.md)を参照)。
- 生成される図は「後編集の起点」として十分な品質を目標としており、完璧な自動レイアウトは行いません。要素の重なりは Warning として検出されますが自動では回避されないため、PowerPoint 上で手直しする前提です。
