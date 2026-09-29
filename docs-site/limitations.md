# Known Limitations (v1)

[🇯🇵 日本語版](/zook/ja/limitations/){ .md-button }

zook targets "a diagram that's good enough as a starting point for hand-editing in PowerPoint," not a fully automatic, polished layout. The known limitations as of v1 are as follows.

## Only Some Overlaps Are Auto-Avoided; the Rest Are Detection Only

When an element with no coordinates (auto-placed) overlaps an already-positioned sibling, only the auto-placed element is shifted (an explicitly-positioned element is never moved — it's treated as the author's intent). This auto-avoidance is a simple "push straight down" operation, so it can still fail to resolve an overlap in a complex layout. Every other overlap isn't auto-corrected — after generation, the computed coordinates are mechanically checked for the next overlap, and a Warning is emitted.

- Rectangle overlaps between sibling elements (parent/child pairs are excluded — except that a container's own label-text area is checked individually against its direct children)
- A link's (arrow's) path, or its own label, overlapping an unrelated element, another link's label, or a container's label (overlap with a container's label is never excluded, even for an ancestor container)

An element-vs-link-label overlap is checked for even when the link's path itself doesn't cross that element (i.e. even when only the label's displayed position overlaps). On the other hand, overlaps between elements that aren't siblings (different parent containers) aren't checked. Both are meant to be fixed up by hand in PowerPoint after generation.

Much of this can actually be auto-resolved with `zook doctor` (see the doctor section in [Usage](usage.md)). **Sibling-vs-sibling and element-vs-container-label overlaps, and children spilling out of their container,** are resolved by moving elements (inside their container); **a link running through a node or back through its own endpoint, and link-label collisions** are attempted by assigning connection sides (fromSide/toSide). A path that can't be routed around via connection sides is resolved by pushing the **obstacle (if auto-placed) perpendicular to the path**, and if the obstacle is author-positioned and can't be moved, by **inserting right-angled waypoints into the link to detour around it** (every change is kept only if a weighted total of the Warnings strictly drops). A case that still can't be fixed (e.g. the obstacle and both endpoints are all author-positioned, with the connection sides fixed too) is simply reported under `remaining`, requiring a manual fix after generation.

Setting `canvas.overlapMargin` extends detection beyond literal overlaps to "too close" as well (see the [YAML Input Guide](yaml-guide.md)).

## Link-Aware Layout Is Opt-In and Simple

By default, auto-layout places children in the order they're written; `layout.order: flow` (or `zook doctor`, which sets it where it helps) arranges them along their links instead. The flow layout is a simple layered one — ranks by longest path, a few ordering sweeps, no reserved lanes — so a link that skips several steps can still run through an element in between, and links between two ranks share one bend line, which can read as a direct connection. Automatic connection sides route round an element when a clean U route exists; what remains is reported as a Warning for `doctor` (connection sides, obstacle moves, waypoint detours) or a hand fix.

## Label Sizes Are Estimated, Not Measured With a Font

zook sizes every label from its text without a font file (the renderer is PowerPoint, not zook): full-width characters (Japanese, Chinese, Korean) count as 1 em, Latin letters as roughly half that, with wider/narrower classes for the letters that differ most. Symbols that Japanese fonts draw full width — arrows, circled numbers (①), dashes, ellipses — count as 1 em too. A word too long for the line starts a new line before it is broken, as PowerPoint does. The estimate errs slightly wide, so a label reserved one line fits on one line in the default fonts. A font much wider than Calibri/Meiryo, or unusual glyphs, can still wrap where zook didn't expect — the preview (`zook preview`) shows zook's own line breaks.

## Shrink-to-Fit Scales the Whole Slide

With the default `canvas.fit: shrink`, a diagram that doesn't fit the slide is scaled down uniformly — icons, text and spacing alike — rather than re-laid out. Line widths and arrowheads keep their size, so a heavily shrunk diagram looks bolder. A milder shrink is silent, even when it was caused by an element explicitly positioned past the slide's edge. Below 70% this is reported as a Warning, naming any such element: reorganise (split the diagram, tighten `gap`/`padding`, fix the stray coordinate) rather than shipping unreadably small text. `fit: none` keeps the old behaviour (draw as laid out, warn about what falls outside).

## Apparent Direct Connections From Z-Route Aliasing Are Detection Only

When two separate links pass through the same connection point of a shared node (e.g. a container's top-center), their Z-route (`elbow`) segments can end up collinear and continuous, making two unrelated elements look directly connected (the typical case: node A→container X and container X→node B both happen to pick the same side of X's center point). zook mechanically detects this and emits a Warning. Links that merely share a trunk at a common endpoint — several leaving the same node from the same point (a fan-out), or arriving at the same point (a fan-in) — read as a branch or merge and aren't flagged. `zook doctor` attempts to break this alignment by assigning a connection side (fromSide/toSide) to one of the links (see the doctor section in [Usage](usage.md)). Depending on the endpoints' relative positions, though, a connection-side change alone can't always break it — in that case it's simply reported under `remaining`, so revisit the link's `from`/`to` or fix it up by hand in PowerPoint.

## Connection Sides Only Support a Top/Bottom Pair or a Left/Right Pair

When specifying connection sides via `link.fromSide`/`toSide`, only a `top`/`bottom` (vertical) pair or a `left`/`right` (horizontal) pair is supported. A cross-axis combination (e.g. `fromSide: bottom` + `toSide: left`) is a Fatal error. This is because `elbow`'s path generation (`bentConnector3`) is implemented assuming both ends exit/enter on the same axis — an arbitrary combination of sides (a single-bend L-shaped path) isn't supported.

When you need an arbitrary path (to detour around an obstacle, bend into an L-shape, etc.), make the intermediate points explicit with `link.waypoints` instead (see the [YAML Input Guide](yaml-guide.md)). It's drawn as a straight polyline through those points, and this axis-match rule doesn't apply there.

## Link-Path Detection Only Approximates `curved` as a Straight Line

Link-path overlap detection is based on the path as it's actually rendered. `style: straight` and `elbow` both match the actual rendered result exactly (`elbow` is the two-bend Z-shaped path of the `bentConnector3` preset; a link that leaves its start through the top/bottom edge is written rotated 90°, so PowerPoint and other viewers that draw the stored geometry show the same vertical-horizontal-vertical route the checks assume. A connector end is glued only where the planned point is the middle of a side of the glued shape — the icon, or the label box for an end placed past the node's own label — so a viewer that redraws glued connectors from their glue points (LibreOffice on open, PowerPoint after you move a shape) keeps the planned route. Ends that aren't at such a point stay unglued and don't follow a moved shape: parallel links' lanes, a link meeting a container's frame part-way along, and `diamond`/`circle` nodes. LibreOffice draws an unglued vertical elbow horizontal first), as do waypoint links and same-side (`top`/`top`, ...) U routes, which are drawn as one straight connector per segment, but `curved` (a bezier curve) doesn't reproduce the curve's actual bulge — it's a straight-line approximation, for reference only.

## Connectors Are Limited to Rectangular Shapes

Every connection target (icon image, container frame) is treated as a rectangle, since python-pptx's own connector implementation doesn't guarantee stable behavior for anything else.

## Connector Labels Don't Follow Movement

Due to a constraint in the OOXML schema, a link's label is placed as an independent textbox at its midpoint. If you move shapes significantly after generation, the label's position won't follow (see [Design Notes](design-notes.md#connector-labels) for details).

## Icons Are Placeholders

The bundled icon images (for AWS, GCP, and Azure alike) aren't each vendor's official icons — they're self-made placeholders. Real-world use is expected to swap in official assets, following the instructions in [Icon Registry](icons.md#icon-assets).

## Official draw.io Icon Display Is AWS-Only

`zook export-drawio` writes out AWS icons/containers already mapped to draw.io's official AWS4 shape library with the official look. GCP/Azure icons/containers currently have no such mapping and fall back to embedding zook's own placeholder PNGs (the mechanism itself is shared across all three providers, so this is extensible by adding a mapping table — see [Design Notes](design-notes.md) for details and `docs/detailed-design-pptx.md` §8.14 for the background).

## The Built-in Vocabulary Is Finite

The built-in registries cover the services common in practice — 77 AWS, 39 GCP and 40 Azure types, plus provider-neutral actors and generic icons (check with `zook icons list`) — not each vendor's whole catalogue. For anything else, use the closest listed service, draw a plain shape (`style: {shape: rect}`) with the name as its label, or append it to your own registry via `--registry`. A container's `groups` (vpc/az/subnet, etc.) fall back to the AWS registry when undefined in a given provider's own registry, but things meant to look provider-specific — like the cloud boundary (`cloud`) — are defined individually in each provider's registry.

## Large-Scale Batch Generation Isn't a Target Use Case

Generating dozens or more slides in a single run isn't a target use case (1 YAML = 1 slide, with usage expected roughly weekly to a couple of times a month).
