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

## 組み込みの語彙

多くの構成図が必要とする Tier-1 の中核サービスに、よく使う Tier-2 のサービス(WAF、CloudWatch、Secrets Manager、Step Functions、Kinesis、Internet/Transit Gateway など)を加えています。別名を含む最新の一覧は `zook icons list` で表示できます。

### AWS (77)

| カテゴリ | サービス |
|---|---|
| Compute | EC2, Lambda, ECS, EKS, Fargate, ECR, Batch, ElasticBeanstalk, AppRunner, Lightsail, AutoScaling |
| Storage | S3, EFS, EBS, Backup, StorageGateway |
| Database | RDS, Aurora, DynamoDB, ElastiCache, DocumentDB, Neptune |
| Networking | ELB, CloudFront, Route53, APIGateway, NATGateway, InternetGateway, NLB, TransitGateway, DirectConnect, SiteToSiteVPN, VPCEndpoint, GlobalAccelerator |
| Integration | SNS, SQS, EventBridge, StepFunctions, AppSync, MQ, SES |
| Security | IAM, Cognito, WAF, Shield, SecretsManager, KMS, ACM, GuardDuty, SecurityHub, NetworkFirewall |
| Management | CloudWatch, CloudTrail, SystemsManager, CloudFormation, XRay, CodePipeline |
| Analytics | Kinesis, Firehose, Redshift, Athena, Glue, EMR, OpenSearch, MSK |
| Machine Learning | SageMaker, Bedrock |
| General | User, Admin, Developer, Client |
| Generic | Server, Database, Internet, Mobile, OnPremises, SaaS |

コンテナの種別: `cloud`, `vpc`, `az`, `subnet`, `region`, `account`, `group`, `publicSubnet`, `privateSubnet`, `securityGroup`, `autoScalingGroup`, `corporateDataCenter`

### GCP (39)

| カテゴリ | サービス |
|---|---|
| Compute | ComputeEngine, CloudFunctions, GKE, CloudRun, AppEngine |
| Storage | CloudStorage, PersistentDisk |
| Database | CloudSQL, Firestore, BigQuery, Memorystore, Spanner, Bigtable, AlloyDB |
| Networking | CloudLoadBalancing, CloudCDN, CloudDNS, APIGateway, CloudNAT, CloudVPN, CloudInterconnect, CloudArmor |
| Integration | PubSub, Eventarc, CloudTasks, CloudScheduler, Workflows |
| Security | CloudIAM, IdentityPlatform, SecretManager, CloudKMS |
| Management | CloudLogging, CloudMonitoring, CloudBuild, ArtifactRegistry |
| Analytics | Dataflow, Dataproc, Composer |
| Machine Learning | VertexAI |

コンテナの種別: `cloud`, `vpc`, `project`

### Azure (40)

| カテゴリ | サービス |
|---|---|
| Compute | VirtualMachine, Functions, AKS, ContainerApps, AppService, ContainerRegistry |
| Storage | BlobStorage, ManagedDisk, StorageAccount |
| Database | SQLDatabase, CosmosDB, CacheForRedis, PostgreSQL, MySQL |
| Networking | LoadBalancer, FrontDoor, DNS, APIManagement, NATGateway, ApplicationGateway, Firewall, VPNGateway, ExpressRoute, TrafficManager, DDoSProtection, Bastion |
| Integration | ServiceBus, EventGrid, EventHubs, LogicApps |
| Security | EntraID, KeyVault, Sentinel |
| Management | Monitor, ApplicationInsights |
| Analytics | DataFactory, Synapse, Databricks |
| Machine Learning | OpenAI, MachineLearning |

コンテナの種別: `cloud`, `vpc`, `resourcegroup`, `subscription`

General(User/Admin/Developer/Client)カテゴリのアイコンはクラウドサービスではなく、「誰がこの構成にアクセスするか」を表す汎用アクターです。エンドユーザーや管理者をノードとして配置し、システムへのリンクを引くことで、構成図に人の視点を加えられます。Generic カテゴリ(Server、Database、Internet、Mobile、OnPremises、SaaS)は、オンプレミスのサーバー、インターネット、外部の SaaS など、クラウドの外にあるものを描くためのものです。どちらも AWS レジストリに定義されていますが、**どの provider でも解決される**ので、GCP や Azure の図でも使えます。

AWS のコンテナ種別には、`publicSubnet`/`privateSubnet`(公式資料どおり緑と青。従来の `subnet` はパブリックサブネットの見た目のまま)、`securityGroup`、`autoScalingGroup`、`corporateDataCenter` もあります。後述のフォールバックにより、GCP や Azure の図でも使えます。

```yaml
- kind: node
  id: user
  type: User
  label: "End User"
```

定義は `docs/registry.aws.yaml` / `docs/registry.gcp.yaml` / `docs/registry.azure.yaml` にあります(実装が読み込むコピーはそれぞれ `src/zook/data/icons/<provider>/registry.<provider>.yaml`)。

## 解決アルゴリズム

1. 要素の `provider`(ノードの既定は `aws`)で対象レジストリを選ぶ。
2. `type` をキーに、**エイリアス込みで、大文字小文字・空白・ハイフン・アンダースコア・ドットを無視して** lookup(例:`alb` → `ELB`、`ddb` → `DynamoDB`、`API Gateway` → `APIGateway`、`route-53` → `Route53`)。AWS レジストリの General/Generic のアイコンは、どの provider でも解決される。
3. ヒットすればアイコンファイルを解決。PNG と JPEG はそのまま使い、SVG はラスタライズする(cairosvg で表示サイズの4倍)。画像として読めないファイルは Warning を出し、プレースホルダーで描く。
4. ミスすれば **Warning を出してプレースホルダーアイコンで継続**(Fatal にはしない)。Warning には直し方が付く。近い type の候補(`did you mean 'Lambda'?`)、その type を持つ provider(`it is a gcp type - set provider: gcp on the node`)、近い候補がなければ確認先。

コンテナの `type`(`cloud`/`vpc`/`az`/`subnet` など)も同様に、要素の `provider` に対応する `groups` エントリを引きます。未知のコンテナ種別は素の枠で描き、最も近い種別を示す Warning を出します(意図して素の枠にしたい場合は `type: group` を使います)。**その provider 自身に定義がなければ AWS レジストリの `groups` にフォールバック**します(`vpc`/`az`/`subnet` のような一般的な概念を、GCP/Azure のレジストリで毎回再定義しなくて済むようにするためです)。`cloud`(クラウド境界)のようにプロバイダごとに固有の見た目にしたいものだけ、各プロバイダのレジストリで上書きします。

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

`--registry` オプションで、ユーザー独自のレジストリ YAML を組み込みレジストリの上に重ねられます。複数回指定すると、指定した順に重ねます。レジストリファイル自身の `provider` フィールドが、どのプロバイダに重ねるかを決めます。`aws`(既定)・`gcp`・`azure` のいずれか、またはノードが `provider: custom` で選ぶ独立した語彙なら `custom` です。

既存の type(またはコンテナ種別)を定義し直すと、**フィールド単位でマージ**されます。下の例の `vpc` の上書きは枠の色だけを変え、組み込みの既定ラベルと draw.io 図形はそのまま残ります。アイコンを上書きした場合もカテゴリと別名は残るので、`ELB` を上書きすれば `ALB` も新しいアイコンになります(`drawioShape` を書かずに `file` だけ差し替えた場合は、組み込みの draw.io 図形を外し、export-drawio でも差し替えた画像を使います)。type 自身の名前は、別のエントリの別名より常に優先されます。自分のエントリに `S3` のような別名を付けても Warning を出して無視するので、S3 のアイコンを変えたい場合は `S3` 自体を定義し直してください。

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

実際の公式アイコンに差し替える場合は、各 `registry.<provider>.yaml` の `file` パスに合わせて画像を配置するだけで済みます(コード変更不要)。`--registry` ファイルのエントリからそれらを指してもかまいません。SVG ファイル(Azure のアイコンはこの形式で配布されています)もそのまま使えます。ラスタライズする場合は、表示ピクセル数の **4倍**の解像度で PNG 化することを推奨します(理由は[内部設計メモ](design-notes.md#icon-raster-resolution)を参照)。
