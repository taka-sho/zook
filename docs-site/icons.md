# アイコン・レジストリ

サービスの `type`(`EC2`、`Lambda` など)は YAML スキーマ上 enum で固定されていません。**アイコンレジストリが語彙の唯一の真実源**です。これにより、新サービスの追加にコード改修は不要で、レジストリへの追記だけで済みます。

## 組み込み Tier-1 語彙(26サービス)

| カテゴリ | サービス |
|---|---|
| Compute | EC2, Lambda, ECS, EKS, Fargate |
| Storage | S3, EFS, EBS |
| Database | RDS, Aurora, DynamoDB, ElastiCache |
| Networking | ELB(ALB), CloudFront, Route53, APIGateway, NATGateway |
| Integration | SNS, SQS, EventBridge |
| Security | IAM, Cognito |
| General | User, Admin, Developer, Client(AWSサービスではなく、図に登場する人物・役割を表すアクター) |

General カテゴリのアイコンは AWS サービスではなく、「誰がこの構成にアクセスするか」を表す汎用アクターです。エンドユーザーや管理者をノードとして配置し、システムへのリンクを引くことで、構成図に人の視点を加えられます。

```yaml
- kind: node
  id: user
  type: User
  label: "End User"
```

定義は [`docs/registry.aws.yaml`](https://github.com/taka-sho/archtecture-diagram-generator/blob/main/docs/registry.aws.yaml) にあります(実装が読み込むコピーは `src/archdiagram/data/icons/aws/registry.aws.yaml`)。

## 解決アルゴリズム

1. 要素の `provider`(ノードの既定は `aws`)で対象レジストリを選ぶ。
2. `type` をキーに、**エイリアス込み・大小文字無視**で lookup(例:`alb` → `ELB`、`ddb` → `DynamoDB`、`AmazonEC2` → `EC2`)。
3. ヒットすればアイコンファイルを解決。
4. ミスすれば **Warning を出してプレースホルダーアイコンで継続**(Fatal にはしない)。

コンテナの `type`(`cloud`/`vpc`/`az`/`subnet` など)も同様に `groups` エントリを引き、枠の色・破線・ラベル位置を適用します。ヒットしなければ既定の枠スタイルになります。

### AWS Cloud 境界

`type: cloud` は、構成図全体がどこから AWS のクラウド境界なのかを示す、最も外側のコンテナです。枠の左上(または左下)には AWS Cloud を表す小さなバッジアイコンが自動で描画され、ラベルもその分だけインデントされます。

```yaml
- kind: container
  id: aws-cloud
  type: cloud
  label: "AWS Cloud"
  children:
    - kind: container
      id: vpc-main
      type: vpc
      label: "Production VPC"
      children: [...]
```

`groups` エントリの `icon` フィールドで、任意のコンテナ種別に同様の隅アイコンを設定できます。

## 独自アイコン・スタイルで上書きする

`--registry` オプションで、ユーザー独自のレジストリ YAML を組み込みレジストリの上に重ねられます。同じキーはユーザー側が優先されます。

```yaml
# my-registry.yaml
registryVersion: "1.0"
provider: aws
icons:
  MyInternalService:
    file: "my_internal_service.png"
    category: Custom
    aliases: [mis]
groups:
  vpc:
    borderColor: "#FF0000"   # 組み込みの vpc スタイルを上書き
```

```bash
archdiagram diagram.yaml -o diagram.pptx --registry my-registry.yaml
```

形式は [`icon-registry.schema.json`](https://github.com/taka-sho/archtecture-diagram-generator/blob/main/docs/icon-registry.schema.json) で検証されます。詳細仕様は [`docs/icon-registry-and-vocabulary.md`](https://github.com/taka-sho/archtecture-diagram-generator/blob/main/docs/icon-registry-and-vocabulary.md) を参照してください。

## アイコン画像について {: #icon-assets }

!!! warning "同梱アイコンは AWS 公式アイコンではありません"
    `src/archdiagram/data/icons/aws/` に同梱されている PNG は、`scripts/generate_placeholder_icons.py` で生成した**自作のプレースホルダー**(カテゴリ別配色 + サービス名の略称)です。ライセンス上の理由から AWS 公式アイコンはリポジトリに含めていません。

実際の AWS Architecture Icons に差し替える場合は、`registry.aws.yaml` の `file` パスに合わせて画像を配置するだけで済みます(コード変更不要)。ラスタライズする場合は、表示ピクセル数の **4倍**の解像度で PNG 化することを推奨します(理由は[内部設計メモ](design-notes.md#icon-raster-resolution)を参照)。
