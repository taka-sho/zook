# Icon Registry

[🇯🇵 日本語版](/zook/ja/icons/){ .md-button }

A service's `type` (`EC2`, `ComputeEngine`, etc.) is not fixed by an enum in the YAML schema. **The icon registry is the single source of truth for vocabulary.** This means adding a new service requires no code changes — just appending to the registry.

## Multi-Cloud Support

`aws`/`gcp`/`azure` each have a built-in registry, and an element's `provider` field decides which one gets looked up (a node's default is `aws`). Multiple providers can coexist within a single diagram.

```yaml
- kind: node
  id: gce
  type: ComputeEngine
  provider: gcp
  label: "Web VM"
```

Check the actually-registered icon/container types with the `icons list` subcommand.

```bash
zook icons list                # all of aws/gcp/azure
zook icons list --provider gcp  # a specific provider only
```

## Built-in Vocabulary

A Tier-1 core of the services most diagrams need, plus a Tier-2 set of common additions (WAF, CloudWatch, Secrets Manager, Step Functions, Kinesis, Internet/Transit Gateway, ...). `zook icons list` prints the current list with every alias.

### AWS (77)

| Category | Services |
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

Container types: `cloud`, `vpc`, `az`, `subnet`, `region`, `account`, `group`, `publicSubnet`, `privateSubnet`, `securityGroup`, `autoScalingGroup`, `corporateDataCenter`

### GCP (39)

| Category | Services |
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

Container types: `cloud`, `vpc`, `project`

### Azure (40)

| Category | Services |
|---|---|
| Compute | VirtualMachine, Functions, AKS, ContainerApps, AppService, ContainerRegistry, Bastion |
| Storage | BlobStorage, ManagedDisk, StorageAccount |
| Database | SQLDatabase, CosmosDB, CacheForRedis, PostgreSQL, MySQL |
| Networking | LoadBalancer, FrontDoor, DNS, APIManagement, NATGateway, ApplicationGateway, Firewall, VPNGateway, ExpressRoute, TrafficManager, DDoSProtection |
| Integration | ServiceBus, EventGrid, EventHubs, LogicApps |
| Security | EntraID, KeyVault, Sentinel |
| Management | Monitor, ApplicationInsights |
| Analytics | DataFactory, Synapse, Databricks |
| Machine Learning | OpenAI, MachineLearning |

Container types: `cloud`, `vpc`, `resourcegroup`, `subscription`

The General (User/Admin/Developer/Client) category isn't cloud services — they're general-purpose actors representing "who's accessing this system." Placing an end user or administrator as a node and drawing a link to the system adds a human perspective to the diagram. The Generic category (Server, Database, Internet, Mobile, OnPremises, SaaS) is for things outside any cloud: an on-premises server, the public internet, a third-party SaaS. Both are defined in the AWS registry but **resolve for every provider**, so they work in a GCP or Azure diagram too.

The AWS container types also cover `publicSubnet`/`privateSubnet` (green/blue, as in the official deck — plain `subnet` keeps the public-subnet look), `securityGroup`, `autoScalingGroup` and `corporateDataCenter`. GCP and Azure diagrams can use them as well, through the fallback described below.

```yaml
- kind: node
  id: user
  type: User
  label: "End User"
```

Definitions live in `docs/registry.aws.yaml` / `docs/registry.gcp.yaml` / `docs/registry.azure.yaml` (the copies the implementation actually loads are `src/zook/data/icons/<provider>/registry.<provider>.yaml`).

## Resolution Algorithm

1. Pick the target registry based on the element's `provider` (a node's default is `aws`).
2. Look up `type` as the key, **alias-aware, ignoring case, spaces, hyphens, underscores and dots** (e.g. `alb` → `ELB`, `ddb` → `DynamoDB`, `API Gateway` → `APIGateway`, `route-53` → `Route53`). A General/Generic icon from the AWS registry resolves under any provider.
3. On a hit, resolve the icon file. PNG and JPEG are used as they are; an SVG is rasterized (cairosvg, 4x the display size). A file that can't be read as an image is a Warning, drawn with the placeholder.
4. On a miss, **emit a Warning and continue with a placeholder icon** (never Fatal). The Warning says how to fix it: the closest types (`did you mean 'Lambda'?`), or the provider that has this one (`it is a gcp type - set provider: gcp on the node`), or where to look when nothing is close.

A container's `type` (`cloud`/`vpc`/`az`/`subnet`, etc.) works the same way, looking up the `groups` entry corresponding to the element's `provider`; an unknown container type is drawn as a plain frame, with a Warning suggesting the closest type (`type: group` is the deliberately plain frame). **If not defined in that provider's own registry, it falls back to the AWS registry's `groups`** (so a general concept like `vpc`/`az`/`subnet` doesn't need to be redefined in the GCP/Azure registries every time). Only things meant to look provider-specific, like `cloud` (the cloud boundary), are overridden in each provider's own registry.

### Cloud Boundaries

`type: cloud` is the outermost container, marking where the whole diagram falls within that cloud's boundary. A brand-colored badge icon for the provider is automatically drawn at the top-left (or bottom-left) of the frame, with the label indented to make room (AWS Cloud is dark navy, Google Cloud is blue, Microsoft Azure is a blue tone).

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

A `groups` entry's `icon` field can set the same kind of corner icon on any container type.

## Overriding With Your Own Icons/Styles

The `--registry` option lets you layer your own registry YAML on top of the built-in registries; repeat it to layer several files, applied in order. The registry file's own `provider` field decides which provider it layers onto: `aws` (the default), `gcp` or `azure`, or `custom` for an independent vocabulary that nodes select with `provider: custom`.

Redefining an existing type (or container type) **merges field by field**: the `vpc` override below only changes the frame colour, keeping the built-in label and draw.io shape, and an icon override keeps the entry's category and aliases — so `ALB` follows an overridden `ELB` to its new icon. (A new `file` without a `drawioShape` drops the built-in draw.io shape, so export-drawio shows your image.) A type's own name always wins over another entry's alias: an alias like `S3` on your own entry is ignored with a Warning — redefine `S3` itself to change its icon.

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
    borderColor: "#FF0000"   # overrides the built-in vpc style
```

```bash
zook build diagram.yaml -o diagram.pptx --registry my-registry.yaml
```

The format is validated against [`icon-registry.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/icon-registry.schema.json). See [`docs/icon-registry-and-vocabulary.md`](https://github.com/taka-sho/zook/blob/main/docs/icon-registry-and-vocabulary.md) for the detailed spec.

## Icon Display in draw.io Integration

When exporting via `zook export-drawio` (see [draw.io Integration](drawio-sync.md)), each registry entry can optionally set a `drawioShape` field. If set, it's exported as an official draw.io shape (AWS4, etc.); if not, this tool's own PNG icon is embedded as-is. Currently only the built-in AWS registry has `drawioShape` set (GCP/Azure are unset → PNG fallback).

## About the Icon Images {: #icon-assets }

!!! warning "The bundled icons are not the official vendor icons"
    The PNGs bundled under `src/zook/data/icons/<provider>/` are **self-made placeholders** generated by `scripts/generate_placeholder_icons.py` (category-based colors + a service-name abbreviation). Official AWS/GCP/Azure icons aren't included in the repository, for licensing reasons.

To swap in the actual official icons, just place the image files to match the `file` path in each `registry.<provider>.yaml` (no code changes needed), or point a `--registry` file's entries at them — SVG files (the form Azure distributes its icons in) work as they are. If rasterizing, we recommend rendering the PNG at **4x** the displayed pixel count (see [Design Notes](design-notes.md#icon-raster-resolution) for why).
