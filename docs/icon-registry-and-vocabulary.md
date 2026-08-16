# Service Vocabulary & Icon Registry Specification (v1.0)

**Version:** 1.0
**Date:** 2026-07-25
**Scope:** Settles requirements spec §7.4 and yaml-spec §10
**Related files:** `icon-registry.schema.json`, `registry.aws.yaml`, `registry.gcp.yaml`, `registry.azure.yaml`

---

## 1. Basic Policy: Types Are Not Fixed as an Enum

Constraining a service's `type` with a JSON Schema enum would require a schema change every time a service is added, undermining extensibility (requirements spec R-IC-04). So instead:

- **In the YAML schema, `type` remains a free-form string** (already settled).
- **The registry is the single source of truth for vocabulary.** The `type` → icon mapping is defined in the registry.
- An unknown `type` is not Fatal — it continues with a Warning + placeholder (error policy §9).

This means "supporting a new service" is just "one line in the registry + an icon file."

## 2. Service Vocabulary (Tiers)

The vocabulary shipped in the registry from the start is split into tiers.

### Tier 1 (bundled in v1: 26 services)

Covers the foundational services that show up constantly in real-world diagrams.

| Category | Services |
|---|---|
| Compute | EC2, Lambda, ECS, EKS, Fargate |
| Storage | S3, EFS, EBS |
| Database | RDS, Aurora, DynamoDB, ElastiCache |
| Networking | ELB(ALB), CloudFront, Route53, APIGateway, NATGateway |
| Integration | SNS, SQS, EventBridge |
| Security | IAM, Cognito |
| General | User, Admin, Developer, Client (not AWS services — actors representing people/roles that appear in a diagram) |

- A practical minimal set that covers the originally requested EC2/Lambda/RDS/S3, plus the services that commonly get drawn alongside them.
- The General category isn't AWS services — it's actors that commonly appear in architecture diagrams to represent "who's accessing this" (end user, administrator, developer, client device). They plug directly into the same registry mechanism (`icons` entries).

### Tier 2 (added on demand)

Every other AWS service (the official icon set has 300+). Added to the registry as needed. No schema change required.

## 3. Icon Registry Format

One registry file per provider (e.g. `icons/aws/registry.aws.yaml`), formalized via `icon-registry.schema.json`.

### 3.1 Top Level

| Field | Required | Description |
|---|---|---|
| `registryVersion` | Yes | fixed "1.0" |
| `provider` | Yes | `aws`/`gcp`/`azure`/`custom` |
| `iconSet` | | provenance/version record (AWS updates quarterly, so this is worth recording explicitly) |
| `basePath` | | directory containing the icon files |
| `defaults` | | default size / default extension |
| `icons` | Yes | node (service/resource) definitions |
| `groups` | | container (frame) style definitions |

### 3.2 icons Entries (Nodes)

Key = the YAML's `type`. Value:

- `file` (required): path relative to `basePath`
- `category`: Compute/Storage etc.
- `kind`: `service` | `resource` (matches AWS's two-way distinction)
- `label`: default display name used when an element omits its own label
- `aliases`: list of alternate names (matched case-insensitively)
- `size`: size override specific to this icon
- `drawioShape`: the draw.io official-shape style string used by `zook export-drawio` (see `detailed-design-pptx.md` §8.14). If omitted, the PNG (`file`) is embedded as-is

### 3.3 groups Entries (Container Frames)

Key = the container's `type` (cloud/vpc/az/subnet, etc.). Defines border color, fill, dashing, label position, and an optional corner icon. Reasonable defaults are filled in, but these are expected to be **tuned to match the official deck's color scheme** as a final pass. `drawioShape` (optional) similarly lets you specify an official container shape for export-drawio.

- `cloud` (the AWS Cloud boundary) is included as the outermost frame. Its `icon` specifies a corner icon (`General/aws-cloud-badge.png`); when the label position is `top-left`/`bottom-left`, the implementation draws the icon in that corner and shifts the label right to make room for it (see `detailed-design-pptx.md` for details). The goal is to make "where the AWS Cloud boundary starts" visible at a glance.

## 4. Resolution Algorithm

Steps for resolving a node's icon:

1. Pick the target registry based on the element's `provider` (default `aws`).
2. Look up `type` as the key, **alias-aware and case-insensitive**.
3. Hit → resolve `basePath` + `file` to an actual file.
4. Miss → emit a Warning and continue with a placeholder icon.

Containers work the same way, looking up `groups`. **If not defined in that provider's own registry, it falls back to the AWS registry's `groups`** (so a common concept like vpc/az/subnet doesn't need to be redefined for GCP/Azure every time). Only things meant to look provider-specific, like `cloud`, are defined individually in each provider's registry. If there's no hit at all, a default frame is used.

- Verified (AWS registry): Tier 1's 26 entries plus aliases give 46 lookup keys, **no collisions**. `alb`→ELB, `AmazonEC2`→EC2, `ddb`→DynamoDB and similar all resolve correctly.
- Verified (implementation phase): after the GCP/Azure registries were added, unit tests confirm `MultiRegistry` correctly dispatches to the right registry based on an element's `provider`, and that the AWS fallback for `groups` works as intended (`tests/test_registry.py`).

## 5. Override Mechanism

- A **user registry can be layered on top of** the built-in registries.
- Resolution order: user-defined > built-in. The user side wins on a matching key.
- Custom icons are added via `provider: custom` plus files under `icons/custom/`.
- This covers "internal company-specific icons" and "stopgap icons for services not yet supported."

## 6. Versioning (Keeping Up With AWS's Quarterly Updates)

- Official AWS icons are updated in Q1 (late January), Q2 (late April), and Q3 (late July).
- `iconSet` records the adopted release, so the whole icon set can be swapped out (vendoring).
- The registry's keys (= the YAML's `type` values) are kept stable; updates generally just swap out the underlying files.

## 7. Extending to Other Providers (settled during implementation)

- `registry.gcp.yaml` / `registry.azure.yaml` were added in the same format (Tier-1 with 19 GCP services and 18 Azure services, plus `cloud`/`vpc`/provider-specific account-concept groups).
- The schema (`icon-registry.schema.json`) is shared — only the `provider` value and the contents of `icons`/`groups` differ.
- On the diagram-YAML side, switching providers is as simple as adding `provider: gcp` to a node. Multiple providers can coexist within a single diagram, since `provider` is set per element.
- Resolution is handled by `MultiRegistry` (`src/zook/registry.py`). It always loads `aws`/`gcp`/`azure`, and a user registry passed via `--registry` is layered onto whichever `provider` **that file itself declares** (declaring an unknown value, e.g. `custom`, adds it as an independent new provider).
- `zook icons list [--provider <name>]` lists the vocabulary that's actually resolvable.

## 8. Status & Handoff

- The registry format has been formalized as JSON Schema and validated. The sample `registry.aws.yaml` has also been confirmed to conform.
- **The actual icon files are not bundled.** The implementation side (Claude Code) needs to source the official assets and place them per the `file` paths (or adjust `file` to match the placement).
- Original SVGs are converted to PNG before being placed (design memo §8.1). `defaults.ext` is png.
- Resolution must be implemented as "alias-aware and case-insensitive" (§4).
- Color/category/kind can be adjusted as needed to match the official deck.

---

*This spec settles every open item from requirements spec §7.4 and the icon-related questions. What remains is sourcing and placing the actual icon files, which is implementation-phase work.*
