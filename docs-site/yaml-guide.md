# YAML Input Guide

[🇯🇵 日本語版](/zook/ja/yaml-guide/){ .md-button }

zook's input YAML is strictly defined by [`zook.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/zook.schema.json) (JSON Schema Draft 2020-12). This page summarizes the key points. See [`docs/yaml-spec.md`](https://github.com/taka-sho/zook/blob/main/docs/yaml-spec.md) for the complete spec.

## Top-Level Structure

```yaml
version: "1.0"        # required. fixed value
canvas: {...}          # required. slide settings
elements: [...]        # required. array of containers/nodes
links: [...]            # optional. connectors. omit for a lineless diagram
```

## canvas

| Field | Required | Description |
|---|---|---|
| `aspectRatio` | Yes | `"16:9"` or `"4:3"` |
| `padding` | | margin between the slide edge and top-level elements (default 40) |
| `background` | | background color `#RRGGBB` |
| `overlapMargin` | | buffer (logical units, default 0) added around each element for overlap detection. `0` detects literal overlaps only; a larger value also flags elements/link paths that are merely close together |

The logical coordinate system is 1280×720 for `16:9` and 960×720 for `4:3`. Origin is top-left, +x is right, +y is down.

## Elements (`elements` / `children`)

Distinguished into two kinds via `kind`.

### container (a frame: VPC / AZ / subnet, etc.)

```yaml
- kind: container
  id: vpc-main          # unique across the whole diagram
  type: vpc               # a free-form string. cloud/vpc/az/subnet/region/account/group, etc.
  provider: aws            # default generic
  label: "Production VPC"
  style:
    labelFontSize: 10       # the frame's own label font size (pt, default 10)
    borderColor: "#8C4FFF"   # optional. defaults to the icon registry's groups.<type> default color
    fillColor: "#F5F0FF"      # optional. defaults to no fill (follows the registry's default)
    borderWidth: 2             # optional. defaults to 1
  layout:                  # auto-placement rule for children (see below)
    direction: horizontal
    gap: 48
  children: [...]           # nested (recursive)
```

Increasing `style.labelFontSize` also proportionally expands the top/bottom space auto-layout reserves for that label. Set `borderColor`/`fillColor`/`borderWidth` when you want to change color/line-width for one specific container away from the icon registry's default style (see [Icon Registry](icons.md)).

### node (an icon: EC2 / Lambda / RDS / S3, etc.)

```yaml
- kind: node
  id: web
  type: EC2                # the icon-resolution key. See "Icon Registry" for details
  label: "WebServer"
  size: 64                  # shorthand for setting the icon's width and height together (logical units)
  style:
    labelPosition: below    # below (default) / above / right / none
    labelGap: 4              # spacing between the icon and its label (logical units, default 4)
    labelFontSize: 9          # label font size (pt, default 9)
```

Increasing `labelGap` makes it easier to avoid label-vs-label or label-vs-link-label overlaps in tight layouts (overlaps are flagged as warnings per [Known Limitations](limitations.md), but not auto-avoided). Increasing `labelFontSize` also proportionally expands the footprint (height) auto-layout reserves for the label.

### node (plain shape: a shape + inline label instead of an icon)

```yaml
- kind: node
  id: step1
  type: step1               # effectively unused when shape is set (any value works)
  label: "Step A"
  style:
    shape: rounded            # rect / rounded / diamond / circle
    fillColor: "#D4E6FF"
    borderColor: "#2255AA"
```

Setting `style.shape` draws a shape (rectangle/rounded-rectangle/diamond/circle) instead of an icon, with the label centered inside it. This is what [Mermaid Flowchart Import](mermaid-import.md) uses internally, but you can use it directly in hand-written YAML too. `labelPosition`/`labelGap` have no effect in this mode (the label always sits centered in the shape).

## Position & Size

- `x`/`y` specified → absolute placement within the parent container (coordinates relative to its top-left origin). **Must be set together** (only one is a schema error).
- `x`/`y` omitted → auto-placed according to the parent's `layout`.
- Explicitly-positioned and auto-placed children can be mixed within the same container.
- `width`/`height` omitted: a container auto-sizes to fit its children; a node uses `size` (if given), falling back to a default icon size.
- A node's `size` is shorthand for setting `width`/`height` together. Explicitly setting `width`/`height` per axis wins on that axis, with `size` ignored there.

## Auto-Layout (`layout`)

Applies to children with no `x`/`y`.

| Field | Default | Description |
|---|---|---|
| `direction` | `grid` | `horizontal` / `vertical` / `grid` |
| `columns` | auto | number of grid columns |
| `gap` | 24 | spacing between children |
| `padding` | 32 | inner padding of the container |

!!! note "v1 limitation"
    In v1, auto-placement packs without avoiding children that already have explicit coordinates. If an overlap results, zook detects it as a Warning but doesn't auto-avoid it — fix it up by hand in PowerPoint (see [Known Limitations](limitations.md)).

## links (connectors)

```yaml
links:
  - from: web
    to: db
    label: "3306"       # optional
    labelFontSize: 8      # label font size (pt, default 8). no effect without label
    arrow: end            # end (default) / both / none
    style: straight        # straight (default) / elbow / curved
    fromSide: bottom       # optional. force the connection side (top/bottom/left/right)
    toSide: top             # optional. auto-selected if omitted
    waypoints:              # optional. intermediate points the path threads through (absolute canvas coords)
      - {x: 470, y: 150}
      - {x: 470, y: 360}
```

- `from`/`to` can reference either a node or a container. Referencing a nonexistent `id` is a Fatal error.
- Omitting `links` entirely produces "no lines, elements just placed in an area."
- `style` can explicitly be `straight`/`elbow`/`curved`. Even when `style` is omitted (default `straight`), a connection whose points aren't aligned horizontally or vertically (diagonal) is automatically drawn as `elbow` (a right-angle bend) instead, since a plain diagonal line doesn't match the orthogonal-routing convention of AWS-style architecture diagrams. Setting `elbow`/`curved` explicitly disables this auto-conversion.
- `fromSide`/`toSide` let you specify the connection side.
    - When both are set, a mismatched axis (`top`/`bottom` is vertical, `left`/`right` is horizontal — e.g. `fromSide: bottom` + `toSide: left`) is a Fatal error.
    - When only one is set, that side fixes the axis, and the other is auto-selected.
    - When both are omitted, it's fully automatic: rather than just the simple relative position (which of dx/dy is larger), the actual routed path length is compared (including label-avoidance offsets), switching to the other axis only when the dominant axis's path is clearly (20%+) longer. A near-tie never triggers a switch, avoiding an unstable, unintuitive choice.
- `waypoints` lets you make the routing explicit with intermediate points the path passes through. It's drawn as a straight polyline through the given points in order (disabling `style`'s automatic routing), useful for detouring around an obstacle or drawing an arbitrary L-shaped path. Each end auto-attaches to whichever side faces its nearest waypoint (a `fromSide`/`toSide` you set takes priority). Since the intermediate points make the routing explicit, the `fromSide`/`toSide` axis-match rule doesn't apply when `waypoints` is used. Coordinates are absolute canvas coordinates (unlike an element's `x`/`y`, which are local — a link belongs to no container, so it's given in absolute coordinates).
- If a node has a label via `labelPosition: below`/`above`, a link leaving from that same side (below→downward, above→upward) attaches outside the label, avoiding it. Left/right connections are unaffected by label position.

## A Complete Example

```yaml
version: "1.0"

canvas:
  aspectRatio: "16:9"
  padding: 40

elements:
  - kind: container
    id: vpc-main
    type: vpc
    provider: aws
    label: "Production VPC"
    layout:
      direction: horizontal
      gap: 48
      padding: 40
    children:
      - kind: container
        id: az-a
        type: az
        label: "ap-northeast-1a"
        layout:
          direction: vertical
          gap: 32
        children:
          - kind: node
            id: web-a
            type: EC2
            label: "WebServer A"
          - kind: node
            id: db-a
            type: RDS
            label: "Primary DB"

      - kind: container
        id: az-c
        type: az
        label: "ap-northeast-1c"
        layout:
          direction: vertical
          gap: 32
        children:
          - kind: node
            id: web-c
            type: EC2
            label: "WebServer C"
          - kind: node
            id: fn-c
            type: Lambda
            label: "Batch Worker"

  # Node placed outside the VPC with an absolute position
  - kind: node
    id: bucket
    type: S3
    label: "Asset Bucket"
    x: 1080
    y: 300
    width: 96
    height: 96

links:
  - from: web-a
    to: db-a
    label: "3306"
  - from: web-c
    to: fn-c
    arrow: end
    style: elbow
  - from: web-c
    to: bucket
    arrow: none
```

This sample is bundled with the repository as [`docs/example.yaml`](https://github.com/taka-sho/zook/blob/main/docs/example.yaml), and is validated against the JSON Schema.
