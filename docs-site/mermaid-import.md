# Mermaidフローチャートのインポート

[Mermaid](https://mermaid.js.org/)の`flowchart`/`graph`記法で書いた図を、archdiagramのYAMLに変換できます。ノード・矢印・入れ子グループというMermaidフローチャートの構造は、archdiagram自体のコンテナ・ノード・リンクという基盤エンジンとほぼそのまま対応するため、変換後は`validate`/`build`/`export-drawio`/`sync`という既存のパイプラインにそのまま接続できます。

対応するのは`flowchart`のみです。`sequenceDiagram`のような縦のライフライン・時系列メッセージを描く図は、まったく別の描画エンジンが必要になるため、現時点では対象外です。

## 基本フロー

```bash
archdiagram from-mermaid diagram.mmd -o diagram.yaml
archdiagram validate diagram.yaml
archdiagram build diagram.yaml -o diagram.pptx
```

`from-mermaid`は変換後のYAMLを`build`/`validate`と同じ検証(スキーマ・重なり・リンク経路など)にかけてから書き出すため、Fatal/Warningはこの時点で分かります。`--format json`/`github`にも対応しています。

## 対応している記法

- ヘッダー:`flowchart <TD|TB|BT|LR|RL>`、または`graph <...>`(レガシー別名)。`TD`/`TB`/`BT`は縦方向、`LR`/`RL`は横方向のレイアウトに対応します。ヘッダーを省略した場合は縦方向として扱います
- ノード形状:`id[label]`(四角)/`id(label)`(角丸)/`id{label}`(ひし形)/`id((label))`(円)。矢印の中にしか登場しない`id`(形状の宣言が無いもの)は、`id`自体をラベルとして四角ノードとして自動登録されます
- 矢印:`-->`(矢印あり)・`---`(矢印なし)・`<-->`(双方向)・`-.->`/`==>`(点線・太線。見た目の再現はせず`-->`と同じ扱いになります)。`-->|label|`でラベルを付けられます。1行に複数の矢印をつなげる`A --> B --> C`にも対応しています
- `subgraph <id>[<Title>]` 〜 `end`:入れ子にも対応しています。タイトルは省略可能です
- `%% ...`のコメント行は無視されます

## 既知の制約(v1)

- **ノード・サブグラフの並び順はソースの初出順をそのまま反映します。** クロッシングを最小化するようなグラフレイアウトは行わないため、複雑な図では手直しが必要になることがあります。生成後は[draw.io連携](drawio-sync.md)のループでレイアウトを調整してください
- `-- label -->`という(パイプを使わない)ラベル記法には対応していません。`-->|label|`を使ってください
- 点線(`-.->`)・太線(`==>`)は、通常の矢印(`-->`)と同じ見た目で描画されます。線種の違いは再現されません
- ラベル中の引用符やネストしたブレーケットのエスケープは特別扱いしません
- `classDef`/`class`/`style`/`click`などのスタイル・インタラクション用ディレクティブは無視されます
- `sequenceDiagram`など`flowchart`/`graph`以外のMermaid図種別は、その旨のエラーになります

## プレーン図形ノードについて

`from-mermaid`が生成するノードは、アイコンではなく`nodeStyle.shape`(`rect`/`rounded`/`diamond`/`circle`)を使った「図形内部にラベルを描く」ノードです。これはMermaid変換専用の機能ではなく、手書きのYAMLでも使える汎用のノードスタイルです。詳細は[YAML入力仕様](yaml-guide.md)を参照してください。
