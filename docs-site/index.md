# ZOOK

[🇯🇵 日本語版](/zook/ja/){ .md-button }

A CLI tool that generates PowerPoint (.pptx) slides from a cloud architecture definition written in YAML.

Diagrams are managed as code in Git, so changes are reviewable — while the final output is a form a human can freely hand-edit in PowerPoint.

```yaml
version: "1.0"
canvas:
  aspectRatio: "16:9"
elements:
  - kind: container
    id: vpc-main
    type: vpc
    label: "Production VPC"
    children:
      - kind: node
        id: web
        type: EC2
        label: "WebServer"
      - kind: node
        id: db
        type: RDS
        label: "Primary DB"
links:
  - from: web
    to: db
    label: "3306"
```

```bash
zook build diagram.yaml -o diagram.pptx
```

## Why zook

- **Diagrams as code** — YAML is text, so it reviews cleanly as a Git diff. Existing diagrams-as-code tools are often constrained on direct PowerPoint output or precise aspect-ratio control, and running an extra conversion step tends to mean compromises and ongoing maintenance cost. zook unifies YAML → PPTX into one pipeline.
- **"Good enough" quality, on the assumption of hand-editing afterward** — rather than a perfect automatic layout, output prioritizes being immediately hand-editable in PowerPoint.
- **A vocabulary that's easy to extend** — a service's `type` isn't fixed by the schema; the [icon registry](icons.md) is the source of truth for vocabulary. Adding a new service is just appending to the registry, with no code changes needed.
- **Designed with LLM generation in mind** — an input spec strictly formalized via JSON Schema, prioritizing unambiguous machine (LLM) generation and parsing over human readability.

## Key Features

| Feature | Overview |
|---|---|
| Multi-cloud | Ships with built-in registries for AWS/GCP/Azure. Set `provider` per node to mix providers within one diagram |
| Hierarchical containers | Nested structures like Cloud → VPC → AZ → subnet, expressed via a `container`'s recursive `children` |
| Cloud boundaries | `type: cloud` draws the cloud boundary itself as a frame, with a provider-specific brand color and badge icon |
| Actor icons | Place actors like User/Admin/Developer/Client as nodes to represent who accesses the system |
| Auto-layout | Elements with no coordinates auto-arrange via grid/horizontal/vertical. Can mix with explicit coordinates — auto-placed elements automatically shift to avoid overlapping an explicitly-positioned sibling |
| Connectors | Connect services with arrow-tipped lines. Labels (e.g. port numbers) supported. Links to containers also work. A diagonal connection auto-switches to a right-angle bend |
| Explicit connection sides | `link.fromSide`/`toSide` explicitly picks which side (top/bottom/left/right) a connector attaches to. Auto-selected by comparing actual path length if omitted |
| Explicit routing (waypoints) | `link.waypoints` specifies intermediate points (absolute coordinates) to draw an arbitrary polyline path — for detouring around obstacles or drawing an L-shaped route. Disables `style`'s auto-routing and the connection-side axis-match rule when set |
| Label-avoiding connections | An arrow leaving a labeled node in the same direction as the label attaches outside it, avoiding the label |
| Icon resolution | Resolves a service name to an icon, alias-aware and case-insensitive. An unknown service continues with a placeholder plus a warning. List everything with `zook icons list` |
| Registry overrides | Layer your own icon/style definitions on top of the built-in registries |
| Overlap detection | Mechanically detects — from the computed coordinates — whether sibling elements, a container's label text, an arrow's path, or a link's label overlap each other, and reports a Warning. `overlapMargin` also lets you flag near-misses |
| Automatic collision resolution | `zook doctor` auto-resolves in four stages: nudge element overlaps apart, assign connection sides to fix link crossings/apparent-direct-connections, displace an obstacle that still blocks a path, and detour a link with waypoints around an obstacle that can't move (each stage only ever applies a change that doesn't make things worse). Defaults to a dry run (proposal only); write back to the YAML with `--fix`/`-o` (see the doctor section in [Usage](usage.md)) |
| Structural diff | `zook diff` compares two diagrams **by meaning**. Elements matched by id, links by id/endpoints — reports only additions, removals, **moves between containers**, field changes, and link/canvas changes. Reordering children or writing out a default value explicitly produces no noise (see the diff section in [Usage](usage.md)) |
| Size/font-size tuning | A node's `size` sets icon size; `labelFontSize` (node/container/link) sets label font size individually. The space auto-layout reserves for labels scales proportionally too |
| Lightweight preview | `zook preview` gives an instant PNG check with no PowerPoint or LibreOffice needed |
| draw.io integration | `zook export-drawio`/`sync` reflect position/size changes made in draw.io back into the YAML — built for continuous diagram management (see [draw.io integration](drawio-sync.md)) |
| Mermaid import | `zook from-mermaid` converts Mermaid `flowchart`/`graph` notation to YAML (see [Mermaid flowchart import](mermaid-import.md)) |
| Plain shape nodes | Draw a node as a rectangle/rounded-rectangle/diamond/circle with an inline label instead of an icon (`style.shape`) — a general-purpose feature the Mermaid importer uses internally |
| CI/CD-friendly | Structural errors (schema violations, duplicate ids, dangling link references) exit non-zero. `--strict` can gate on Warnings too. `--format json`/`github` gives machine-readable output. `zook validate` offers a fast check with no rendering |

## Documentation

- [Installation](installation.md) — setup steps
- [Usage](usage.md) — CLI commands and error handling
- [YAML Input Guide](yaml-guide.md) — how to write a diagram (containers, nodes, links, layout)
- [Icon Registry](icons.md) — the service vocabulary and icon mechanism, and how to customize it
- [draw.io Integration](drawio-sync.md) — the draw.io export/sync workflow for continuous diagram management
- [Mermaid Flowchart Import](mermaid-import.md) — converting from Mermaid's `flowchart`/`graph` notation
- [Design Notes](design-notes.md) — implementation approach for pptx generation (grouping, connectors, coordinate system)
- [Known Limitations](limitations.md) — what's out of scope as of v1

The detailed requirements, JSON Schemas, and design-validation source material live in the repository's [`docs/`](https://github.com/taka-sho/zook/tree/main/docs) directory.
