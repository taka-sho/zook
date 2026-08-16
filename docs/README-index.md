# Architecture Diagram Generator — Design Package Index

**Version:** 1.0
**Date:** 2026-07-25
**Phase:** Requirements & design complete → handed off to implementation (Claude Code)

This repository package is the requirements/design-phase deliverable for a tool that generates **PowerPoint** architecture diagrams from YAML, initially for AWS (multi-cloud later). Implementation and prototyping are assumed to happen on the Claude Code side; treat this package as the "single source of truth" for decisions made.

---

## 1. Deliverables

| # | File | Type | Role |
|---|---|---|---|
| 1 | `architecture-diagram-tool-requirements.md` | Requirements spec | Purpose, scope, personas, functional/non-functional requirements |
| 2 | `detailed-design-pptx.md` | Detailed design memo | Decisions on grouping, connectors, and coordinate systems in python-pptx |
| 3 | `yaml-spec.md` | YAML input spec | Structure, coordinate system, layout, links, and error policy for the input YAML |
| 4 | `zook.schema.json` | JSON Schema | Format definition for the input YAML (source of truth for validation) |
| 5 | `example.yaml` | Sample | Input example covering the main features (validated) |
| 5b | `example-cloud-actors.yaml` | Sample | Input example including an AWS Cloud boundary + User/Admin actors (validated) |
| 6 | `icon-registry-and-vocabulary.md` | Spec | Policy for service vocabulary and icon resolution |
| 7 | `icon-registry.schema.json` | JSON Schema | Format definition for the icon registry |
| 8 | `registry.aws.yaml` | Sample | Initial registry for AWS (validated) |
| 8b | `registry.gcp.yaml` | Sample | Initial registry for GCP (validated; added during the implementation phase) |
| 8c | `registry.azure.yaml` | Sample | Initial registry for Azure (validated; added during the implementation phase) |

Recommended reading order: **1 → 3 → 4/5 → 6 → 7/8 → 2** (requirements for the big picture, then the input spec, then the pptx details right before implementation).

---

## 2. Summary of Core Decisions

### Product
- Input **YAML**, output **PowerPoint (.pptx)**, **1 YAML = 1 slide**.
- Primary purpose: manage diagrams as code (reviewable via Git diffs), hand-edit in PowerPoint afterward, and support semi-automated generation by an LLM.
- Users: PMs/sales/SREs/engineers. Frequency: roughly weekly to a couple of times a month. Quality: "good enough" is fine, since hand-editing afterward is assumed.

### Data Model (Abstraction)
- Abstracted into two concepts: **container** (a frame) and **node** (an icon). VPC/AZ/subnet etc. are all containers that differ only in `type`.
- Hierarchy is expressed recursively via nested `children`. Multi-cloud is extended through `provider` + `type`.
- Links are optional. Omitting them yields "no lines, elements just placed in an area."

### Coordinates & Layout
- Logical units. 16:9 = 1280×720, 4:3 = 960×720 (origin at top-left). The EMU conversion table is in `yaml-spec.md §2`.
- `x`/`y` give absolute placement; omitting them triggers auto-layout. The two can be mixed. `x`/`y` must be set together.

### PowerPoint Implementation (python-pptx)
- **Hierarchical grouping**: VPC → AZ → (icon + label). `add_group_shape` with a 1:1 mapping of chOff/chExt to off/ext.
- **Connectors**: shapes are connected via `begin_connect`/`end_connect`, so they follow the shapes when moved. Limited to rectangles for stable behavior.
- **Label tracking**: inject `txBody` into the connector where possible (first choice); fall back to a midpoint textbox where not.
- **Icon embedding**: **PNG raster** by default (converted via cairosvg, suited to CI/CD). EMF vector is optional.

### Icons & Vocabulary
- `type` is not fixed as an enum. **The registry is the source of truth for vocabulary.** An unknown `type` produces a Warning plus a placeholder.
- Initial built-in Tier 1 = 26 services (22 AWS services + 4 General actors: User/Admin/Developer/Client). Additions only require appending to the registry (no schema change needed).
- Containers also ship with 7 built-in frame styles, including `cloud` (a boundary, with a corner icon).
- Resolution is **alias-aware and case-insensitive**. **Overridable** via a user registry.
- AWS icons are updated quarterly → releases are recorded in `iconSet`, keeping keys stable while swapping files.
- **Multi-cloud support** (added during the implementation phase): built-in registries for GCP (19 services) and Azure (18 services) were added, along with a `MultiRegistry` that switches the resolution target based on an element's `provider`. A container's `groups` fall back to the AWS registry when undefined in the provider's own registry. Check with `zook icons list`.

### Error Policy
- Structural breakage (schema violation, duplicate id, dangling link target) = **Fatal, stops immediately** (non-zero exit for CI/CD; `--strict` can additionally treat Warnings this way).
- Minor drawing issues (unknown icon, out-of-canvas coordinates, elements/labels overlapping) = **Warning, continues**. Coordinate-based overlap detection applies the same logic regardless of whether an element was placed explicitly or automatically.
- Only when an auto-placed child overlaps an explicitly-positioned sibling is the auto-placed side pushed to avoid it (added during the implementation phase). All other overlaps are detected only, not auto-corrected.
- The CLI is organized into subcommands: `build` (generate), `validate` (check only, no rendering), `icons list` (inspect vocabulary), `preview` (lightweight PNG), `export-drawio`/`sync` (draw.io round-trip, added during the implementation phase) (all added during the implementation phase).

---

## 3. What's Been Verified

- `zook.schema.json` conforms to Draft 2020-12. `example.yaml` validates against it. Confirmed that invalid input (x alone, an invalid id, an unknown kind, an out-of-range aspect ratio, extra fields) is rejected.
- `registry.aws.yaml` (26 icons + 7 group styles) validates against `icon-registry.schema.json`. 46 alias lookup keys, no collisions.

---

## 4. Handoff to the Implementation Phase (Claude Code)

### Items Settled by Prototyping (verified 2026-07-25)

`prototype/build_prototype.py` was written and visually verified with python-pptx 1.0.2 + cairosvg + LibreOffice headless (`soffice --convert-to pdf` → `pdftoppm`). See `detailed-design-pptx.md` §8.2–8.4/§8.6/§8.7 for details.

- **Connection point indices**: `idx 0 = top-center / 1 = left-center / 2 = bottom-center / 3 = right-center` (starting at top, counter-clockwise). This is definitive, since python-pptx's own source code computes the actual coordinates using this mapping.
- **Connector labels**: confirmed that `p:cxnSp` cannot carry a `txBody` under the OOXML schema (injecting one is impossible). Settled on the midpoint-textbox approach.
- **Icon PNG resolution**: rasterize at **4x** the displayed pixel count (based on 1 logical unit = 9525 EMU = 1px at 96dpi).
- (Secondary finding) A group's 1:1 chOff/chExt mapping is handled automatically by python-pptx's `recalculate_extents()`, so the custom helper the design memo assumed would be needed turns out to be unnecessary.
- (Secondary finding) Getting a container's label to appear at the top-left requires explicitly setting `text_frame.vertical_anchor = MSO_ANCHOR.TOP` (the default is vertically centered).

### Work Remaining for Implementation
- **Sourcing and placing actual icon files**: obtain official assets → convert to PNG → place per the `file` paths in `registry.aws.yaml`.
- Wire in YAML validation: **always validate** against `zook.schema.json` before rendering.
- Implement the logical-unit → EMU conversion (the table in `yaml-spec.md §2`).
- Ship auto-layout with sensible defaults for v1; more sophisticated overlap avoidance can wait for a later version.
- Wire up the CLI and CI/CD integration (YAML → PPTX, non-zero exit on Fatal).

### Principles to Preserve
- Treat the two JSON Schemas as the **single source of truth for validation**.
- Treat the registry as the **single source of truth for vocabulary** (never hard-code types in the implementation).

---

## 5. Candidates for Future Versions (Out of Scope)

- Advanced link routing (pathfinding that detours around obstacles; currently only a simple push-apart between auto-placed and explicitly-positioned elements).
- Standardizing the EMF vector path (handling the Inkscape dependency).
- Actually sourcing and bundling official AWS/GCP/Azure icon assets (currently only self-made placeholders).
- Broader Tier 2 service coverage (300+ per cloud).
- An MCP server (semi-automating requirements → YAML generation → diagram output).

---

*This index summarizes the requirements/design phase. Reflect any subsequent changes in both the individual spec files and this index.*
