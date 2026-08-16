# Design Notes

[🇯🇵 日本語版](/zook/ja/design-notes/){ .md-button }

zook's PowerPoint generation (built on [python-pptx](https://python-pptx.readthedocs.io/)) rests on a handful of technical decisions validated by prototyping before implementation. The details live in [`docs/detailed-design-pptx.md`](https://github.com/taka-sho/zook/blob/main/docs/detailed-design-pptx.md); the key points are below.

## Coordinate System

Written in logical units, converted internally to EMU (English Metric Unit).

| aspectRatio | Logical size | Physical size |
|---|---|---|
| `16:9` | 1280 × 720 | 13.333in × 7.5in |
| `4:3` | 960 × 720 | 10in × 7.5in |

The simple conversion **1 logical unit = 9525 EMU = 1px at 96dpi** holds for both aspect ratios.

## Hierarchical Grouping

A nested structure like VPC → AZ → service is expressed as nested groups in PowerPoint via `add_group_shape()`. python-pptx automatically recalculates `chOff`/`chExt` (a group's child-coordinate-system offset/extent) to match its children's bounding box every time a child is added, so no custom helper implementation was needed.

## Connector Connection-Point Indices

When connecting rectangular shapes (icon images, container frames) to each other via `begin_connect()`/`end_connect()`, the connection-point index is settled as follows:

```
idx 0 = top-center
idx 1 = left-center
idx 2 = bottom-center
idx 3 = right-center
```

This is fixed as a library specification, not renderer-dependent, since python-pptx's own implementation (`_move_begin_to_cxn`/`_move_end_to_cxn`) computes the connection points' actual coordinates directly from this mapping.

A connection side can be set explicitly via `link.fromSide`/`toSide` (if both are set, they must share an axis — a mismatch is a Fatal error). An omitted side is auto-selected: rather than just the simple relative position (which of dx/dy is larger), the actual routed path length is computed and compared for both axis candidates, including the label-avoidance offset. On a near-tie (under 20%), though, the dominant axis (whichever of dx/dy is larger) is preferred, with a hysteresis that only switches to the other axis when it's clearly (20%+) shorter. This is because deciding purely by shortest distance was found, during implementation validation, to be unstable — the axis would flip on a near-tie.

## Connector Labels {: #connector-labels }

Under the OOXML schema, a connector element (`p:cxnSp`) cannot carry a `txBody` (text body). Because of this, a link's `label` is drawn as an **independent textbox placed at the connector's midpoint**. The label itself doesn't follow the connector when shapes are moved (consistent with the design's assumption of hand-editing afterward).

## Icon Rasterization Resolution {: #icon-raster-resolution }

When rasterizing an SVG icon to PNG, it's rendered at **4x the displayed pixel count**. At 1x (96dpi-equivalent), blurriness was visible when scaled up in PowerPoint/LibreOffice; at 2x and above it was mostly gone, and 3x vs. 4x was indistinguishable to the eye. For an icon-sized image, the file size at 4x is still minor (on the order of tens of KB).

## Visual Consistency With the Lightweight PNG Preview

`zook preview` is a second renderer that skips python-pptx entirely, drawing the same layout results (the `Box` tree, connection-point calculations) directly with Pillow. A container's look — border color, fill, dashing, label position, corner icon — is resolved in one place via the shared function `resolve_container_style()`, so the pptx renderer and the PNG preview can never drift apart on how something should look.

## Multi-Cloud Resolution

A separate registry is held per element `provider` (`aws`/`gcp`/`azure`/any custom value), and `MultiRegistry` dispatches between them. Icons are assumed to exist only in their own provider's registry, but a container's `groups` (vpc/az/subnet, etc.) fall back to the AWS registry when undefined for that provider. This is a deliberate design choice so that structural concepts common across clouds (VPC, AZ, etc.) don't need to be redefined in the GCP/Azure registries every time.

## draw.io Integration

`zook export-drawio`/`sync` (see [draw.io Integration](drawio-sync.md) for details) treats draw.io (mxGraph XML) as a second output target alongside pptx. Unlike a PowerPoint group, draw.io's container (`container=1`) keeps a child element's coordinates as a plain relative offset from the parent, with no scaling of child coordinates on resize — confirmed against the official `jgraph/drawio` source. Since the scaling trap that pptx groups' `chOff`/`chExt` carry simply doesn't exist here, the layout results (`Box.local_x`/`local_y`) can be used directly as mxGraph child coordinates, with no coordinate conversion needed.

AWS icons/containers were added to the registry after confirming draw.io's official AWS4 shape-library identifiers (`resIcon`/`grIcon`) directly from its source code (not guessed), so they display with the familiar official look in draw.io too. GCP/Azure don't have an equivalent mapping table yet and fall back to zook's own placeholder PNGs (see [Known Limitations](limitations.md)).

## How This Was Validated

These decisions were validated by actually generating a pptx with `prototype/build_prototype.py` and visually inspecting it, rendered to an image via LibreOffice headless (`soffice --convert-to pdf` → `pdftoppm`). See [`prototype/README.md`](https://github.com/taka-sho/zook/blob/main/prototype/README.md) for the reproduction steps.
