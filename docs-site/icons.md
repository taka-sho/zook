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

## Built-in Tier-1 Vocabulary

### AWS (26)

| Category | Services |
|---|---|
| Compute | EC2, Lambda, ECS, EKS, Fargate |
| Storage | S3, EFS, EBS |
| Database | RDS, Aurora, DynamoDB, ElastiCache |
| Networking | ELB(ALB), CloudFront, Route53, APIGateway, NATGateway |
| Integration | SNS, SQS, EventBridge |
| Security | IAM, Cognito |
| General | User, Admin, Developer, Client (not cloud services — actors representing people/roles in a diagram, usable regardless of provider) |

### GCP (19)

| Category | Services |
|---|---|
| Compute | ComputeEngine, CloudFunctions, GKE, CloudRun |
| Storage | CloudStorage, PersistentDisk |
| Database | CloudSQL, Firestore, BigQuery, Memorystore |
| Networking | CloudLoadBalancing, CloudCDN, CloudDNS, APIGateway, CloudNAT |
| Integration | PubSub, Eventarc |
| Security | CloudIAM, IdentityPlatform |

### Azure (18)

| Category | Services |
|---|---|
| Compute | VirtualMachine, Functions, AKS, ContainerApps |
| Storage | BlobStorage, ManagedDisk |
| Database | SQLDatabase, CosmosDB, CacheForRedis |
| Networking | LoadBalancer, FrontDoor, DNS, APIManagement, NATGateway |
| Integration | ServiceBus, EventGrid |
| Security | EntraID, KeyVault |

The General (User/Admin/Developer/Client) category isn't cloud services — they're general-purpose actors representing "who's accessing this system." Placing an end user or administrator as a node and drawing a link to the system adds a human perspective to the diagram. They're only defined in the AWS registry, but since a node's default `provider` is `aws`, they're usable in any diagram as long as you don't set `provider` explicitly.

```yaml
- kind: node
  id: user
  type: User
  label: "End User"
```

Definitions live in `docs/registry.aws.yaml` / `docs/registry.gcp.yaml` / `docs/registry.azure.yaml` (the copies the implementation actually loads are `src/zook/data/icons/<provider>/registry.<provider>.yaml`).

## Resolution Algorithm

1. Pick the target registry based on the element's `provider` (a node's default is `aws`).
2. Look up `type` as the key, **alias-aware and case-insensitive** (e.g. `alb` → `ELB`, `ddb` → `DynamoDB`, `AmazonEC2` → `EC2`).
3. On a hit, resolve the icon file.
4. On a miss, **emit a Warning and continue with a placeholder icon** (never Fatal).

A container's `type` (`cloud`/`vpc`/`az`/`subnet`, etc.) works the same way, looking up the `groups` entry corresponding to the element's `provider`. **If not defined in that provider's own registry, it falls back to the AWS registry's `groups`** (so a general concept like `vpc`/`az`/`subnet` doesn't need to be redefined in the GCP/Azure registries every time). Only things meant to look provider-specific, like `cloud` (the cloud boundary), are overridden in each provider's own registry.

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

The `--registry` option lets you layer your own registry YAML on top of the built-in registries. The user side wins on a matching key. The registry file's own `provider` field decides which provider it layers onto (a value that's none of `aws`/`gcp`/`azure` — e.g. `custom` — is added as an independent new provider).

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

To swap in the actual official icons, just place the image files to match the `file` path in each `registry.<provider>.yaml` (no code changes needed). If rasterizing, we recommend rendering the PNG at **4x** the displayed pixel count (see [Design Notes](design-notes.md#icon-raster-resolution) for why).
