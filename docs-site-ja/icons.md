# アイコン・レジストリ

[🇬🇧 English](/zook/icons/){ .md-button }

サービスの `type`(`EC2`、`ComputeEngine` など)は YAML スキーマ上 enum で固定されていません。**アイコンレジストリが語彙の唯一の真実源**です。これにより、新サービスの追加にコード改修は不要で、レジストリへの追記だけで済みます。

## マルチクラウド対応

`aws`/`gcp`/`azure` それぞれに組み込みレジストリがあり、要素の `provider` フィールドでどのレジストリを引くかが決まります(ノードの既定は `aws`)。1つの図の中で複数のプロバイダを混在させることもできます。

```yaml
- kind: node
  id: gce
  type: ComputeEngine
  provider: gcp
  label: "Web VM"
```

実際に登録されているアイコン・コンテナ種別は `icons list` サブコマンドで確認できます。

```bash
zook icons list                # aws/gcp/azure すべて
zook icons list --provider gcp  # 特定プロバイダのみ
```

## 組み込み Tier-1 語彙

### AWS(26)

| カテゴリ | サービス |
|---|---|
| Compute | EC2, Lambda, ECS, EKS, Fargate |
| Storage | S3, EFS, EBS |
| Database | RDS, Aurora, DynamoDB, ElastiCache |
| Networking | ELB(ALB), CloudFront, Route53, APIGateway, NATGateway |
| Integration | SNS, SQS, EventBridge |
| Security | IAM, Cognito |
| General | User, Admin, Developer, Client(クラウドサービスではなく、図に登場する人物・役割を表すアクター。プロバイダを問わず使える) |

### GCP(19)

| カテゴリ | サービス |
|---|---|
| Compute | ComputeEngine, CloudFunctions, GKE, CloudRun |
| Storage | CloudStorage, PersistentDisk |
| Database | CloudSQL, Firestore, BigQuery, Memorystore |
| Networking | CloudLoadBalancing, CloudCDN, CloudDNS, APIGateway, CloudNAT |
| Integration | PubSub, Eventarc |
| Security | CloudIAM, IdentityPlatform |

### Azure(18)

| カテゴリ | サービス |
|---|---|
| Compute | VirtualMachine, Functions, AKS, ContainerApps |
| Storage | BlobStorage, ManagedDisk |
| Database | SQLDatabase, CosmosDB, CacheForRedis |
| Networking | LoadBalancer, FrontDoor, DNS, APIManagement, NATGateway |
| Integration | ServiceBus, EventGrid |
| Security | EntraID, KeyVault |

General(User/Admin/Developer/Client)カテゴリのアイコンはクラウドサービスではなく、「誰がこの構成にアクセスするか」を表す汎用アクターです。エンドユーザーや管理者をノードとして配置し、システムへのリンクを引くことで、構成図に人の視点を加えられます。AWS レジストリにのみ定義されていますが、`provider` を明示しなければどの図でも(既定 `aws` なので)使えます。

```yaml
- kind: node
  id: user
  type: User
  label: "End User"
```

定義は `docs/registry.aws.yaml` / `docs/registry.gcp.yaml` / `docs/registry.azure.yaml` にあります(実装が読み込むコピーはそれぞれ `src/zook/data/icons/<provider>/registry.<provider>.yaml`)。

## 解決アルゴリズム

1. 要素の `provider`(ノードの既定は `aws`)で対象レジストリを選ぶ。
2. `type` をキーに、**エイリアス込み・大小文字無視**で lookup(例:`alb` → `ELB`、`ddb` → `DynamoDB`、`AmazonEC2` → `EC2`)。
3. ヒットすればアイコンファイルを解決。
4. ミスすれば **Warning を出してプレースホルダーアイコンで継続**(Fatal にはしない)。

コンテナの `type`(`cloud`/`vpc`/`az`/`subnet` など)も同様に、要素の `provider` に対応する `groups` エントリを引きます。**その provider 自身に定義がなければ AWS レジストリの `groups` にフォールバック**します(`vpc`/`az`/`subnet` のような一般的な概念を、GCP/Azure のレジストリで毎回再定義しなくて済むようにするためです)。`cloud`(クラウド境界)のようにプロバイダごとに固有の見た目にしたいものだけ、各プロバイダのレジストリで上書きします。

### クラウド境界

`type: cloud` は、構成図全体がどこからそのクラウドの境界なのかを示す、最も外側のコンテナです。枠の左上(または左下)にはプロバイダごとのブランドカラーのバッジアイコンが自動で描画され、ラベルもその分だけインデントされます(AWS Cloud は濃紺、Google Cloud は青、Microsoft Azure は青系)。

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

`--registry` オプションで、ユーザー独自のレジストリ YAML を組み込みレジストリの上に重ねられます。同じキーはユーザー側が優先されます。レジストリファイル自身の `provider` フィールドが、どのプロバイダに重ねるかを決めます(`aws`/`gcp`/`azure` のいずれでもない値、例えば `custom` を指定すると、独立した新しいプロバイダとして追加されます)。

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
zook build diagram.yaml -o diagram.pptx --registry my-registry.yaml
```

形式は [`icon-registry.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/icon-registry.schema.json) で検証されます。詳細仕様は [`docs/icon-registry-and-vocabulary.md`](https://github.com/taka-sho/zook/blob/main/docs/icon-registry-and-vocabulary.md) を参照してください。

## draw.io連携でのアイコン表示

`zook export-drawio`(詳細は[draw.io連携](drawio-sync.md))で書き出す際、レジストリの各エントリに任意で `drawioShape` フィールドを設定できます。設定されていれば draw.io 公式のシェイプ(AWS4等)として書き出され、未設定ならこのツール自身のPNGアイコンをそのまま埋め込みます。現時点では組み込みのAWSレジストリのみ `drawioShape` を設定済みです(GCP/Azureは未設定 → PNGフォールバック)。

## アイコン画像について {: #icon-assets }

!!! warning "同梱アイコンは各社の公式アイコンではありません"
    `src/zook/data/icons/<provider>/` に同梱されている PNG は、`scripts/generate_placeholder_icons.py` で生成した**自作のプレースホルダー**(カテゴリ別配色 + サービス名の略称)です。ライセンス上の理由から AWS/GCP/Azure の公式アイコンはリポジトリに含めていません。

実際の公式アイコンに差し替える場合は、各 `registry.<provider>.yaml` の `file` パスに合わせて画像を配置するだけで済みます(コード変更不要)。ラスタライズする場合は、表示ピクセル数の **4倍**の解像度で PNG 化することを推奨します(理由は[内部設計メモ](design-notes.md#icon-raster-resolution)を参照)。
