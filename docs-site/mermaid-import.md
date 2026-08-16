# Mermaid Flowchart Import

[🇯🇵 日本語版](/zook/ja/mermaid-import/){ .md-button }

A diagram written in [Mermaid](https://mermaid.js.org/)'s `flowchart`/`graph` notation can be converted into zook YAML. A Mermaid flowchart's structure — nodes, arrows, nested groups — maps almost directly onto zook's own underlying engine of containers, nodes, and links, so once converted it plugs straight into the existing `validate`/`build`/`export-drawio`/`sync` pipeline.

Only `flowchart` is supported. A diagram like `sequenceDiagram`, which draws vertical lifelines and time-ordered messages, needs an entirely different rendering engine and is currently out of scope.

## Basic Flow

```bash
zook from-mermaid diagram.mmd -o diagram.yaml
zook validate diagram.yaml
zook build diagram.yaml -o diagram.pptx
```

`from-mermaid` runs the converted YAML through the same checks as `build`/`validate` (schema, overlaps, link paths, etc.) before writing it out, so Fatal/Warning issues surface at this point. `--format json`/`github` are supported too.

## Supported Notation

- Header: `flowchart <TD|TB|BT|LR|RL>`, or `graph <...>` (the legacy alias). `TD`/`TB`/`BT` map to a vertical layout, `LR`/`RL` to a horizontal one. Omitting the header is treated as vertical
- Node shapes: `id[label]` (rectangle) / `id(label)` (rounded) / `id{label}` (diamond) / `id((label))` (circle). An `id` that only ever appears inside an arrow (with no shape declared) is auto-registered as a rectangle node, using the `id` itself as the label
- Arrows: `-->` (with arrowhead), `---` (no arrowhead), `<-->` (bidirectional), `-.->`/`==>` (dotted/thick — not visually reproduced, treated the same as `-->`). A label can be attached with `-->|label|`. Chaining multiple arrows on one line (`A --> B --> C`) is also supported
- `subgraph <id>[<Title>]` … `end`: nesting is supported. The title is optional
- `%% ...` comment lines are ignored

## Known Limitations (v1)

- **Node/subgraph ordering directly reflects the order they first appear in the source.** No graph-layout algorithm minimizes edge crossings, so a complex diagram may need hand-tuning afterward. Use the [draw.io integration](drawio-sync.md) loop to adjust layout post-generation
- The (pipe-less) label notation `-- label -->` isn't supported. Use `-->|label|` instead
- Dotted (`-.->`) and thick (`==>`) lines are drawn identically to a plain arrow (`-->`) — the line-style distinction isn't reproduced
- No special handling for escaping quotes or nested brackets inside a label
- Style/interaction directives such as `classDef`/`class`/`style`/`click` are ignored
- A Mermaid diagram type other than `flowchart`/`graph` (e.g. `sequenceDiagram`) produces an error saying so

## About Plain Shape Nodes

The nodes `from-mermaid` generates aren't icons — they're "a shape with the label drawn inside it," via `nodeStyle.shape` (`rect`/`rounded`/`diamond`/`circle`). This isn't a Mermaid-conversion-only feature; it's a general-purpose node style you can use directly in hand-written YAML too. See the [YAML Input Guide](yaml-guide.md) for details.
