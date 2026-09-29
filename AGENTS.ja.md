# AGENTS.md (日本語版)

*[English version](./AGENTS.md)*

zook は、YAML で書いたインフラ構成から PowerPoint(.pptx)のアーキテクチャ図を生成する CLI ツールです。想定する主な利用者は生成AIです。ユーザーがAIに「○○の要件でインフラ構成を提案してアーキテクチャ図を作って」と依頼する場面を考えてみてください。この依頼を受けたAIは、まず構成案をテキストで提示して合意を得ます。そのうえで要件に合うアーキテクチャを選び、zookでYAMLを書き、検証してから図を生成することになります。このファイルは、その一連の流れを迷わず進めるための道筋です。

以下の内容はパッケージにも同梱されています。そのため、zook をリポジトリの clone ではなく `pip`/`pipx` で入れた環境でも使えます。`zook guide` で以下の手順(英語)を、`zook guide yaml` で YAML の全仕様を、`zook patterns list` で参考アーキテクチャを、`zook schema` で JSON Schema を表示できます。

## アーキテクチャ提案から図の生成までの流れ

1. **まずテキストで構成案を提示し、合意を得る。** 要件を受け取っても、いきなりzookでYAML/pptxを作り始めないでください。想定する構成を箇条書きやアスキーアート程度の軽量な形でユーザーに示し、方向性の合意を得てから次のステップに進みます。この段階ではzookのコマンドを一切実行しません。認識のズレは、実際に図を生成する前に直すほうがずっと安く済みます。

2. **近いパターンを探す。** `zook patterns list` で、要件別のアーキテクチャパターン(3層Webアプリ・サーバーレスAPI・非同期処理・コンテナ基盤など)と、それぞれの用途を一覧できます。選び方は `zook guide patterns` にまとまっています。最も近いものを `zook init diagram.yaml --pattern <名前>` で書き出し、要件に合わせて差分を編集してください。ゼロから構造を組み立てるより、確実に構造の破綻を避けられます。

3. **使えるサービス名を確認する。** YAML の `type`(`EC2`、`ComputeEngine` など)はスキーマ上の enum で固定されていません。**アイコンレジストリが語彙の唯一の真実源**です。書き始める前に必ず次を実行し、実在する `type`・別名・カテゴリを確認してください。

   ```bash
   zook icons list --format json
   ```

   存在しない `type` を書いても Fatal エラーにはならず Warning とプレースホルダー表示で処理は続行されますが、意図した見た目にはなりません。Warning には直し方が付きます。近い候補(`did you mean 'Lambda'?`)や、その type を持つ provider(`set provider: gcp`)です。大文字小文字・空白・ハイフンの違いは無視されます(`API Gateway` でも `APIGateway` が見つかります)。

   **語彙にないサービスを描くとき**は、次の順に判断してください。(a) 最も近いサービスを使い、`label` に実際の名前を書く。(b) プレーン図形で描く。`style: {shape: rect}`(または `rounded`/`diamond`/`circle`)に名前をラベルとして付けます。provider に依存しないものに向いています。(c) ユーザーが公式アイコンを持っていれば、`--registry` ファイルで重ねる(形式は `zook schema --icon-registry`。PNG・JPEG・SVG のいずれも使えます)。(d) どれを選ぶかで図の意味が変わる場合は、ユーザーに確認する。アクター(`User`・`Admin`・`Client`・`Developer`)と provider に依存しないアイコン(`Server`・`Database`・`Internet`・`Mobile`・`OnPremises`・`SaaS`)は、どの `provider` でも使えます。

4. **YAML を書く、またはパターンを編集する。** 形式の正式な定義は JSON Schema(`zook schema`)、読み下した仕様は `zook guide yaml` にあります。近いパターンがない場合は、`zook init diagram.yaml` で小さな有効な雛形を書き出せます。リンクは見た目でも意味を表せます。非同期や待機系の経路には `line: dashed`、監視や論理的な関係には `line: dotted`、主要な流れを目立たせるには `color`/`width` を使います。パターンを流用する場合は、要件に合わない部分だけを書き換え、パターン全体の構造(コンテナの入れ子・レイアウト方針)はなるべく維持してください。

5. **検証する。** レンダリングの前に必ず実行してください。

   ```bash
   zook validate diagram.yaml --format json
   ```

   `{"status": "error", ...}` は構造的な破綻(スキーマ違反・id重複・リンク参照先不在など)を意味し、レンダリングしても意味のある出力になりません。`error` フィールドの内容を読んで修正し、`{"status": "ok"}` か `{"status": "warning"}` になるまで直してください。スキーマ違反は1件ずつ、該当箇所の正確なパス付きで報告されます(例: `$['elements'][0]['children'][1]['style']['labelPosition']: 'bottom' is not one of [...]`)。そのフィールドだけを直してください。YAML の構文エラーや重複キーは、行と列の番号付きで報告されます。「引用符なしの値が数値や真偽値として読まれた」という案内が付いた場合は、値を引用符で囲んでください(`"16:9"`、`"no"`)。メッセージの文章を解析する必要はありません。`errorCode` がエラーの種類を、`errorDetails` が個々の問題(スキーマ違反の YAML 内の位置 `pointer`、YAML エラーの `line`/`column`、存在しないリンク先の候補 `didYouMean` など)を示します。Warning も `details` に1件ずつ、`code`(`element-overlap`、`unknown-type`、`link-crosses-element` など)と関係する `elements`/`links` 付きで並びます。`warning` は描画上の軽微な問題(重なり・未知のアイコンなど)なので、そのまま進めても構いませんが、内容を確認し意図した配置になっているか判断してください。

   描画上の `warning` は、座標や接続辺を手計算で直そうとせず、まず `doctor` に解消させてください(ピクセル単位の調整はAIが最も苦手とする作業で、ツール側に任せるのが確実です)。`doctor` は4段階で直します。(1) 兄弟要素どうし・要素とコンテナ見出しの**重なり**(とコンテナからはみ出した子要素)を、要素を動かして解消。(2) リンク(矢印)の**経路衝突・見かけ上の直接接続(false edge aliasing)**を、接続辺(fromSide/toSide)を割り当てて解消。(3) 接続辺では迂回できない貫通は、経路上の**障害物要素(自動配置のもの)をどかして**解消。(4) 障害物が著者指定で動かせない場合は、**リンク側に経由点(waypoints)を挿入して迂回**させて解消。どの変更も、警告の重み付き合計が厳密に減るときだけ採用するので、doctor が図を悪化させることはなく、2回かけても追加の変更は起きません。まず `zook doctor diagram.yaml --format json` で提案を確認し(ドライラン)、問題なければ `zook doctor diagram.yaml --fix` で書き戻します。どの段階でも直せない衝突、および未知アイコン・スライドからのはみ出しや縮小フィットの警告は `remaining` として報告されるだけなので、`zook guide limitations`(英語。日本語版は `docs-site-ja/limitations.md`)を読み、YAMLの編集か draw.io での手直しで対応してください。

6. **生成する。**

   ```bash
   zook build diagram.yaml -o diagram.pptx
   ```

見た目を調整したい場合は、YAML を直接手直しするだけでなく、`zook export-drawio`/`sync` によるdraw.io連携(`docs-site-ja/drawio-sync.md`、`zook guide drawio`)という選択肢もあります。

## Mermaidのフローチャートから始まる依頼の場合

ユーザーがすでにMermaidの`flowchart`/`graph`記法で図を持っている(あるいはAI自身がMermaidで業務フローを組み立てた)場合は、上記のYAMLを新規に書く流れの代わりに、まず変換してください。

```bash
zook from-mermaid diagram.mmd -o diagram.yaml
```

変換後のYAMLはこの時点で検証済みなので、そのままステップ6の`build`に進めます。対応記法・既知の制約は`docs-site-ja/mermaid-import.md`を参照してください。`sequenceDiagram`など`flowchart`以外のMermaid図種別には対応していません。

## 主要リファレンス

| 知りたいこと | コマンド(どのディレクトリからでも可、英語) | このリポジトリ内 |
|---|---|---|
| YAML の全フィールド仕様 | `zook guide yaml`、`zook schema` | `docs/yaml-spec.md`(正本、英語)、`docs-site-ja/yaml-guide.md`(要点、日本語) |
| アイコン・コンテナの語彙とレジストリの仕組み | `zook icons list`、`zook schema --icon-registry` | `docs/icon-registry-and-vocabulary.md`(英語)、`docs-site-ja/icons.md`(日本語) |
| 要件別のアーキテクチャパターン | `zook patterns list`、`zook guide patterns` | `src/zook/data/patterns/`(英語) |
| 重なり・リンク経路 Warning の自動解消(`doctor`)の対象と使い方 | `zook guide usage`(doctor節) | `docs-site-ja/usage.md` |
| 2つの図の構造差分(`diff`)。変更前後の差分レビューに使う | `zook guide usage`(diff節) | `docs-site-ja/usage.md` |
| 既知の制約(自動レイアウトが解決しない重なり、GCP/Azureの制約など) | `zook guide limitations` | `docs-site-ja/limitations.md` |
| draw.io連携による継続的な図の管理 | `zook guide drawio` | `docs-site-ja/drawio-sync.md` |
| Mermaidフローチャートからの変換 | `zook guide mermaid` | `docs-site-ja/mermaid-import.md` |
| pptx生成の内部設計(座標系・コネクタなど) | — | `docs-site-ja/design-notes.md`、`docs/detailed-design-pptx.md`(英語) |

## 変更作業をするとき

- `docs/zook.schema.json`/`docs/icon-registry.schema.json` を変更したら、`src/zook/schemas/` 配下の同名ファイルにも同じ内容をコピーしてください(パッケージが読み込むのはこちらのコピーで、2つは常にbyte-identicalである前提です)。
- `docs/registry.<provider>.yaml` を変更したら、`src/zook/data/icons/<provider>/registry.<provider>.yaml` にも同様にコピーしてください。アイコンを追加した場合は、`python scripts/generate_placeholder_icons.py --missing-only` でそのプレースホルダー PNG を生成できます。
- `zook guide` は、`AGENTS.md`(英語版)・`docs/yaml-spec.md`・一部の `docs-site/` ページのコピーを `src/zook/data/guide/` から表示します。これらを編集したら `python scripts/sync_bundled_docs.py` を実行してください(コピーが古いと `tests/test_bundled_data.py` が失敗します)。
- 変更後は必ずテストを実行してください。

  ```bash
  .venv/bin/pytest tests/ -v
  ```

- `docs/example.yaml`・`docs/example-cloud-actors.yaml`・`src/zook/data/patterns/*.yaml` は「Warningゼロ」を保つ前提の回帰対象です。変更が影響しうる場合は `zook validate` で確認してください。

---

*注意: `docs/` 配下の一次資料(要件・詳細設計・YAML仕様・アイコンレジストリ仕様)は英語で統一されています。このファイル(AGENTS.ja.md)と `docs-site-ja/` のみが日本語です。*
