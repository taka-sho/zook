# YAML Input Specification (v1.0)

**Version:** 1.0
**Date:** 2026-07-25
**Scope:** Concretizes requirements spec §7.1/§9, and settles §14-1 (formal schema definition)
**Related files:** `zook.schema.json` (JSON Schema), `example.yaml` (sample)

---

## 1. Design Principles

- **Machine readability first**: since an LLM is expected to generate this, ambiguity is eliminated and strictly constrained via JSON Schema.
- **Extensibility through abstraction**: not tied to AWS-specific vocabulary — expressed through two concepts, **container** (a frame) and **node** (an icon). VPC, AZ, subnet, region — all are containers that differ only in `type`. This is what makes extending to GCP/Azure/arbitrary icons possible.
- **Explicit and automatic coexist**: writing coordinates places an element exactly (relative to its parent container); omitting them triggers auto-layout. The two can be mixed.
- **Assumes hand-editing afterward**: the output is a starting point for hand-editing in PowerPoint. We don't over-optimize.

## 2. Coordinate System & Units

- Written in logical units; the tool converts to EMU internally.
- The canvas's logical size is determined by the aspect ratio.

| aspectRatio | Logical size (W×H) | Physical size | EMU |
|---|---|---|---|
| `16:9` | 1280 × 720 | 13.333in × 7.5in | 12192000 × 6858000 |
| `4:3` | 960 × 720 | 10in × 7.5in | 9144000 × 6858000 |

- Origin is top-left. +x is right, +y is down.
- `x` / `y` / `width` / `height` / `gap` / `padding` are all logical units.

## 3. Top-Level Structure

```yaml
version: "1.0"        # required. fixed value "1.0"
canvas: {...}         # required. slide settings
elements: [...]       # required. array of containers/nodes
links: [...]          # optional. connectors. no links -> a lineless diagram
```

## 4. canvas

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `aspectRatio` | Yes | enum(`16:9`,`4:3`) | — | slide aspect ratio |
| `padding` | | number ≥ 0 | 40 | margin between the slide edge and top-level elements |
| `background` | | `#RRGGBB` | — | background color. Text, frame and line colours that would be hard to read on it (contrast below 3:1) switch to white or near-black - node labels, container labels and frames against whatever fill lies behind them |
| `overlapMargin` | | number ≥ 0 | 0 | buffer (logical units) added around each element for overlap detection (§9). `0` detects literal overlaps only; a larger value also flags elements/link paths that are merely close together |
| `layout` | | object | grid, gap 64 | arrangement of the top-level elements: `direction` (`grid`/`horizontal`/`vertical`), `columns`, `gap`. A grid without `columns` picks the count that best fits the slide (least overflow, then the closest aspect) |
| `fit` | | enum(`shrink`,`none`) | `shrink` | a laid-out diagram that doesn't fit the slide is scaled down uniformly (text included) and centred within `padding`; one that fits is untouched. `none`: drawn as laid out, and whatever falls outside is a Warning (§9) |

## 5. element (container / node)

Entries in `elements` and `children` are one of two kinds, distinguished by `kind`.

### 5.1 container (a frame: VPC / AZ / subnet, etc.)

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `kind` | Yes | `"container"` | — | discriminator |
| `id` | Yes | id string | — | unique; used for link references |
| `type` | Yes | string | — | `vpc`/`az`/`subnet`/`region`/`account`/`group` etc. (extensible) |
| `provider` | | enum | `generic` | `aws`/`gcp`/`azure`/`custom`/`generic` |
| `label` | | string | — | label drawn on the frame |
| `x`,`y` | | number | — | position relative to the parent container's top-left (the canvas's at the top level); must be set together, one alone is not allowed |
| `width`,`height` | | number > 0 | — | explicit size; auto-sized to fit children if omitted |
| `layout` | | object | — | auto-placement rule for children (§7) |
| `style` | | object | — | border color/fill/line width/label position/label font size |
| `children` | | element[] | — | nested elements (recursive) |

`style.labelFontSize` (number > 0, default 10, pt): the container's own label font size. The top/bottom space auto-layout reserves for the label also scales proportionally with this value.

`style.borderColor`/`style.fillColor` (`#RRGGBB`), `style.borderWidth` (number ≥ 0, default 1): the frame's border color, fill, and line width. If omitted, the default style defined at `groups.<type>` in the icon registry is used (and if not defined there either: border `#5A6B86`, no fill, line width 1). Set these when you want to override the registry default's color for one specific element.

`style.labelPosition` (enum: `top-left`/`top-center`/`bottom-left`, default `top-left`): where the container's own label is drawn. If omitted, follows the registry's `groups.<type>.labelPosition`.

### 5.2 node (an icon: EC2 / Lambda / RDS / S3, etc.)

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `kind` | Yes | `"node"` | — | discriminator |
| `id` | Yes | id string | — | unique; used for link references |
| `type` | Yes | string | — | `EC2`/`Lambda`/`RDS`/`S3` etc. (extensible); the icon-resolution key |
| `provider` | | enum | `aws` | `aws`/`gcp`/`azure`/`custom` |
| `label` | | string | — | the icon's label |
| `x`,`y` | | number | — | position relative to the parent container's top-left (the canvas's at the top level); must be set together |
| `width`,`height` | | number > 0 | — | icon size; falls back to `size`, then to a default size if omitted |
| `size` | | number > 0 | — | shorthand for setting `width`/`height` together. If `width`/`height` is explicitly set on one axis, `size` is ignored on that axis |
| `style` | | object | — | label position (`labelPosition`: below/above/right/none), label spacing (`labelGap`), label font size (`labelFontSize`), plain-shape mode (`shape`/`fillColor`/`borderColor`, below) |

`style.labelGap` (number ≥ 0, default 4, logical units): spacing between the icon and its label. Has no effect when `labelPosition: none`. Useful for avoiding label-vs-label or label-vs-link-label overlaps in tight layouts.

`style.labelFontSize` (number > 0, default 9, pt): the node's label font size. The footprint (height) auto-layout reserves for the label also scales proportionally with this value. Has no effect when `labelPosition: none`.

`style.shape` (enum: `rect`/`rounded`/`diamond`/`circle`): when set, the node skips icon resolution via `type` and instead becomes a "plain shape node" with the label drawn directly inside the shape (a box-with-text-inside look, similar to Mermaid flowchart notation). `type` is still required by the schema, but is effectively unused when `shape` is set (any value works). `labelPosition`/`labelGap` have no effect (the label always sits centered in the shape).

`style.fillColor`/`style.borderColor` (`#RRGGBB`): fill and border color when `shape` is set. Default is a white background with a black border. Has no effect when `shape` is not set.

### 5.3 id Rules

- Pattern: `^[A-Za-z][A-Za-z0-9_-]*$` (starts with a letter; letters, digits, `_`, `-`).
- Must be unique across the whole diagram. A duplicate is an error (§9).

## 6. Position & Size Rules

- `x`/`y` specified → placed at that offset from the parent container's top-left corner (or the canvas's, at the top level).
- `x`/`y` omitted → auto-placed according to the parent's `layout`.
- `x` and `y` **must be set together** (specifying only one is a schema error).
- `width`/`height` omitted: a container auto-sizes to fit its children; a node uses its default icon size.
- A node's `size` is shorthand for setting `width`/`height` together. If `width`/`height` is set explicitly per axis, that value wins and `size` is ignored on that axis (e.g. `size: 80, width: 40` → width 40, height 80).
- Within the same container, "children with explicit coordinates" and "auto-placed children" can be mixed. An auto-placed child that would overlap an explicitly-positioned sibling is pushed down clear of it; anything this simple push doesn't resolve is a Warning (§9).
- A node's label is measured from its text: a long label widens the node's footprint up to 150 units and then wraps, and every line is reserved. A container reserves a band for its label — its own `label`, or the registry's default label when omitted — at the top, or at the bottom for `labelPosition: bottom-left`, and an auto-sized container widens for its label (up to 260 units) before the label wraps.

## 7. Auto-Layout (layout)

Applies to children with no `x`/`y`.

| Field | Type | Default | Description |
|---|---|---|---|
| `direction` | enum(`horizontal`,`vertical`,`grid`) | `grid` | arrangement |
| `columns` | integer ≥ 1 | auto | number of grid columns |
| `gap` | number ≥ 0 | 24 | spacing between children |
| `padding` | number ≥ 0 | 32 | inner padding of the container |

- `grid`: if `columns` is omitted, it's derived automatically from the number of children (for the top level: the count that best fits the slide). Each column is as wide as its widest member and each row as tall as its tallest.
- `horizontal` / `vertical`: arranged in a single row/column.
- Cross-axis alignment: in a row/column of nodes only, icons are centred on one line (so links between neighbours run straight); a row/column holding a container aligns its members to the start edge.
- When the container's size is unspecified, it's auto-determined from the bounding box of the placed children plus `padding`.

## 8. links (connectors)

| Field | Required | Type | Default | Description |
|---|---|---|---|---|
| `from` | Yes | string | — | source element id |
| `to` | Yes | string | — | target element id |
| `id` | | id string | — | the link's own id (optional); must be unique among links and not reuse an element id (Fatal otherwise) |
| `arrow` | | enum(`end`,`both`,`none`) | `end` | arrowhead placement. `none` draws a plain line |
| `style` | | enum(`straight`,`elbow`,`curved`) | `straight` | connector routing style |
| `label` | | string | — | a label carried on the line (e.g. a port number) |
| `labelFontSize` | | number > 0 | 8 | label font size (pt). The midpoint label box itself also scales proportionally with this value. No effect without `label` |
| `fromSide` | | enum(`top`,`bottom`,`left`,`right`) | — | force the connection side on the `from` end. Auto-selected if omitted |
| `toSide` | | enum(`top`,`bottom`,`left`,`right`) | — | force the connection side on the `to` end. Auto-selected if omitted |
| `waypoints` | | array of `{x,y}` (1 or more) | — | intermediate points (absolute canvas coordinates) the path threads through, in order, connected by straight segments. Takes priority over `style` routing. Use it to detour a connector around an obstacle |

- Omitting `links` entirely produces "no lines, elements just placed in an area."
- `from`/`to` can reference either a node or a container.
- Connections assume rectangular targets (design memo §8.2). Labels track the connector (design memo §8.3).
- When `style` isn't set explicitly (default `straight`), a connection whose two endpoints aren't aligned horizontally or vertically (i.e. diagonal) is automatically drawn as `elbow` (a right-angle bend) instead. This avoids a plain diagonal line, which doesn't match the orthogonal-routing convention of AWS-style architecture diagrams. An explicit `elbow`/`curved` is never overridden.
- If a node has a `label` (default position `below`/`above`), a connection leaving from that same side attaches outside the label (e.g. an arrow going downward from a node with a `below` label connects below the label). Left/right connections are unaffected by the label.
- `fromSide`/`toSide`: use these to force a specific connection side.
  - **Both set**: used as-is. However, mixing `top`/`bottom` (vertical) with `left`/`right` (horizontal) — an axis mismatch — is Fatal (§9).
  - **Only one set**: the side given fixes the axis (horizontal/vertical); the other side is auto-chosen within the same axis based on the relative position of the two endpoints.
  - **Both omitted (default)**: the horizontal and vertical routes are compared by how many other elements they run through, and the clearer one wins. On a tie, generally uses whichever of `|dx|`/`|dy|` is larger (the dominant axis), but switches to the other axis if its actual routed path (including label-avoidance offsets) is more than 20% shorter (see `detailed-design-pptx.md` §8.15 for details).
  - **Both on the same side** (`top`/`top`, `left`/`left`, ...): a U route that leaves both ends outward, passes beyond the outermost endpoint, and comes back.
- **A link from an element to itself** (a retry loop) is drawn out of one side and back into the adjacent one around their shared corner, 16 units clear of the element: right to top by default; `fromSide`/`toSide` can name another pair of adjacent sides.
- **A link between a container and an element inside it** runs straight from that element's side nearest the frame to the frame (unless `fromSide`/`toSide` are set).
- **Links joining the same two elements** (`A -> B` twice, or `A -> B` and `B -> A`) are drawn side by side, 18 units apart, instead of on one line with their labels stacked.
- A link `label` is sized from its text (wrapping past 120 units) and centred on the path's arc-length midpoint, unless that would cover an end of the link or one of its endpoint icons; then it moves to the nearest free spot just beside the line (or past the endpoint icons), within 60 units.
- `waypoints`: use this when you want to make the routing explicit, e.g. to detour around an obstacle. It's drawn as a straight polyline through the given intermediate points in order (in the pptx, one straight connector per segment, with the arrowhead only on the final segment), and `style`'s automatic routing no longer applies. Each end auto-attaches to whichever side of its shape faces the nearest waypoint (a `fromSide`/`toSide` you set takes priority). Since the intermediate points make the routing explicit, the `fromSide`/`toSide` axis-match rule (§9) doesn't apply when `waypoints` is used. Coordinates are absolute canvas coordinates (unlike an element's `x`/`y`, which are local to its parent — a link belongs to no container, so it's given in absolute coordinates). The label sits at the polyline's true midpoint (by arc length).

## 9. Error Policy

| Condition | Class | Behavior |
|---|---|---|
| The file isn't valid YAML (syntax error, reported with line and column), isn't UTF-8 (a BOM is fine), or can't be read | Fatal | generation stops |
| A mapping key written twice in the same mapping (e.g. two `links:` blocks) | Fatal | generation stops (never "last one wins") |
| An unquoted value YAML 1.1 reads as another type (`16:9` → 969, `no` → false, `1.0` → float) where a string is required | Fatal | schema violation, with a hint to quote the value |
| A number that is `.nan`/`.inf` or beyond ±1,000,000 | Fatal | generation stops |
| Schema violation (missing required field, type mismatch, unknown field) | Fatal | generation stops, errors out |
| Duplicate `id` | Fatal | generation stops |
| `link.from`/`to` references a nonexistent id | Fatal | generation stops |
| Unknown `type` (icon unresolved; lookup ignores case, spaces, hyphens, underscores and dots) | Warning | continues with a placeholder icon; the message names the closest types, or the provider that has this one |
| Icon file that can't be read as an image (PNG/JPEG as-is, SVG rasterized) | Warning | continues with a placeholder icon |
| Unknown container `type` | Warning | drawn as a plain frame; the message names the closest container type |
| Coordinates outside the canvas (anything drawn - element, node label, link path or label - with `canvas.fit: none`) | Warning | placed as-is, with a warning (not clipped) |
| The diagram needed shrinking below 70% to fit the slide (`canvas.fit: shrink`) | Warning | shrunk to fit, with a warning (text is correspondingly smaller) naming any explicitly positioned element outside the canvas; a milder shrink is silent |
| Elements overlap (between siblings) | Warning | placed as-is, with a warning (no avoidance/auto-fix) |
| A child overlaps its container's own label text | Warning | placed as-is, with a warning |
| A child extends outside its own container (explicit x/y beyond the container's explicit size, or negative) | Warning | placed as-is, with a warning |
| A link's path runs back through one of its own endpoint nodes (icon or label) | Warning | placed as-is, with a warning |
| A link's label covers one of its own endpoint nodes (no spot beside the line clear of them was found) | Warning | placed as-is, with a warning |
| A link's path or label overlaps an unrelated element, another link's label, or a container's label | Warning | placed as-is, with a warning (no detour) |
| Two separate links' Z-routes run collinear through a shared node's connection point, reading as one direct connection (false edge aliasing) - not a fan-out/fan-in trunk shared by links leaving (or entering) the same point | Warning | placed as-is, with a warning (connection points aren't shifted) |
| Both `link.fromSide`/`toSide` set with a mismatched axis (horizontal/vertical) (only when `waypoints` is not set) | Fatal | generation stops |
| Only one of `x`/`y` set | Fatal | rejected by the schema |

- Basic policy: **structural breakage is Fatal and stops generation immediately; minor drawing issues are Warnings that let generation continue**.
- Since CI/CD is assumed, a Fatal returns a non-zero exit code.
- The overlap check mechanically tests for rectangle intersection using the computed coordinates (regardless of whether they came from explicit positioning or auto-layout). It only compares siblings within the same parent container — a parent and its own contents are expected to overlap and are excluded. The one exception is a **container's own label text area**, which is checked individually against its direct children (auto-placed children already avoid this area, but explicitly-positioned children don't). Setting `canvas.overlapMargin` adds that much buffer around every element/label before testing (proximity detection).
- The link-path check derives the connector's actual rendered path from its real connection points (`straight` is a straight line; `elbow` is the exact two-bend Z-route that's actually rendered) and tests it against every element except the endpoints and their ancestors/descendants, every other link's label rectangle, and every container's label rectangle. Only `curved` doesn't reproduce the actual curve's bulge, so it's approximated as a straight line for reference purposes only (see `detailed-design-pptx.md`).
- **A link's own label** is also checked, independently of its path, as its own rectangle against unrelated elements, other links' labels, and container labels (since the label's displayed position can overlap something even when the path itself avoids it).
- The check against a container's label doesn't exclude ancestor containers either (passing through an ancestor container's body is normal, but visually cutting through its **label text** specifically is undesirable). The only exclusion is when the link's `from`/`to` is that very container.
- `overlapMargin` applies to all of the checks above.
- The **false-edge-aliasing check** is distinct from the "crossing" detection above: instead of "crosses an unrelated element," it detects "two separate links' paths run collinear (touching or overlapping) on the same line, reading as one direct connection." The typical case is two links sharing a common node X (one ending at X, one starting from X) where `choose_connection_indices()` happens to pick the same side of X for both. Each link's path is broken into segments, and any pair of segments from different links that lie on the same line (same axis, same coordinate) with touching ranges (even a single point of contact) is mechanically flagged (see `detailed-design-pptx.md` §8.13).

## 10. Icon Resolution Rules

- A node's `type` is looked up in the icon registry of its `provider` (`zook icons list`; see `icon-registry-and-vocabulary.md`), ignoring case, spaces, hyphens, underscores and dots; the entry's `file` (relative to the registry's `basePath`) is the icon. Actors and generic icons resolve under any provider.
- PNG and JPEG icons are used as-is; SVG icons are rasterized when read (design memo §8.1, §8.6).
- Each provider has its own registry; a `--registry` file layers onto one of them, or declares `provider: custom` for a vocabulary of its own.

## 11. Complete Samples

- `example.yaml` — two AZs inside a VPC, services in each AZ, an S3 outside the VPC at an explicit position, and three kinds of links (labeled / elbow / no arrowhead). Validated against the JSON Schema.
- `example-cloud-actors.yaml` — an outermost `cloud` (AWS Cloud) container, `User`/`Admin` actor nodes outside it, and links referencing the container (actor → container). Validated against the JSON Schema, with no overlaps.

## 12. Status

- This spec has been formalized as a JSON Schema (`zook.schema.json`).
- Verified: the schema itself conforms to Draft 2020-12, the samples validate against it, and invalid input is rejected.
- The implementation (Claude Code side) uses this schema as the single source of truth for validation.

## 13. Handoff to the Implementation Side (Claude Code)

- Input YAML must **always be validated against this schema before** entering the rendering pipeline.
- §8.2/§8.3/§8.6 (connection point indices, txBody labels, PNG DPI) should be confirmed against real prototype behavior at implementation time.
- Logical-unit → EMU conversion must follow the table in §2.
- Auto-layout should ship in v1 with the defaults in §7; more sophisticated overlap avoidance can wait for a later version.
