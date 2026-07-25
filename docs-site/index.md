# archdiagram

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
archdiagram diagram.yaml -o diagram.pptx
```

## なぜ archdiagram なのか

- **コードとしての構成図** — YAML はテキストなので Git 差分でレビューできます。既存の diagram-as-code ツールは PowerPoint 直接出力やアスペクト比の厳密指定に制約があり、変換ステップを挟む運用は妥協とメンテコストが発生しがちでした。archdiagram は YAML → PPTX を一本化します。
- **後編集前提の「そこそこ」の品質** — 完璧な自動レイアウトは目指さず、PowerPoint 上で人間がすぐ手を入れられる状態の出力を優先します。
- **拡張しやすい語彙** — サービスの `type` はスキーマで固定せず、[アイコンレジストリ](icons.md)が語彙の真実源です。新サービスの追加はコード改修なしにレジストリへの追記だけで済みます。
- **LLM 生成を見据えた設計** — 人間可読性よりも機械(LLM)が曖昧さなく生成・パースできることを優先した、JSON Schema で厳密化された入力仕様です。

## 主な機能

| 機能 | 概要 |
|---|---|
| 階層コンテナ | AWS Cloud → VPC → AZ → subnet のような入れ子構造を `container` の再帰 `children` で表現 |
| AWS Cloud 境界 | `type: cloud` でクラウド境界そのものを枠として描画。隅にバッジアイコン付き |
| アクターアイコン | User/Admin/Developer/Client など、構成にアクセスする人物・役割をノードとして配置可能 |
| 自動レイアウト | 座標未指定の要素を grid/horizontal/vertical で自動整列。明示座標との混在も可能 |
| コネクタ | サービス間の関係を矢印付き線で接続。ラベル(ポート番号等)も付与可能。コンテナへのリンクも可 |
| アイコン解決 | エイリアス込み・大小文字無視でサービス名からアイコンを解決。未知のサービスは警告付きプレースホルダーで継続 |
| レジストリ上書き | 組み込みレジストリの上にユーザー独自のアイコン/スタイル定義を重ねられる |
| 重なり検知 | 計算済みの座標から兄弟要素同士の重なりを機械的に検出し Warning で通知(明示座標・自動配置いずれにも適用) |
| リンク経路検知 | 矢印の経路が無関係な要素や他リンクのラベルを横切っていないかを座標から機械的に検出 |
| CI/CD 対応 | 構造的な誤り(スキーマ違反・id重複・リンク参照先不在)は非ゼロ終了。CLI 単体で動作 |

## ドキュメント構成

- [インストール](installation.md) — セットアップ手順
- [使い方](usage.md) — CLI コマンドとエラーハンドリング
- [YAML入力仕様](yaml-guide.md) — 図の書き方(コンテナ・ノード・リンク・レイアウト)
- [アイコン・レジストリ](icons.md) — サービス語彙とアイコンの仕組み、カスタマイズ方法
- [内部設計メモ](design-notes.md) — pptx生成の実装方針(グループ化・コネクタ・座標系)
- [既知の制約](limitations.md) — v1 時点でのスコープ外事項

より詳細な要件定義・JSON Schema・設計検証の一次資料は、リポジトリの [`docs/`](https://github.com/taka-sho/archtecture-diagram-generator/tree/main/docs) ディレクトリにあります。
