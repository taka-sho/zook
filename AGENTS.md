# AGENTS.md

archdiagram は、YAML で書いたインフラ構成から PowerPoint(.pptx)のアーキテクチャ図を生成する CLI ツールです。想定する主な利用者は生成AIです。ユーザーがAIに「○○の要件でインフラ構成を提案してアーキテクチャ図を作って」と依頼する場面を考えてみてください。この依頼を受けたAIは、要件に合うアーキテクチャを選び、archdiagramでYAMLを書き、検証してから図を生成することになります。このファイルは、その一連の流れを迷わず進めるための道筋です。

## アーキテクチャ提案から図の生成までの流れ

1. **近いパターンを探す。** `docs/patterns/README.md` に、要件別のアーキテクチャパターン(3層Webアプリ・サーバーレスAPI・非同期処理・コンテナ基盤など)と、それぞれ「どんな要件のときに選ぶか」がまとまっています。ゼロから構造を組み立てるより、近いパターンのYAMLを土台にして要件に合わせて差分を編集するほうが、確実に構造の破綻を避けられます。

2. **使えるサービス名を確認する。** YAML の `type`(`EC2`、`ComputeEngine` など)はスキーマ上の enum で固定されていません。**アイコンレジストリが語彙の唯一の真実源**です。書き始める前に必ず次を実行し、実在する `type`・別名・カテゴリを確認してください。

   ```bash
   archdiagram icons list --format json
   ```

   存在しない `type` を書いても Fatal エラーにはならず Warning とプレースホルダー表示で処理は続行されますが、意図した見た目にはなりません。

3. **YAML を書く、またはパターンを編集する。** 形式の正式な定義は `docs/arch-diagram.schema.json`(JSON Schema)、読み下した仕様は `docs/yaml-spec.md` にあります。パターンを流用する場合は、要件に合わない部分だけを書き換え、パターン全体の構造(コンテナの入れ子・レイアウト方針)はなるべく維持してください。

4. **検証する。** レンダリングの前に必ず実行してください。

   ```bash
   archdiagram validate diagram.yaml --format json
   ```

   `{"status": "error", ...}` は構造的な破綻(スキーマ違反・id重複・リンク参照先不在など)を意味し、レンダリングしても意味のある出力になりません。`error` フィールドの内容を読んで修正し、`{"status": "ok"}` か `{"status": "warning"}` になるまで直してください。スキーマ違反のメッセージには `(closest match: ...)` という形で具体的な原因が付くので、そこを優先して読むと直しやすいはずです。`warning` は描画上の軽微な問題(重なり・未知のアイコンなど)なので、そのまま進めても構いませんが、内容を確認し意図した配置になっているか判断してください。

5. **生成する。**

   ```bash
   archdiagram build diagram.yaml -o diagram.pptx
   ```

見た目を調整したい場合は、YAML を直接手直しするだけでなく、`archdiagram export-drawio`/`sync` によるdraw.io連携(`docs-site/drawio-sync.md`)という選択肢もあります。

## Mermaidのフローチャートから始まる依頼の場合

ユーザーがすでにMermaidの`flowchart`/`graph`記法で図を持っている(あるいはAI自身がMermaidで業務フローを組み立てた)場合は、上記のYAMLを新規に書く流れの代わりに、まず変換してください。

```bash
archdiagram from-mermaid diagram.mmd -o diagram.yaml
```

変換後のYAMLはこの時点で検証済みなので、そのままステップ5の`build`に進めます。対応記法・既知の制約は`docs-site/mermaid-import.md`を参照してください。`sequenceDiagram`など`flowchart`以外のMermaid図種別には対応していません。

## 主要リファレンス

| 知りたいこと | 参照先 |
|---|---|
| YAML の全フィールド仕様 | `docs/yaml-spec.md`(正本)、`docs-site/yaml-guide.md`(要点) |
| アイコン・コンテナの語彙とレジストリの仕組み | `docs/icon-registry-and-vocabulary.md`、`docs-site/icons.md` |
| 要件別のアーキテクチャパターン | `docs/patterns/README.md` |
| 既知の制約(自動レイアウトが解決しない重なり、GCP/Azureの制約など) | `docs-site/limitations.md` |
| draw.io連携による継続的な図の管理 | `docs-site/drawio-sync.md` |
| Mermaidフローチャートからの変換 | `docs-site/mermaid-import.md` |
| pptx生成の内部設計(座標系・コネクタなど) | `docs-site/design-notes.md`、`docs/detailed-design-pptx.md` |

## 変更作業をするとき

- `docs/arch-diagram.schema.json`/`docs/icon-registry.schema.json` を変更したら、`src/archdiagram/schemas/` 配下の同名ファイルにも同じ内容をコピーしてください(パッケージが読み込むのはこちらのコピーで、2つは常にbyte-identicalである前提です)。
- `docs/registry.<provider>.yaml` を変更したら、`src/archdiagram/data/icons/<provider>/registry.<provider>.yaml` にも同様にコピーしてください。
- 変更後は必ずテストを実行してください。

  ```bash
  .venv/bin/pytest tests/ -v
  ```

- `docs/example.yaml`・`docs/example-cloud-actors.yaml`・`docs/patterns/*.yaml` は「Warningゼロ」を保つ前提の回帰対象です。変更が影響しうる場合は `archdiagram validate` で確認してください。
