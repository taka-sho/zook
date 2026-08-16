# Known Limitations (v1)

[🇯🇵 日本語版](/zook/ja/limitations/){ .md-button }

zook targets "a diagram that's good enough as a starting point for hand-editing in PowerPoint," not a fully automatic, polished layout. The known limitations as of v1 are as follows.

## Only Some Overlaps Are Auto-Avoided; the Rest Are Detection Only

When an element with no coordinates (auto-placed) overlaps an already-positioned sibling, only the auto-placed element is shifted (an explicitly-positioned element is never moved — it's treated as the author's intent). This auto-avoidance is a simple "push straight down" operation, so it can still fail to resolve an overlap in a complex layout. Every other overlap isn't auto-corrected — after generation, the computed coordinates are mechanically checked for the next overlap, and a Warning is emitted.

- Rectangle overlaps between sibling elements (parent/child pairs are excluded — except that a container's own label-text area is checked individually against its direct children)
- A link's (arrow's) path, or its own label, overlapping an unrelated element, another link's label, or a container's label (overlap with a container's label is never excluded, even for an ancestor container)

An element-vs-link-label overlap is checked for even when the link's path itself doesn't cross that element (i.e. even when only the label's displayed position overlaps). On the other hand, overlaps between elements that aren't siblings (different parent containers) aren't checked. Both are meant to be fixed up by hand in PowerPoint after generation.

Much of this can actually be auto-resolved with `zook doctor` (see the doctor section in [Usage](usage.md)). **Sibling-vs-sibling and element-vs-container-label overlaps** are resolved by nudging elements apart; **a link running through a node, and link-label collisions** are attempted by assigning connection sides (fromSide/toSide). A path that can't be routed around via connection sides is resolved by pushing the **obstacle (if auto-placed) perpendicular to the path**, and if the obstacle is author-positioned and can't be moved, by **inserting waypoints into the link to detour around it** (both only ever apply a change that doesn't make things worse). A case that still can't be fixed (e.g. the obstacle and both endpoints are all author-positioned, with the connection sides fixed too) is simply reported under `remaining`, requiring a manual fix after generation.

Setting `canvas.overlapMargin` extends detection beyond literal overlaps to "too close" as well (see the [YAML Input Guide](yaml-guide.md)).

## Apparent Direct Connections From Z-Route Aliasing Are Detection Only

When two separate links pass through the same connection point of a shared node (e.g. a container's top-center), their Z-route (`elbow`) segments can end up collinear and continuous, making two unrelated elements look directly connected (the typical case: node A→container X and container X→node B both happen to pick the same side of X's center point). zook mechanically detects this and emits a Warning. `zook doctor` attempts to break this alignment by assigning a connection side (fromSide/toSide) to one of the links (see the doctor section in [Usage](usage.md)). Depending on the endpoints' relative positions, though, a connection-side change alone can't always break it — in that case it's simply reported under `remaining`, so revisit the link's `from`/`to` or fix it up by hand in PowerPoint.

## Connection Sides Only Support a Top/Bottom Pair or a Left/Right Pair

When specifying connection sides via `link.fromSide`/`toSide`, only a `top`/`bottom` (vertical) pair or a `left`/`right` (horizontal) pair is supported. A cross-axis combination (e.g. `fromSide: bottom` + `toSide: left`) is a Fatal error. This is because `elbow`'s path generation (`bentConnector3`) is implemented assuming both ends exit/enter on the same axis — an arbitrary combination of sides (a single-bend L-shaped path) isn't supported.

When you need an arbitrary path (to detour around an obstacle, bend into an L-shape, etc.), make the intermediate points explicit with `link.waypoints` instead (see the [YAML Input Guide](yaml-guide.md)). It's drawn as a straight polyline through those points, and this axis-match rule doesn't apply there.

## Link-Path Detection Only Approximates `curved` as a Straight Line

Link-path overlap detection is based on the path as it's actually rendered. `style: straight` and `elbow` both match the actual rendered result exactly (`elbow` is the two-bend Z-shaped path drawn by python-pptx's `bentConnector3` preset), but `curved` (a bezier curve) doesn't reproduce the curve's actual bulge — it's a straight-line approximation, for reference only.

## Connectors Are Limited to Rectangular Shapes

Every connection target (icon image, container frame) is treated as a rectangle, since python-pptx's own connector implementation doesn't guarantee stable behavior for anything else.

## Connector Labels Don't Follow Movement

Due to a constraint in the OOXML schema, a link's label is placed as an independent textbox at its midpoint. If you move shapes significantly after generation, the label's position won't follow (see [Design Notes](design-notes.md#connector-labels) for details).

## Icons Are Placeholders

The bundled icon images (for AWS, GCP, and Azure alike) aren't each vendor's official icons — they're self-made placeholders. Real-world use is expected to swap in official assets, following the instructions in [Icon Registry](icons.md#icon-assets).

## Official draw.io Icon Display Is AWS-Only

`zook export-drawio` writes out AWS icons/containers already mapped to draw.io's official AWS4 shape library with the official look. GCP/Azure icons/containers currently have no such mapping and fall back to embedding zook's own placeholder PNGs (the mechanism itself is shared across all three providers, so this is extensible by adding a mapping table — see [Design Notes](design-notes.md) for details and `docs/detailed-design-pptx.md` §8.14 for the background).

## Multi-Cloud Vocabulary Is Tier-1 Only

The built-in AWS/GCP/Azure registries are each a Tier-1 vocabulary limited to the dozen-or-so to twenty-some services commonly used in practice (check with `zook icons list`). Anything beyond that is expected to be appended to your own registry via `--registry`. A container's `groups` (vpc/az/subnet, etc.) fall back to the AWS registry when undefined in a given provider's own registry, but things meant to look provider-specific — like the cloud boundary (`cloud`) — are defined individually in each provider's registry.

## Large-Scale Batch Generation Isn't a Target Use Case

Generating dozens or more slides in a single run isn't a target use case (1 YAML = 1 slide, with usage expected roughly weekly to a couple of times a month).
