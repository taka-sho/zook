# サービス語彙 & アイコンレジストリ仕様（v1.0）

**バージョン:** 1.0
**作成日:** 2026-07-25
**対象:** 要求仕様書 §7.4、YAML入力仕様書 §10 の確定
**関連ファイル:** `icon-registry.schema.json`, `registry.aws.yaml`

---

## 1. 基本方針：型は enum で固定しない

サービスの `type` を JSON Schema の enum で縛ると、サービス追加のたびにスキーマ改修が必要になり、拡張性(要求仕様書 R-IC-04)を損なう。そこで：

- **YAML スキーマ上、`type` は自由文字列**のまま(既に確定済み)。
- **語彙の実体はレジストリが唯一の真実源**とする。`type` → アイコンの対応はレジストリで定義。
- 未知 `type` は Fatal にせず、Warning + プレースホルダで継続(エラーポリシー §9)。

これにより「新サービス対応 = レジストリに1行 + アイコン追加」だけで済む。

## 2. サービス語彙（Tier 分け）

初期からレジストリに載せる語彙を Tier で分ける。

### Tier 1（v1 同梱：26種）

実際の構成図で頻出する基礎サービスを網羅する。

| カテゴリ | サービス |
|---|---|
| Compute | EC2, Lambda, ECS, EKS, Fargate |
| Storage | S3, EFS, EBS |
| Database | RDS, Aurora, DynamoDB, ElastiCache |
| Networking | ELB(ALB), CloudFront, Route53, APIGateway, NATGateway |
| Integration | SNS, SQS, EventBridge |
| Security | IAM, Cognito |
| General | User, Admin, Developer, Client(AWSサービスではなく、図に登場する人物・役割を表すアクター) |

- 当初要望の EC2/Lambda/RDS/S3 を含み、そこに「図でよく一緒に描かれる」ものを加えた実用最小セット。
- General カテゴリは AWS サービスではなく、構成図に頻出する「誰がアクセスするか」を表すアクター(エンドユーザー・管理者・開発者・クライアント端末)。同じレジストリ機構(`icons` エントリ)にそのまま乗る。

### Tier 2（オンデマンド追加）

上記以外の AWS サービス(公式アイコンは300超)。必要になった時点でレジストリに追記する。スキーマ改修は不要。

## 3. アイコンレジストリの形式

プロバイダごとに1つのレジストリファイル(例：`icons/aws/registry.aws.yaml`)。`icon-registry.schema.json` で厳密化済み。

### 3.1 トップレベル

| フィールド | 必須 | 説明 |
|---|---|---|
| `registryVersion` | ○ | 固定 "1.0" |
| `provider` | ○ | `aws`/`gcp`/`azure`/`custom` |
| `iconSet` | | 由来・バージョン記録(AWSは四半期更新のため明記) |
| `basePath` | | アイコンファイルのあるディレクトリ |
| `defaults` | | 既定サイズ・既定拡張子 |
| `icons` | ○ | ノード(サービス/リソース)の定義 |
| `groups` | | コンテナ(枠)のスタイル定義 |

### 3.2 icons エントリ（ノード）

キー = YAML の `type`。値は：

- `file`（必須）：`basePath` からの相対パス
- `category`：Compute/Storage 等
- `kind`：`service` | `resource`（AWS の2区分に対応）
- `label`：要素側でラベル省略時の既定表示名
- `aliases`：別名リスト(大小文字無視でマッチ)
- `size`：このアイコン固有のサイズ上書き

### 3.3 groups エントリ（コンテナ枠）

キー = コンテナの `type`（cloud/vpc/az/subnet 等）。枠線色・塗り・破線・ラベル位置・任意の隅アイコンを定義。色は妥当な既定値を入れてあるが、**公式デックの配色に合わせて最終調整する**前提。

- `cloud`(AWS Cloud 境界)は最も外側の枠として追加済み。`icon` に隅アイコン(`General/aws-cloud-badge.png`)を指定しており、実装側はラベル位置が `top-left`/`bottom-left` のとき、その隅にアイコンを描画しラベルをアイコン分だけ右にずらす(詳細は `detailed-design-pptx.md`)。「どこから AWS Cloud か」を一目で分かるようにする狙い。

## 4. 解決アルゴリズム

ノードのアイコン解決手順：

1. 要素の `provider`（既定 aws）で対象レジストリを選ぶ。
2. `type` をキーに、**エイリアス込み・大小文字無視**で lookup。
3. ヒット → `basePath` + `file` を実ファイルに解決。
4. ミス → Warning を出し、プレースホルダアイコンで継続。

コンテナは同様に `groups` を引き、ヒットすれば枠スタイルを適用、なければ既定枠。

- 検証済み：Tier 1 の 22 エントリ + 別名で lookup キー 35 個、**衝突なし**。`alb`→ELB、`AmazonEC2`→EC2、`ddb`→DynamoDB 等が解決可能。

## 5. 上書き（オーバーライド）機構

- 組み込みレジストリの上に、**ユーザーレジストリを重ねられる**。
- 解決順：ユーザー定義 > 組み込み。同一キーはユーザー側が勝つ。
- カスタムアイコンは `provider: custom` + `icons/custom/` に置いて追加。
- これで「社内独自アイコン」「未対応サービスの暫定アイコン」に対応。

## 6. バージョニング（AWS 四半期更新への追従）

- AWS 公式アイコンは Q1(1月末)/Q2(4月末)/Q3(7月末)に更新される。
- `iconSet` に採用リリースを明記し、アイコン一式ごと差し替え可能にする(vendoring)。
- レジストリのキー(=YAML の `type`)は安定させ、更新時はファイル実体だけ入れ替える運用を基本とする。

## 7. 他プロバイダへの拡張

- `registry.gcp.yaml` / `registry.azure.yaml` を同形式で追加するだけ。
- スキーマ(`icon-registry.schema.json`)は共通。`provider` 値と `icons`/`groups` の中身が変わるだけ。
- 図 YAML 側はノードに `provider: gcp` を付けるだけで切り替わる。

## 8. 確定状況 & 申し送り

- レジストリ形式は JSON Schema 化・検証済み。サンプル `registry.aws.yaml` も適合確認済み。
- **アイコン実ファイル本体は未同梱**。Claude Code 側で公式アセットを取得し、`file` パスに合わせて配置(または配置に合わせて `file` を調整)すること。
- SVG 原本は PNG へ変換して配置(設計メモ §8.1)。`defaults.ext` は png。
- 解決は「エイリアス込み・大小文字無視」で実装すること(§4)。
- 色・カテゴリ・kind は公式デックに合わせて必要に応じ調整可。

---

*本仕様により、要求仕様書 §7.4 とアイコン関連の未決事項はすべて確定。残るアイコン実ファイルの調達・配置は実装フェーズの作業。*
