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

- Header: `flowchart <TD|TB|BT|LR|RL>`, or `graph <...>` (the legacy alias). `TD`/`TB`/`BT` (and Mermaid's `v`/`^`) map to a vertical layout, `LR`/`RL` (and `>`/`<`) to a horizontal one. Omitting the header, or just its direction (`flowchart` alone), is treated as vertical
- `;` separates statements, as in Mermaid's grammar: `graph TD;` / `A-->B;` and a one-liner like `graph LR; A-->B; B-->C` both work. A `;` inside a label (`A["x; y"]`, `-->|a;b|`) is part of the label
- Node shapes: `id[label]` (rectangle) / `id(label)` (rounded) / `id{label}` (diamond) / `id((label))` (circle), plus Mermaid's other shapes mapped to the closest of those four — `([stadium])`, `[(database)]` → rounded; `[[subroutine]]`, `>asymmetric]`, `[/parallelogram/]`, `[/trapezoid\]` → rectangle; `{{hexagon}}` → diamond; `(((double circle)))` → circle. A quoted label (`A["text with [brackets] and --> arrows"]`) is taken literally; `:::className` is ignored. An `id` that only ever appears inside an arrow is auto-registered as a rectangle, using the `id` itself as the label; if a node is declared more than once, its last explicit label/shape wins (as in Mermaid)
- Mermaid 11's shape syntax: `id@{ shape: cyl, label: "Orders DB" }` is read like the bracket forms — cylinder/stadium shapes become rounded, `hex` a diamond, every circle variant a circle, and the rest (`doc`, `lean-r`, `notch-rect`, ...) a rectangle. Edge ids (`A e1@--> B`) are accepted, and an edge's own `e1@{ animate: true }` statement is ignored
- Labels: `<br>`/`<br/>` becomes a line break, `#quot;`/`#35;`-style entities are decoded, and a markdown string (`` "`**bold** text`" ``) keeps its text without the markers
- Arrows: `-->`, `---`, `<-->`, `-.->`, `-.-`, `==>`, `===`, `<==>`, `--x`, `--o`, `x--x`, `o--o` and longer forms (`---->`, `-..->`). Arrowheads (`>`, `x`, `o`) become zook arrows at that end; dotted/thick lines are drawn like a plain line (the line style isn't reproduced). `~~~` (invisible link) adds no line. A label can be given as `-->|label|` (spaces allowed before the pipe) or as `-- label -->` / `== label ==>` / `-. label .->`. `A & B --> C & D` draws one link per pair, and arrows chain on one line (`A --> B --> C`)
- `subgraph <id>[<Title>]` … `end`: nesting is supported. Without `[<Title>]`, the subgraph's own text is its title, as Mermaid draws it (`subgraph Backend`, `subgraph "AWS Cloud"`, `subgraph バックエンド`). `direction LR` (etc.) inside a subgraph sets that subgraph's own layout direction. A node belongs to the first subgraph *closed* that mentions it (so an inner subgraph wins over its parent), and a node mentioned only at the top level stays there — so `A --> B` followed by `subgraph S` … `B` … `end` puts `B` in `S`, as Mermaid does. A link may point at a subgraph id, even one declared later
- `end` closes a subgraph only in lowercase, as in Mermaid — `End`/`END` can be used as a node id
- `%% ...` comment lines are ignored, and so are a surrounding ```` ```mermaid ```` code fence, `---` front matter, a multi-line `%%{ ... }%%` directive, and `accTitle:`/`accDescr:` accessibility text
- A statement zook can't read is an error naming the line — it never silently drops the statement
- **Branching graphs are laid out by rank.** Where the links in a scope (the top level or a subgraph) fan out or merge, each node is placed by how far along the links it sits, and nodes of the same rank are set side by side in a borderless row (a column, for `LR`), ordered to reduce crossings. A plain chain stays in one line, in the order its links run (so `J --> K` written before `F --> J` still gives F, J, K); separate chains keep their source order. The generated top-level container has no frame

## Known Limitations (v1)

- The rank layout is simple (longest path, one ordering pass): with many crossing links, `zook doctor` — or the [draw.io integration](drawio-sync.md) loop — can still be needed afterward
- Dotted and thick lines are drawn identically to a plain line — the line-style distinction isn't reproduced; `x`/`o` arrowheads are drawn as ordinary arrowheads
- Shapes beyond rectangle/rounded/diamond/circle are approximated by the closest of those four
- Style/interaction directives such as `classDef`/`class`/`style`/`linkStyle`/`click` are ignored
- A top-level `direction` statement is ignored, as in Mermaid (the header sets the graph's direction; `direction` applies inside a subgraph)
- A Mermaid diagram type other than `flowchart`/`graph` (e.g. `sequenceDiagram`) produces an error saying so

## About Plain Shape Nodes

The nodes `from-mermaid` generates aren't icons — they're "a shape with the label drawn inside it," via `nodeStyle.shape` (`rect`/`rounded`/`diamond`/`circle`). This isn't a Mermaid-conversion-only feature; it's a general-purpose node style you can use directly in hand-written YAML too. See the [YAML Input Guide](yaml-guide.md) for details.
