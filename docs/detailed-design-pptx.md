# Detailed Design Memo: PowerPoint Output (python-pptx)

**Version:** 0.1
**Date:** 2026-07-25
**Scope:** Concretizes requirements spec §7.2/§7.3/§14-3
**Assumed library:** python-pptx 1.0.0

---

## 1. Technical Validation — Conclusions

| Item validated | Conclusion | Notes |
|---|---|---|
| Hierarchical grouping of shapes | Possible | `add_group_shape()`. Nested groups work (recursive structure) |
| Moving/editing a whole group as one unit | Possible | In PowerPoint you can grab and move an entire group |
| Connector (arrow) attached to shapes | Possible | `begin_connect()` / `end_connect()` |
| Arrow follows when a shape is moved | Possible (with a quirk) | Maintains a relative offset. Does not re-snap to the connection point |
| Stability of the connection feature | Rectangles only | EXPERIMENTAL. Works correctly with images/rectangles — which is exactly what we need here |

## 2. Group Structure Design

### 2.1 Hierarchy Policy

Editability is the top priority, so grouping follows this hierarchy:

```
Slide (root shapeTree)
└─ VPC group
   ├─ VPC frame (rectangle / label)
   └─ AZ group (multiple)
      ├─ AZ frame (rectangle / label)
      └─ service group (multiple)
         ├─ icon (image)
         └─ label (textbox)
```

- Each VPC, AZ, and service can be grabbed as a single object in PowerPoint.
- Grouping a service's "icon + label" together means the label never drifts away from its icon when moved.

### 2.2 Implementation Notes (Groups)

- `shapes.add_group_shape()` returns an empty group. Children are added via `group.shapes.add_picture()` etc.
- A group's child offset/extent (chOff/chExt) needs to be set to match the coordinate range of its children.
  → **Hide this behind a helper function `create_group(children, bbox)` that computes it automatically from the children's bounding box.**
- Groups can be nested recursively, so the VPC → AZ → service, three-level hierarchy can be expressed directly.

## 3. Connector (Arrow) Design

### 3.1 Connection Policy

- Generate a line via `slide.shapes.add_connector(connector_type, x1, y1, x2, y2)`.
- Attach both ends to shapes via `begin_connect(from_shape, cxn_pt_idx)` / `end_connect(to_shape, cxn_pt_idx)`.
- Connection targets are limited to rectangles (icon images, VPC/AZ frames), since the EXPERIMENTAL implementation is stable only for rectangles.
- Arrow direction/arrowhead is set on the **line's endpoint style** (note: this is not a connector-specific property).

### 3.2 Understanding — and Accepting — the Follow Behavior

- Moving a shape moves its connector by the same amount (i.e. it follows).
- However, the endpoint doesn't re-snap to the connection point — it just **keeps the same relative offset**.
  → Large repositioning in PowerPoint can leave the line's routing less than ideal.
- Since this tool's stance is to provide "a starting point for hand-editing" (requirements spec §8-R-NF-03), this behavior is accepted. The lines are drawn correctly right after generation; humans handle fine-tuning.

### 3.3 Connection Point Index (cxn_pt_idx) Policy

- A rectangle's connection points are typically assigned to top/left/bottom/right etc. (index starting at 0).
- Implement logic that picks an appropriate connection-point index for each end, based on the relative position of `from` vs `to` (left/right, up/down).
  Example: if `from` is to the left of `to` → pick `from`'s right edge and `to`'s left edge.

## 4. YAML → PPTX Mapping

| YAML element | PPTX representation |
|---|---|
| `canvas.aspectRatio` | sets the slide size (`prs.slide_width` / `slide_height`) |
| `vpcs[]` | VPC group + rectangular frame |
| `availabilityZones[]` | AZ group + rectangular frame |
| `children[]` (services) | a service group (icon image + label) |
| `type` (EC2 etc.) | the icon image file's lookup key |
| `x` / `y` / `size` | the shape's absolute coordinates/size (auto-placed if omitted) |
| `links[]` | connectors (begin_connect / end_connect) |
| `links[].label` | text near the connector's midpoint, or a label attached to the line |

## 5. Coordinate System & Units

- python-pptx's internal unit is the EMU (English Metric Unit, 914400 EMU = 1 inch).
- YAML is written in an easier-to-work-with unit (roughly px-equivalent), converted to EMU internally.
- Canvas size is derived from the aspect ratio (e.g. 16:9 resolved against a default inch width).

## 6. Handling Icons

- Icons are referenced from an external folder (requirements spec §7.4-R-IC-03). A mapping table from `type` to file path is maintained.
- Official AWS icons are SVG. Since python-pptx expects embedded images as PNG/EMF etc., we need to determine whether **SVG→raster (PNG) or SVG→vector (EMF)** conversion is required (open in §8).
- The mapping is split by per-provider directory (`icons/aws/`, `icons/gcp/`, `icons/custom/`).

## 7. Auto-Layout (When Position Is Unspecified)

- v1 uses a simple algorithm that arranges children in a grid within their container (VPC/AZ).
- Column count, spacing, and padding are parameterized. Elements with an explicit position stay fixed; only unspecified elements are auto-arranged.
- Prioritizes "no overlaps, readable" over strict visual polish.

## 8. Decisions (Formerly-Open Items, Now Settled)

### 8.1 SVG icon embedding method → PNG by default, EMF optional

- python-pptx is built on PIL/Pillow, and Pillow only supports raster formats (PNG/JPEG/GIF/TIFF/BMP). **Embedding SVG directly is not possible.**
- **Default: rasterize SVG → PNG** (via `cairosvg` etc.). Self-contained via pip with no external GUI dependency, so it's easy to run in CI/CD. A high-DPI PNG is practically sufficient for icon purposes.
- **Optional: vectorize SVG → EMF** (requires something like Inkscape). Higher scaling fidelity and editability, but adds a heavy external dependency that doesn't suit CI/CD. Kept as an opt-in choice only.
- Rationale: since CI/CD is assumed (requirements spec R-OP-03), that takes priority, and PNG is the standard.

### 8.2 Connection point indices → settled (verified by prototype)

- All connection targets (icon images, VPC/AZ frames) are unified as **rectangles**.
- **Indices are settled as `idx 0 = top-center / 1 = left-center / 2 = bottom-center / 3 = right-center` (starting at top, counter-clockwise).**
  This is determined by python-pptx's own implementation (`_move_begin_to_cxn`/`_move_end_to_cxn` in `pptx/shapes/connector.py`), which computes the connection points' actual coordinates directly from this mapping — it's **fixed as a library specification, not renderer-dependent**. We rendered `prototype/build_prototype.py`'s idx legend (red dots explicitly marking the idx at all four directions) via LibreOffice headless and visually confirmed this mapping as well.
- A helper that picks the connecting side from the relative position of `from` vs `to` (left/right, up/down, decided via `abs(dx) >= abs(dy)`) has been implemented and validated (`choose_connection_indices()`). Non-rectangular shapes (rounded corners, etc.) aren't used.

### 8.3 Connector label tracking → settled on a midpoint textbox (txBody injection turned out to be impossible)

- **Under the OOXML schema, `p:cxnSp` (a connector) cannot carry a `txBody` child element.** LibreOffice's oox source (`shapes.cxx`) explicitly states "connector shape (cxnSp) cannot contain text (txBody) (according to schema)," confirming that the "first choice" of injecting a txBody into a connector is technically impossible.
- The implementation therefore **adopts the midpoint textbox (an independent `p:sp`) as the sole approach**, accepting the constraint that it won't track shape movement (consistent with the "starting point for hand-editing" stance in §3.2).
- Implementation note (found during prototyping): the label box is placed at the midpoint of `begin_x/y` and `end_x/y`, but it can end up close to — and overlapping — a container's own label (see §8.6), so simple collision avoidance against nearby elements (an offset, or a white background for readability) needs to be applied at generation time. The prototype used a white-filled textbox background to ensure at least minimal readability.

### 8.4 Automatic computation of group extent → fixed 1:1 mapping (handled by python-pptx's built-in behavior, no custom helper needed)

- Compute the children's bounding box and set it as the group's off/ext. Use **chOff/chExt = off/ext**, using the children's absolute coordinates directly (no scale conversion).
- **Found during prototyping: python-pptx automatically calls `CT_GroupShape.recalculate_extents()` every time a child is added to a group via `shapes.add_group_shape()`, handling the chOff/chExt = off/ext 1:1 mapping by default.** The custom helper function `create_group(children, bbox)` the design memo originally assumed would be needed turns out to be unnecessary — it's enough to call `group.shapes.add_picture()`/`add_shape()`/`add_textbox()`/`add_group_shape()` directly.

### 8.5 Aspect ratio → slide dimensions settled

| Ratio | Inches (W×H) | EMU (W×H) | Default |
|---|---|---|---|
| 16:9 | 13.333 × 7.5 | 12192000 × 6858000 | ◎ |
| 4:3 | 10 × 7.5 | 9144000 × 6858000 | |

- 1 inch = 914400 EMU. Default is 16:9.
- The slide size is set by looking up this table with `canvas.aspectRatio`'s value.
- **Coefficient confirmed by prototyping: 1 logical unit = 9525 EMU = 1px at 96dpi.**
  This holds for both 16:9 (1280 logical width → 13.333in) and 4:3 (960 logical width → 10in): `914400 × width_in ÷ logical_width = 9525` in both cases. This means a simple conversion — treating the YAML's logical units directly as "96dpi pixels" — is valid.

### 8.6 Icon PNG rasterization resolution → settled at 4x the displayed size (px)

- **Confirmed by prototyping: rasterizing an SVG at the same pixel count as its displayed size (96dpi-equivalent, 1x) shows visible blurriness when scaled up in PowerPoint/LibreOffice.** At 2x the visible blurriness is mostly gone, and 3x vs 4x is indistinguishable to the eye.
- File size for an icon-sized image stays around tens of KB even at 4x, which is fine in practice, so **the default is 4x (= the logical-unit pixel count × 4), giving margin for printing/projector use.**
  Example: a default icon size of 64 logical units → rasterized at 256×256px.
- Implementation: `cairosvg.svg2png(url=svg_path, output_width=size_logical_units*4, output_height=size_logical_units*4)`.

### 8.7 Validation Prototype (completed)

The following was validated with `prototype/build_prototype.py` (python-pptx 1.0.2 + cairosvg + LibreOffice 26.2.5 headless, rasterized via `soffice --convert-to pdf` → `pdftoppm` and inspected visually).

| Item | Conclusion |
|---|---|
| Order of connection-point index assignment | Settled as in §8.2 (0=top/1=left/2=bottom/3=right). Deterministic, since it comes from python-pptx's source. |
| Label rendering via txBody injection | Injection itself is impossible — a schema violation. Settled on the midpoint-textbox approach (§8.3). |
| The right resolution for high-DPI PNGs | Rasterize at 4x the displayed pixel count (§8.6). |
| Grouping (chOff/chExt) | Found that python-pptx's `recalculate_extents()` handles the 1:1 mapping automatically, so no custom implementation is needed (§8.4). |
| (Secondary finding) Vertical position of a container's label | `add_shape()`'s default text frame is vertically centered, which doesn't match the intent of `labelPosition: top-left` (top-left). The implementation needs to explicitly set `text_frame.vertical_anchor = MSO_ANCHOR.TOP`. |

### 8.8 Link-path overlap detection → settled by reproducing elbow's actual path

Requirement: mechanically detect when an arrow (connector) crosses an unrelated element or text partway along its path.

- The connector's actual connection-point coordinates can be computed deterministically via the mapping from §8.2 (`connection_point()`). For `style: straight`, the line segment connecting those two points matches the rendered result exactly.
- **`elbow` (`MSO_CONNECTOR.ELBOW`) always uses the OOXML preset geometry `bentConnector3`** (a fixed mapping in python-pptx). This is a two-bend, three-segment Z-shaped path: it exits perpendicular to the start shape's connected edge, bends once at the midpoint of the bridging axis, and enters perpendicular to the end shape's edge. Since `choose_connection_indices()` always returns a same-axis pair (horizontal: 1/3, vertical: 0/2), the shape of the path is uniquely determined by whether the start-side idx is horizontal or vertical. This path was **measured and confirmed via an actual rendering probe in LibreOffice headless** (equivalent to what's in `prototype/`: forcing `idx` via `begin_connect`/`end_connect` on fixed start/end shapes and confirming the path exits perpendicular to the connected edge regardless of the bounding box's aspect ratio). This Z-shaped path is implemented in `connector_path()`, and rectangle-intersection is tested per segment, so the check matches the actual rendering rather than a straight-line approximation.
- Only `curved` doesn't reproduce the actual bezier curve's bulge — it's a straight-line approximation (reference value only).
- Getting the exclusion set (ancestors/descendants) wrong would falsely flag "overlapping its own child element inside the container," which is expected and normal — so the ancestor/descendant sets for each link's start and end are derived from the Box tree's parent/child relationships and excluded.
- `canvas.overlapMargin` (default 0) adds a buffer around every element/label rectangle. `0` detects literal intersection only; a larger value also flags proximity. The same margin is applied to both `overlap_warnings()` (sibling-to-sibling overlaps) and `link_crossing_warnings()` (link paths).
- Warning only (never Fatal). No detour or auto-fix is performed.

### 8.9 Label-avoiding connection points, auto-elbow for diagonal lines (added during implementation)

- A node's `labelPosition: below`/`above` places the label textbox outside the icon. Previously, `connection_point()` returned the icon's own edge (bottom/top), so a link leaving from that side would cut straight through the label. **This was resolved by pushing the connection point out past the label (to the edge of the footprint), but only for connections leaving from the same side as the label** (below→idx2, above→idx0). Left/right (idx1/3) are unaffected by label position.
- Since python-pptx's `begin_connect`/`end_connect` snap to the shape's actual edge, the push-out above wouldn't take effect as-is. This was resolved by **directly overwriting `conn.begin_x`/`begin_y` (and `end_x`/`end_y`) after calling `begin_connect`**, which keeps the logical connection info (`stCxn`/`endCxn`, used for drag-follow behavior) intact while placing the initial render position wherever we want. That this override actually takes effect (i.e. isn't re-snapped to the connected shape's edge) was confirmed via LibreOffice rendering.
- When a link with no explicit `style` (default `straight`) has connection points that aren't aligned horizontally or vertically (i.e. diagonal), it's automatically upgraded to `elbow` (`effective_connector_style()`). This avoids a plain diagonal line, which doesn't match the orthogonal-routing convention of AWS-style architecture diagrams. An explicit `elbow`/`curved` is never overridden.
- `link_render_plan()` computes all of the above (connection-point idx, effective style, actual path) in one place, and is called by both `render.py` (actual rendering) and `link_crossing_warnings()` (detection), so the detection logic never drifts from what's actually rendered.

### 8.10 Overlap detection for container labels and link labels (added during implementation)

Requirement: extend overlap detection beyond just element bodies, to also cover "a container's text area" and "a link's label."

- **Container label vs. child elements**: the area a container's own label text occupies is defined as `container_label_rect()`. Its position is decided by `resolve_container_label_position()` (`element.style.labelPosition` → the registry's `groups.<type>.labelPosition` → default `top-left`, the same precedence render.py uses), and its height by `CONTAINER_LABEL_RESERVE` (the same value auto-layout uses to avoid placing children in this area). **This area is the sole exception to the usual sibling-overlap check's "parent/child pairs are excluded" rule**, checked individually against each direct child (auto-placed children already avoid this area, so they never trigger it, but explicitly-positioned children don't avoid it, which is where this actually matters).
- **Link label vs. elements/other link labels**: the previous `link_crossing_warnings()` only looked at "does the path (the line) cross something" — it didn't independently check whether the label textbox itself (a rectangle floating at the path's midpoint) overlaps an unrelated element or another link's label. Rectangle-intersection testing between label boxes was added, applying the same ancestor/descendant exclusion rule as the path check.
- **(Additional gap noticed) Link path/label vs. container label**: the usual path check "excludes ancestor containers" (passing through your own parent container's body is expected), but applying that rule as-is would miss a visually obvious defect: cutting straight through an ancestor container's **label text**. For the check against a container's label specifically, the exclusion was loosened so that **only the case where the link's `from`/`to` is that very container** is excluded (ancestors are not excluded).
- `canvas.overlapMargin` applies to all of these. Warning only; no detour or auto-fix.
- `resolve_container_label_position()` is a shared function called from both `render.py` (actual rendering) and `layout.py` (detection), so the label-position resolution logic never drifts between the two (the same design principle established for `link_render_plan()` in §8.9).

### 8.11 CLI redesign, auto-avoidance, lightweight preview, multi-cloud (added during implementation)

Requirement: add CI workflow improvements, icon discoverability, rendering quality, and multi-cloud support together.

- **Redesigned the CLI as a subcommand structure**: changed from the single command `zook <file> -o <out>` to a click Group with `build`/`validate`/`icons list`/`preview` (a breaking change — invocation becomes `zook build <file> -o <out>`). `_load_and_check()` was extracted as shared logic; `build`/`validate` share every non-rendering check (schema, semantic validation, icon resolution, coordinate-range, overlap, link path).
  - `--strict`: exits non-zero if there's even one Warning.
  - `--format {text,json,github}`: machine-readable output for CI integration (`github` produces `::warning::`/`::error::` annotations).
  - This redesign surfaced and fixed a bug: **`validate` wasn't detecting the same Warnings as `build`.** The "unknown icon type" Warning used to be raised only inside `render.py`, so `validate` (which skips rendering) never caught it. This was fixed by extracting it into a pure check on the `layout.py` side, `icon_resolution_warnings()`, called from `_load_and_check()`; the duplicate warning emission in `render.py` was removed.
- **Icon discoverability**: `zook icons list` lists every registered `type`, alias, and group. A `name` field preserving the original casing was added to `IconEntry`/`GroupEntry` for display purposes (the internal lookup key is still lowercased).
- **Auto-placement overlap avoidance** (`_avoid_explicit_overlaps()`): when an auto-placed child overlaps an explicitly-positioned sibling, only the auto-placed side is pushed straight down to avoid it. Just a simple single-axis push (if multiple explicitly-positioned elements are stacked, it pushes multiple times, bounded by `len(explicit)+1`). Explicit-vs-explicit and auto-vs-auto pairs aren't touched (the former is the author's intent; the latter never collides given the existing algorithm). `overlap_warnings()` still runs afterward and flags any overlap this doesn't resolve.
- **Lightweight PNG preview** (`preview.py`): a second renderer that draws the same `Box` tree and `link_render_plan()` output directly with Pillow, with no LibreOffice/PowerPoint involved. It shares `render.py`'s `resolve_container_style()` (newly added — a shared function that resolves frame color, fill, dashing, label position, and corner icon together, extracted from logic that used to be written directly inline in `_add_container_rect()`), so the two renderers can't drift apart on how something should look.
- **Multi-cloud**: `registry.gcp.yaml`/`registry.azure.yaml` were added, along with `MultiRegistry`, which holds multiple `Registry` instances and dispatches based on an element's `provider`. Every existing `resolve_icon`/`resolve_group` call site was updated to pass `element.provider` (`layout.py`/`render.py`). A container's `groups` fall back to the AWS registry when undefined in the provider's own registry (this consistently flows through the same path established in §8.10, including `container_label_rect()` and label-position resolution).

### 8.12 Configurable icon size and font size (added during implementation)

Requirement: allow icon size and font size (for node/container/link labels) to be specified from the YAML.

- **A node's `size`**: shorthand for setting `width`/`height` together (`node.size`). `_measure_node()` resolves it as `element.width or element.size or default_size`, so explicitly setting `width`/`height` per axis wins, with `size` ignored only on that axis (mixing is fine).
- **Label font size, kept proportionally in sync with auto-layout**: added `nodeStyle.labelFontSize` (default 9pt), `containerStyle.labelFontSize` (default 10pt), and `link.labelFontSize` (default 8pt). Simply enlarging the font size while leaving the reserved label area (footprint height, a container's top/bottom padding, a link's label box) unchanged would make text spill out, so these auto-layout reservations now scale by the same ratio.
  - `label_box_height(font_size) = font_size * 2`: 1pt = 4/3 logical units, times a line-height factor of 1.5 (`4/3 * 1.5 = 2`). A node's footprint calculation (`_label_reserve()`) uses this function. At the default (9pt) this gives `18`, matching the old `LABEL_BOX_HEIGHT` constant exactly.
  - `container_label_reserve(font_size) = CONTAINER_LABEL_RESERVE * (font_size / CONTAINER_LABEL_FONT_SIZE_DEFAULT)`: scaled proportionally against the 10pt default.
  - `link_label_size(font_size)`: scales both width and height by `font_size / LINK_LABEL_FONT_SIZE_DEFAULT`, relative to `LINK_LABEL_SIZE = (60, 18)` at the default 8pt.
  - Substituting the default value into any of these reproduces the old fixed constant exactly, so an existing diagram that omits `labelFontSize` (including `example.yaml`/`example-cloud-actors.yaml`) has an identical layout result.
- **Both `render.py`/`preview.py` were updated**: the pptx renderer sets `Pt(font_size)` on each text frame, and also uses `label_box_height()`/`link_label_size()` for textbox dimensions. The PNG preview renderer references the same resolution functions (`node_label_font_size()`/`resolve_container_style().label_font_size`/`link.label_font_size`), so font size and box size never drift between the two renderers.
- Visually confirmed via both LibreOffice rendering and `zook preview` that container labels, node icon+label, and link labels match between the two renderers at both default and enlarged font sizes.

### 8.13 Detecting false edge aliasing in Z-routes (added following an external bug report)

Requirement (external bug report): when two links pass through the same connection point of a shared node (e.g. a container's top-center), the `elbow` Z-route's segments end up collinear and continuous, making two unrelated elements look directly connected. The reported example: in a horizontal layout, two links straddling an intermediate node (an ALB) — `ALB→VPC` and `VPC→S3` — both had `choose_connection_indices()`'s decision (`|dy|>|dx|`) pick the same side of VPC (top-center), so the Z-route's horizontal segments touched and aligned, making it look like a direct ALB→S3 connection.

- **Root cause**: `choose_connection_indices()`/`connector_path()` compute each link's path independently, so there's no way to detect multiple links' paths ending up collinear. The existing `link_crossing_warnings()` only looked at a link **crossing** an unrelated element or label — a case where two links **touch and align** on the same line was out of scope.
- **Detection approach (adopting option 1 from the report)**: added a new function, `link_aliasing_warnings()`. It breaks each link's path (computed via `link_render_plan()`, the same actual-rendering geometry the existing checks use) into segments, and checks every pair of links exhaustively for segment pairs that share an axis (horizontal/vertical), lie on the same coordinate (collinear), and either overlap or touch at even a single point. The key detail is including the single-point-touch case: in the report's example, the two horizontal segments only meet at VPC's connection point (zero-length overlap), yet it still visually reads as one continuous line.
  - `_segment_axis_range()`: normalizes a segment to `('h', y, (x_lo,x_hi))` / `('v', x, (y_lo,y_hi))` (a diagonal segment is out of scope, returning None).
  - `_collinear_overlap()`: on the same axis and coordinate, returns the shared range if `lo <= hi + epsilon` (including touching).
  - Since this detects **alignment**, not **crossing**, it's a separate check from `_segments_intersect()`/`_segment_intersects_rect()` (a perpendicular crossing is not a false positive here).
- Warning only. No automatic fix — shifting the connection point or rerouting (options 2/3 from the report) is not performed, keeping the same "mechanical detection, manual fix on the user's side" policy as the existing overlap checks (the same design decision made in §8.8/§8.10).
- **Verified against a real case**: implementing this detection revealed that the bundled sample `example-cloud-actors.yaml` actually triggered the warning (`user→aws-cloud` and `admin→aws-cloud` both connected to the same point — the left-center of the `aws-cloud` container). Since `connection_point()`'s left/right connection (idx 1/3) always returns the center of that box's own edge by design (settled in §8.2), multiple links can converge on the same point regardless of where the other node sits. The sample was fixed by repositioning `admin` below the VPC (so it connects from the bottom edge instead of the left edge), restoring the existing invariant that "the canonical examples produce zero warnings."
- The `_build()` helper in `tests/test_render_smoke.py` previously only aggregated `icon_resolution_warnings()`, letting `overlap_warnings()`/`link_crossing_warnings()`/`link_aliasing_warnings()` pass through unchecked (i.e. these regression tests weren't actually exercising them). `_build()` was fixed to match the full set of checks the CLI (`_load_and_check()`) actually aggregates.

### 8.14 draw.io Integration (Export, Sync, CI Auto-PR)

Requirement: manage architecture diagrams continuously. Hand-tune a base diagram generated by the tool in (self-hosted) draw.io, then feed those changes back into the YAML.

- **Why draw.io instead of PowerPoint**: a PowerPoint group (container) has a child coordinate system with an offset/scale (`chOff`/`chExt`, §8.4) — resizing a group implicitly scales its children's coordinates. Reading that back out of a pptx and correctly recovering coordinates would require recursively resolving nested group transforms. draw.io's (mxGraph's) containers (`container=1`) keep a child element's coordinates as a plain relative offset from the parent, with no child scaling on resize — confirmed against the official `jgraph/drawio` source (below) — so this trap simply doesn't exist there. On top of that, mxGraph XML is a text format that diffs cleanly in Git, and it can be self-hosted (diagrams never have to leave your own infrastructure).
- **`zook export-drawio`** (`drawio.py: export_drawio()`): converts the `Box` tree to mxGraph XML. No coordinate conversion is needed — `Box.local_x/local_y` (a content position relative to its parent) has exactly the same semantics as mxGraph's child `<mxGeometry>` coordinates (a plain relative offset from the parent), so it's used as-is. Containers get their `parent` attribute set to the actual parent element's id plus `container=1`; a node's label isn't a separate textbox but is handled via the mxCell's own `value` + `verticalLabelPosition=bottom` (a simplification matching draw.io's own convention — unrelated to the footprint calculation used for pptx/preview).
- **Validating the official shape library**: the `Sidebar-AWS4.js` file was pulled directly from the `jgraph/drawio` repository (`dev` branch), and the `resIcon`/`grIcon` identifiers actually in use were confirmed from the source (not guessed), then fed into the `drawioShape` field of the existing AWS registry (26 icons + 7 groups). GCP2/Azure2's identifiers are scattered across multiple files and helper functions, and couldn't be reliably verified within this implementation's time budget, so that was deferred — entries without `drawioShape` fall back to embedding the existing PNG as a base64 data URI (the mechanism is shared across all three providers, so extending to GCP/Azure is future work).
- **`zook sync`** (`drawio.py: sync_from_drawio()`): runs the original YAML through `build_layout()` to compute the "intended auto-layout coordinates" as a baseline, then reads the coordinates of same-id cells from the edited `.drawio` and compares. Only elements with an actual difference get explicit `x`/`y`/`width`/`height` written; untouched elements stay auto-placed. YAML is read/written via ruamel.yaml (round-trip mode), so comments and key ordering are preserved. Unknown cells (id mismatch) and missing cells (possibly deleted) both produce Warnings only — adding/removing nodes/containers, or color changes, are out of scope for syncing (following the same "mechanical detection, manual fix on the user's side" policy established in §8.8/§8.10/§8.13).
- **`.drawio` compression format**: when draw.io itself saves a file, the contents of its `<diagram>` element are compressed by default via `encodeURIComponent → raw deflate → base64`. The format `export_drawio()` writes, on the other hand, is uncompressed (the `<mxGraphModel>` is embedded directly as raw XML child elements). `_diagram_model_root()` can read either form (only the compressed form needed actual implementation — the uncompressed form is already a plain XML child element).
- **CI auto-PR** (`.github/workflows/drawio-sync.yml`): triggered by changes to `**/*.drawio`. It identifies the corresponding YAML via a same-basename convention (`X.yaml` ⇔ `X.drawio`), runs `zook sync`, and — if there's a diff — automatically opens a PR via `peter-evans/create-pull-request`. Opening a PR rather than committing directly avoids conflicting with protected-branch policies.

### 8.15 Explicit connection-side selection + path-length-based auto-selection

Requirement: allow a link's connection side (which edge it exits/enters from: top/bottom/left/right) to be specified explicitly. When unspecified, auto-select it so the path is as short and natural as possible.

- **Keeping the same-axis-pair constraint**: `choose_connection_indices()` continues to only ever return "both ends on the horizontal pair (left/right)" or "both ends on the vertical pair (top/bottom)." This is because `connector_path()`'s elbow implementation (bentConnector3, §8.8) is built assuming both ends exit/enter on the same axis. Supporting an arbitrary combination of sides (a mismatched-axis pair) would require implementing a new single-bend routing scheme; weighing the cost against the benefit, the decision was to keep the existing same-axis-pair constraint for now.
- **`link.fromSide`/`link.toSide`** (new, optional):
  - Both set: used as-is. A mismatched-axis combination (e.g. `fromSide: bottom` + `toSide: left`) is a Fatal error in `validate.py` (detected immediately as a structural contradiction, handled the same as every other Fatal case).
  - Only one set: the side given fixes the axis; the other is auto-selected (reusing just the "pick the other side once the axis is fixed" part of the auto logic below).
  - Both omitted: fully automatic.
- **The fully-automatic selection algorithm (revised)**: the old implementation was an approximation that decided the horizontal/vertical pair purely from `|dx| >= |dy|`. The new implementation computes the **actual rendered path** for both pair candidates (including `connection_point()`'s label-avoidance offset and `connector_path()`'s elbow routing) and compares path length. However, **deciding purely by shortest distance turned out to be unstable**, discovered during implementation: testing against `docs/example.yaml`'s `web-c → bucket` (a pair that visually reads as obviously horizontal), the label-avoidance offset's influence caused the vertical side to win by a mere 2.6%, which then collided with another link's connection side on the same node and newly triggered a false-edge-aliasing warning (§8.13). To fix this, the logic was changed to a hysteresis-based decision: **generally use the dominant axis (whichever of `|dx|`/`|dy|` is larger), and only switch when the other axis's path is shorter by at least `_AXIS_SWITCH_MARGIN` (20%)**. On a near-tie, the dominant axis always wins, so the more intuitive the layout, the more stably the same side gets picked.
- `link_render_plan()` includes this selection logic and is called uniformly from `render.py`/`preview.py`/`link_crossing_warnings()`/`link_aliasing_warnings()`, so the rendered result and the warning detection never drift apart (following the design principle established in §8.9).

## 9. Next Actions

- [x] Build a minimal prototype in python-pptx that hierarchically groups "VPC frame + AZ + icon + label" (`prototype/build_prototype.py`)
- [x] Confirm actual behavior of connector attachment + follow-on-move, and of txBody label injection → txBody turns out to be impossible; settled on a midpoint textbox
- [x] Wire in SVG→PNG conversion (cairosvg) and settle on the right DPI → 4x the displayed pixel count
- [ ] Formal definition of the YAML schema (JSON Schema) → done via `zook.schema.json` (requirements-definition phase; see `README-index.md`)
- [ ] Sourcing and placing the actual icon files (official AWS assets) hasn't started. This prototype used only self-made placeholder SVGs for technical validation, for licensing reasons.

---

*This memo is version 1 of the technical validation and detailed design against the requirements spec. §8.2–8.4/8.6 have been settled through prototype validation.*
