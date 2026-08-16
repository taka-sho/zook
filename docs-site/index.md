# ZOOK

YAML で書いたクラウドアーキテクチャ定義から、PowerPoint(.pptx)スライドを生成するCLIツールです。

図をコードとして Git 管理し、差分をレビュー可能にしつつ、最終成果物は PowerPoint 上で人間が自由に手編集できる形で出力します。

```yaml
version: "1.0"
canvas:
  aspectRatio: "16:9"
elements:
  - kind: container
    id: vpc-main
    type: vpc
    label: "Production VPC"
    children:
      - kind: node
        id: web
        type: EC2
        label: "WebServer"
      - kind: node
        id: db
        type: RDS
        label: "Primary DB"
links:
  - from: web
    to: db
    label: "3306"
```

```bash
zook build diagram.yaml -o diagram.pptx
```

## なぜ zook なのか

- **コードとしての構成図** — YAML はテキストなので Git 差分でレビューできます。既存の diagram-as-code ツールは PowerPoint 直接出力やアスペクト比の厳密指定に制約があり、変換ステップを挟む運用は妥協とメンテコストが発生しがちでした。zook は YAML → PPTX を一本化します。
- **後編集前提の「そこそこ」の品質** — 完璧な自動レイアウトは目指さず、PowerPoint 上で人間がすぐ手を入れられる状態の出力を優先します。
- **拡張しやすい語彙** — サービスの `type` はスキーマで固定せず、[アイコンレジストリ](icons.md)が語彙の真実源です。新サービスの追加はコード改修なしにレジストリへの追記だけで済みます。
- **LLM 生成を見据えた設計** — 人間可読性よりも機械(LLM)が曖昧さなく生成・パースできることを優先した、JSON Schema で厳密化された入力仕様です。

## 主な機能

| 機能 | 概要 |
|---|---|
| マルチクラウド | AWS/GCP/Azure の組み込みレジストリを同梱。ノードごとに `provider` を指定して混在可能 |
| 階層コンテナ | Cloud → VPC → AZ → subnet のような入れ子構造を `container` の再帰 `children` で表現 |
| クラウド境界 | `type: cloud` でクラウド境界そのものを枠として描画。プロバイダごとのブランドカラー・バッジアイコン付き |
| アクターアイコン | User/Admin/Developer/Client など、構成にアクセスする人物・役割をノードとして配置可能 |
| 自動レイアウト | 座標未指定の要素を grid/horizontal/vertical で自動整列。明示座標との混在も可能。自動配置の要素は明示座標の兄弟と重ならないよう自動でずれる |
| コネクタ | サービス間の関係を矢印付き線で接続。ラベル(ポート番号等)も付与可能。コンテナへのリンクも可。斜めになる接続は自動で直角の折れ線に切り替え |
| 接続辺の指定 | `link.fromSide`/`toSide` で接続する辺(上下左右)を明示指定可能。省略時は実際の経路長を比較して自動選択 |
| 経路の明示(経由点) | `link.waypoints` で中間点(絶対座標)を指定し、任意の折れ線経路を描画。障害物の迂回やL字経路に。指定時は `style` の自動取り回しと接続辺の軸一致ルールが無効になる |
| ラベル回避接続 | ラベル付きノードから同じ方向に矢印を伸ばすと、ラベルを避けてその外側に接続 |
| アイコン解決 | エイリアス込み・大小文字無視でサービス名からアイコンを解決。未知のサービスは警告付きプレースホルダーで継続。`zook icons list` で一覧表示 |
| レジストリ上書き | 組み込みレジストリの上にユーザー独自のアイコン/スタイル定義を重ねられる |
| 重なり検知 | 計算済みの座標から、兄弟要素同士・コンテナのラベル文字・矢印の経路・リンクラベルが互いに重なっていないかを機械的に検出し Warning で通知。`overlapMargin` で近接判定のバッファも設定可能 |
| 衝突の自動解消 | `zook doctor` で4段階に自動解消: 要素の重なりを座標調整、リンクのノード貫通・見かけ上の直接接続を接続辺の割り当て、迂回できない貫通は障害物要素の退避、動かせない障害物はリンクに経由点を挿入して迂回(いずれも悪化しない範囲のみ)。既定はドライラン(提案のみ)、`--fix`/`-o` で YAML に書き戻し([使い方](usage.md)の doctor 節) |
| サイズ・文字サイズ調整 | ノードの `size` でアイコンサイズを、`labelFontSize`(ノード/コンテナ/リンク)でラベル文字サイズを個別に指定可能。自動レイアウトが確保するラベル用スペースも連動して拡大/縮小 |
| 軽量プレビュー | `zook preview` で PowerPoint も LibreOffice も使わずにPNGですぐ確認 |
| draw.io連携 | `zook export-drawio`/`sync` で draw.io 上での位置・サイズ変更をYAMLに反映。継続的な構成図管理を想定([draw.io連携](drawio-sync.md)) |
| Mermaidインポート | `zook from-mermaid` で Mermaid の `flowchart`/`graph` 記法をYAMLに変換([Mermaidフローチャートのインポート](mermaid-import.md)) |
| プレーン図形ノード | アイコンの代わりに四角/角丸/ひし形/円の図形+内部ラベルでノードを描画(`style.shape`)。Mermaidインポートが内部的に使う汎用機能 |
| CI/CD 対応 | 構造的な誤り(スキーマ違反・id重複・リンク参照先不在)は非ゼロ終了。`--strict` で Warning もゲート可能。`--format json`/`github` で機械可読出力。`zook validate` でレンダリングなしの高速チェックも可能 |

## ドキュメント構成

- [インストール](installation.md) — セットアップ手順
- [使い方](usage.md) — CLI コマンドとエラーハンドリング
- [YAML入力仕様](yaml-guide.md) — 図の書き方(コンテナ・ノード・リンク・レイアウト)
- [アイコン・レジストリ](icons.md) — サービス語彙とアイコンの仕組み、カスタマイズ方法
- [draw.io連携](drawio-sync.md) — 継続的な構成図管理のためのdraw.ioエクスポート・同期ワークフロー
- [Mermaidフローチャートのインポート](mermaid-import.md) — Mermaidの`flowchart`/`graph`記法からの変換
- [内部設計メモ](design-notes.md) — pptx生成の実装方針(グループ化・コネクタ・座標系)
- [既知の制約](limitations.md) — v1 時点でのスコープ外事項

より詳細な要件定義・JSON Schema・設計検証の一次資料は、リポジトリの [`docs/`](https://github.com/taka-sho/zook/tree/main/docs) ディレクトリにあります。
