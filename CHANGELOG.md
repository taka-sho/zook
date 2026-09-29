# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CI runs the suite on Python 3.10 and the latest release, fails on any read
  or write in zook that depends on the locale's encoding, builds the wheel
  and uses it from outside the repository, and runs the tests from the
  sdist; releases run all of it first and check the tag matches the
  version. The docs site is built on pull requests too; Dependabot watches
  the Actions and pip dependencies. Badges are updated even when the tests
  fail, and a concurrent push no longer turns CI red.
- CI now measures branch coverage on every push/PR and fails the build if it
  drops below 85% (`pytest --cov=zook --cov-fail-under=85`). The README's
  coverage and test-result badges are generated from that same run's real
  output (`scripts/update_badges.py`, committed to `.github/badges/` on
  pushes to `main`), not a third-party dashboard.
- Structured output for tools and AIs: under `--format json` every Warning
  also appears in `details` with a stable `code` (`element-overlap`,
  `unknown-type`, `link-crosses-element`, ...) and the `elements`/`links`
  it concerns (doctor: `remainingDetails`), and an error comes with
  `errorCode` and `errorDetails` (each schema violation's path and pointer,
  a YAML error's line and column, an unknown link endpoint's close
  matches). The text fields are unchanged. A container drawn off the slide
  (`fit: none`) is one Warning, not one per element inside it; `diff`'s
  JSON has a `status` like every other command's.
- Link line styles: `color` (#RRGGBB), `line` (`solid`/`dashed`/`dotted`)
  and `width` (pt, arrowheads scale with it), in the .pptx, the preview and
  the .drawio. Mermaid import keeps a dotted link dashed and a thick one
  thick, reads `linkStyle` (stroke colour, width, dasharray), and ranks the
  layout with invisible `~~~` links too.
- `zook --version`, and `python -m zook` as an alternative entry point.
- Everything an AI agent needs now ships in the package, so zook works when
  installed with `pipx`/`uv tool` instead of cloned: `zook guide [TOPIC]`
  prints the workflow (AGENTS.md's agent part), the YAML spec, the usage,
  limitations, Mermaid and draw.io pages; `zook schema [--icon-registry]`
  the JSON Schema; `zook patterns list|show` the reference architectures
  (moved from `docs/patterns/` into `src/zook/data/patterns/`); and
  `zook init [PATH] [--pattern NAME]` writes a starter diagram.
- A Tier-2 vocabulary: 77 AWS, 39 GCP and 40 Azure types (from 26/19/18) -
  WAF, CloudWatch, Secrets Manager, KMS, Step Functions, Kinesis, Internet/
  Transit Gateway, VPC endpoints, Bedrock, Spanner, Vertex AI, App Service,
  Application Gateway, ... - with verified draw.io shapes for AWS; generic
  icons (Server, Database, Internet, Mobile, OnPremises, SaaS); and AWS
  `publicSubnet`/`privateSubnet`/`securityGroup`/`autoScalingGroup`/
  `corporateDataCenter` frames. Actors and generic icons work under any
  provider (a GCP diagram's `User` used to be an unknown type).
- `--registry` can be given more than once; each file layers onto the
  provider it declares, in order (a second one used to replace the first
  silently).
- SVG icon files (e.g. Azure's official icons) in a `--registry` are
  rasterized with cairosvg for the .pptx, the preview and the .drawio.
- `preview` accepts `--format` and `--strict` like `build`.
- A `--registry` file is validated against `icon-registry.schema.json`, as
  the docs always said; a malformed one is a Fatal naming the file and field
  instead of an internal `KeyError`/`AttributeError`. `provider` (default
  `aws`) and `icons` stay optional, so a groups-only override still works.
- Mermaid import reads the whole flowchart edge and node syntax: dotted/thick/
  `x`/`o`/invisible/long arrows, `-- text -->`-style labels, `A & B --> C`,
  every node shape (mapped to the closest zook shape), quoted labels with
  brackets or arrows inside, `:::class`, `<br>`, `#quot;`-style entities and
  markdown strings. A branching graph is laid out by rank (a fork's arms side
  by side instead of stacked in one column with links running through
  nodes), and subgraph membership / node labels follow Mermaid's own rules (a
  node first used in an edge and then listed in a subgraph goes into it; a
  later explicit label wins). The generated top-level container has no frame.
  Mermaid 11's `id@{ shape: ..., label: ... }` node syntax and edge ids
  (`A e1@--> B`) are read too; a chain written out of order (`J --> K`
  before `F --> J`) is laid out in the order its links run.
- Mermaid import: `;` as a statement separator (`graph TD;` / `A-->B;`, as in
  GitHub's own examples), a header without a direction (`flowchart`), and
  `direction <TD|LR|...>` inside a subgraph. More non-flowchart diagram types
  (`architecture-beta`, `C4Container`, `block`, `kanban`, ...) are rejected
  with an explicit error instead of being misread as a flowchart.

- `canvas.fit` (default `shrink`): a diagram that doesn't fit the slide is
  scaled down uniformly, text included, and centred - instead of spilling off
  the slide with a warning per element. A shrink below 70% is a Warning,
  naming any explicitly positioned element outside the canvas (the usual
  cause: one mistyped coordinate). Line widths and arrowheads keep their
  size. `fit: none` keeps the old behaviour.
- `canvas.layout` (`direction`/`columns`/`gap`) arranges the top-level
  elements, which used to be a fixed grid.

### Changed

- Labels are measured from their text (full-width CJK characters - and the
  arrows, circled numbers and dashes Japanese fonts draw full width - count
  as 1 em, Latin letters roughly half; a word too long for the line starts a
  new line before it is broken): a long node label widens its footprint
  up to 150 units and then wraps, explicit line breaks are honoured, and
  every line is reserved - so a long, multi-line or Japanese label no longer
  runs into the arrow, frame or row below it while every check says "clear".
  `labelPosition: right` reserves the label's width beside the icon; a
  container reserves its label band (its registry default label too, e.g.
  "VPC") at the top, or at the bottom for `bottom-left`, and an auto-sized
  container widens for its label. Plain-shape nodes grow to fit their text,
  as it wraps inside the shape's own text area (the middle half of a diamond,
  the inscribed square of a circle), and widen so their longest word isn't
  broken; link labels are sized from their text. Label text boxes no longer
  lose PowerPoint's 0.1in side insets.
- A grid's columns/rows are sized per column/row rather than one uniform cell
  sized to the largest element (an actor next to a VPC pushed the VPC off the
  slide); the top-level grid picks the column count that fits the slide, with
  a 64-unit gap. Rows/columns of nodes are aligned on their icons' centres.
- Automatic connection sides prefer the axis whose route runs through fewer
  other elements.
- Both ends of a link on the same side (`top`/`top`, ...) is routed as a U
  around the outermost endpoint (it used to be modelled as a Z through the
  endpoints' own icons, and drawn differently by each viewer).
- A link label that would cover an end of its link (the arrowhead of a short
  link between neighbouring icons) or one of its endpoint icons moves beside
  the line instead - just beside it, or past the endpoint icons when it is
  wider than the gap between them. A new Warning reports a link label that
  still covers one of its own endpoints.
- A link from an element to itself (Mermaid's `B -->|retry| B`) is drawn as
  a loop round one of its corners; a link between a container and an
  element inside it runs straight to the nearest point of the frame; links
  joining the same two elements (both directions included) are drawn side
  by side instead of on one line with their labels stacked. All three used
  to be drawn straight through the elements' own icons.
- Each icon node is one PowerPoint group (icon + label) named by its element
  id, so the label moves with the icon; the icon's alt text is its label and
  type instead of the icon file's name.
- A connector end is glued only where the planned point is the middle of a
  side of the glued shape - the label box, for an end placed past the
  node's own label - so LibreOffice (on open) and PowerPoint (after a move)
  redraw it where it was planned; it used to snap back to the icon's edge
  and run through the label.
- An auto-placed element pushed down past an explicitly positioned sibling
  pushes on any auto-placed sibling it then lands on.
- Links that share a trunk at a common endpoint (fan-out from, or fan-in to,
  the same point) are no longer reported as false edge aliasing.
- `preview` draws text at the size PowerPoint does (it was about half), with
  a CJK-capable system font (`ZOOK_PREVIEW_FONT` to choose one; a Warning if
  none is found and the diagram has CJK text, or if the chosen file can't be
  loaded or has no CJK glyphs - it is then ignored), the same wrapped lines
  and label boxes as the .pptx, and a container's corner badge. A line whose
  preview font runs wider than its box is drawn slightly smaller; line
  widths, arrowheads and container borders are drawn at their .pptx size.

- Redefining a built-in type or container type in a `--registry` merges
  field by field (overriding `vpc`'s colour used to drop its label and
  draw.io shape), and the entry's aliases follow it (`ALB` kept the old icon
  when `ELB` was overridden). A user alias that names another type (`S3`)
  is ignored with a Warning instead of silently taking it over. A registry's
  `provider` must be `aws`/`gcp`/`azure`/`custom`, the names a diagram can
  select.
- Link ids must be unique and must not reuse an element id (Fatal):
  export-drawio wrote them as duplicate mxCell ids, which draw.io decodes
  one over the other.
- A `type` is looked up ignoring case, spaces, hyphens, underscores and dots
  (`API Gateway`, `route-53`), and an unresolved one's Warning says how to
  fix it: the close matches (`did you mean 'Lambda'?`) or the provider that
  has it (`set provider: gcp`). An unknown container type is now a Warning
  (it silently became a grey frame), with the closest container type.
- Schema errors are reported at the exact path of each violation. `element`
  now selects the container or node schema by `kind` (if/then) instead of
  `oneOf`, which reported a mistake deep inside a container against the whole
  top-level element with the other branch's complaint (e.g. "'children' was
  unexpected"). An unquoted value YAML reads as a number or boolean
  (`aspectRatio: 16:9` -> 969, `label: no` -> false) gets a hint to quote it.
- `diff` exits **2** (not 1) on an invalid input, so `--exit-code`'s 1 always
  means "the diagrams differ"; the error names which file failed.
- `diff` reports a reorder of auto-placed siblings (it moves them; it used to
  be "No structural differences"), pairs links between the same two
  elements identical-first (deleting the first of two was reported as "the
  first changed, the second removed"), treats a link that only gained an id
  as a change of its id, ignores style values and sizes equal to their
  defaults, prints each link's id and label, and orders its output
  deterministically.
- `doctor -o PATH` always writes `PATH`, even when there was nothing to fix
  (a byte-for-byte copy then; `--fix` still leaves a clean file untouched).
- `doctor` and `sync` read a file with the same YAML interpretation as
  `validate`/`build`. They used to lay out and edit the YAML 1.2 reading, so
  an unquoted `16:9` passed doctor while validate rejected it, `x: 0600` was
  600 for doctor but octal 384 for build, and `label: 1e3` failed doctor
  while validate accepted it. Such an ambiguous scalar is now written back in
  its unambiguous form (`384`, `'1e3'`) when doctor/sync rewrite the file.
- A missing, unreadable or directory input path, `--registry` path or `-o`
  path is reported in the command's own `--format` and exits 1 (2 for
  `diff`); it used to be a click usage error (plain text, exit 2).
- `preview -o` must be a `.png` path (Pillow used to pick another format
  from the extension).
- Packaging: the version has one source (`zook.__version__`); every data
  file under the package ships (the list named each provider); the sdist
  includes what its tests need; `setuptools>=77` (for the PEP 639 license
  field) and `click>=8.2` (what the tests use). The JSON Schemas' `$id` is
  their real URL, so an editor's YAML language server can validate a
  diagram as it is typed; README links work on PyPI.
- A label whose box was sized to its own text could still wrap one letter
  onto a second line (`async` -> `asyn` / `c`) through float rounding.
- Mermaid import: a statement zook can't read is an error naming the line;
  unsupported edges used to drop the whole statement, nodes included,
  silently with status ok. A top-level `direction` statement is ignored, as
  Mermaid does.

### Changed (doctor)

- `doctor` judges every change by a *weighted* total of the Warnings it can
  influence (an overlap or a link doubling back through its own endpoint
  weighs more than a link crossing a container frame), including off-slide /
  shrink-to-fit Warnings; every stage - element separation included, which
  used to be unverified - is kept only if that total strictly drops. It used
  to count all Warnings equally, so it could route a link straight through
  its own endpoint's icon, or push an element off the slide or out of its
  fixed-size container, and call the result "fixed".
- Elements are moved the shortest way (right/down/left/up) that stays inside
  their container and on the slide; a child outside its container is pulled
  back in.
- The stages repeat while a round improves, so a second `doctor` run on its
  own output changes nothing.
- Stage 2 scores candidate connection sides incrementally: a 30-link,
  crossing-heavy diagram went from ~7 minutes to a few seconds.
- Stage-4 detours are right-angled; they used to add diagonal segments.
- The report lists `pinned` elements (auto-placed elements given an explicit
  x/y at the spot they already occupied), so a dry run tells the whole truth
  about what `--fix` writes.
- `doctor --strict` exits non-zero when anything is left in `remaining`.
- `doctor --fix`/`-o` and `sync` keep the file's own indentation style and
  write integer coordinates as integers; `sync` with nothing moved in draw.io
  no longer rewrites the YAML (no more empty PRs from the drawio-sync
  workflow).
- Links with author-set `waypoints` are never re-sided by doctor.

### Changed (draw.io)

- `export-drawio` carries the diagram's styling: container frame overrides
  (colour, width, label position/size - the same precedence the .pptx uses,
  on top of the official draw.io group shapes), node label position and size,
  each link's connection sides and route (a diagonal link is exported as the
  orthogonal route the .pptx draws; same-side U routes and waypoints as
  bend points), and the background colour. Each style key is written once.
- `sync` compares the .drawio against what was *exported* (recorded in a
  hidden cell), so a .drawio exported before a YAML change no longer pins
  every element back to its old position; after writing the edits it pins
  whatever else drifted (moving one auto-placed element used to re-pack its
  siblings), so the YAML lays out exactly as the .drawio showed. Edited link
  bend points are written back as `waypoints`. Moving an element into another
  container, relabelling, reconnecting and adding links are reported as
  Warnings instead of being silently ignored (or, for re-parenting, written
  relative to the wrong container). Shapes draw.io wrapped in `<UserObject>`
  are synced; in a multi-page file the page zook exported is used; a file
  with no `<diagram>` (a .drawio.svg/.png) is an error instead of exit 0.
- The drawio-sync workflow syncs every .drawio added or modified by a push -
  all its commits, file names with spaces included - skips deleted ones,
  reports a failing sync as an annotation, and documents how to use it in
  another repository.

### Fixed

- Every command reports a malformed input the same way it reports a Fatal —
  `{"status": "error", ...}` under `--format json` — instead of a Python
  traceback with nothing on stdout: YAML syntax errors (with line and
  column), non-UTF-8 files, missing/unwritable output paths, malformed
  `.drawio` files, recursive YAML aliases. Unexpected internal errors are
  reported in the same shape (`ZOOK_DEBUG=1` prints the traceback).
- A document that isn't a mapping - typically a `.drawio` given where the
  YAML goes (`zook sync d.drawio d.yaml`) - is reported as such, with a hint,
  instead of as a schema error quoting the whole XML.
- An icon file that can't be read as an image is a Warning and the
  placeholder is drawn; an SVG (or any non-image) crashed `build` with a
  traceback while `validate` said ok.
- A mapping key written twice (e.g. two `links:` blocks) is a Fatal error;
  it used to silently keep only the last one, dropping connectors.
- The bundled registries are read as UTF-8 regardless of locale; every
  command except `diff` crashed on start-up under a non-UTF-8 locale such as
  Japanese Windows (cp932).
- `doctor`'s text and github reports crashed with a `TypeError` (after
  `--fix` had already written the file) when a container moved and its
  auto-placed children followed it.
- `export-drawio` produced invalid XML for a label containing `"`, and
  embedded PNG icons (every GCP/Azure icon) as `data:image/png;base64,...`,
  which draw.io's `;`-separated style parser cuts apart; labels are now also
  HTML-escaped for `html=1` cells, with newlines kept as `<br>`.
- `sync` rejects a compressed `<diagram>` that can't be decoded or inflates
  past 50 MB, instead of crashing or exhausting memory.
- Mermaid import keeps a subgraph's title when it has no separate `[Title]`
  (`subgraph Backend`, `subgraph "AWS Cloud"`, a Japanese name), no longer
  treats `End`/`END` as closing a subgraph, and ignores a leading UTF-8 BOM.
- `.nan`/`.inf` coordinates and sizes are a Fatal error instead of a crash
  in layout/rendering.
- A vertical `elbow` (or `curved`) connector - one leaving its start through
  the top/bottom edge - is written rotated 90 degrees, so PowerPoint draws the
  vertical-horizontal-vertical route the checks and preview assume; it used
  to be drawn as a horizontal-vertical-horizontal hook with a sideways
  arrowhead.
- Connectors and shapes no longer inherit the theme's drop shadow (in
  LibreOffice too), and a container's `borderWidth: 0` draws no border.
- `arrow: both` writes the connector's `headEnd` before its `tailEnd`, the
  order the OOXML schema requires.
- Text size and colour are set on every run, not only as the paragraph's
  default, which PowerPoint doesn't apply to existing runs; Japanese and
  Korean text is tagged with its language (LibreOffice drew Japanese in a
  Chinese font).
- On a dark `canvas.background`, labels, container frames and lines that
  would be unreadable (black on navy) switch to white.
- The .pptx no longer carries python-pptx's template metadata (author "Steve
  Canny", a 2013 date, a 4:3 slide-size type, "On-screen Show (4:3)");
  `SOURCE_DATE_EPOCH` fixes its timestamps.
- Placeholder icons no longer share abbreviations within a provider (nine
  GCP icons read "CLOU").
- The schema describes element `x`/`y` as relative to the parent container
  (it said "absolute"), and a node's `provider` by what it does.
- New Warnings: a child that extends outside its own container, and a link
  whose path runs back through one of its own endpoint nodes. A link leaving
  a node with a `right` label through the right side attaches past the label
  instead of through it.
- `build`/`preview`/`export-drawio`/`from-mermaid` refuse an output path that
  is the input file itself (`build d.yaml -o d.yaml` overwrote the YAML), and
  `sync` refuses to write its YAML over the `.drawio` it reads - including via
  a differently-cased path or a hard link to the same file.
- A report can no longer crash on a console that can't encode a label
  (e.g. cp1252 on a Windows CI runner): unencodable characters are escaped.
- Numbers beyond ±1,000,000 are a Fatal error; a huge one overflowed to
  infinity and leaked a non-JSON `Infinity` into `--format json` output.
- `export-drawio` drops characters XML can't carry (control characters,
  lone surrogates) from labels, and decides whether a label is HTML the way
  draw.io does (`html=1` or `whiteSpace=wrap`).
- `sync` accepts compressed `<diagram>` content with whitespace inside the
  base64 (as draw.io's own decoder does).
- Mermaid import recognises the header after a ```` ```mermaid ```` code
  fence, `---` front matter or a multi-line `%%{init}%%` directive, ignores
  `accTitle:`/`accDescr:` text (whose `;` used to create stray nodes), no
  longer turns an unknown header direction into a node, and no longer
  rejects a headerless flowchart whose first node is called e.g. `block`.

## [0.1.0] - 2026-08-16

First public release.

### Added

- **`build`** — generate a PowerPoint (`.pptx`) architecture diagram from a
  YAML definition, with hierarchical containers (cloud → VPC → AZ → subnet),
  connectors, labels, and multi-cloud icon registries (AWS/GCP/Azure).
- **`validate`** — schema + semantic checks plus mechanical overlap, link-
  crossing and false-edge-aliasing detection, with no rendering.
- **`doctor`** — auto-resolve drawing collisions in four verified stages, each
  of which only ever accepts a strictly-improving change so a diagram is never
  made worse: (1) separate overlapping elements, (2) route links by connection
  side, (3) displace an auto-placed obstacle a link runs through, (4) detour a
  link with waypoints around an obstacle that can't move.
- **`diff`** — semantic structural diff between two diagrams: elements matched
  by id and links by id-or-endpoints, normalised against defaults, reporting
  additions, removals, re-parenting (moves between containers) and field-level
  changes rather than text noise.
- **Link waypoints** — explicit polyline routing (`link.waypoints`) to send a
  connector through given points, e.g. to detour around an obstacle.
- **`preview`** — quick PNG render with no PowerPoint/LibreOffice needed.
- **`export-drawio` / `sync`** — round-trip a diagram through draw.io, syncing
  manual position/size edits back into the YAML.
- **`from-mermaid`** — convert a Mermaid `flowchart`/`graph` to zook YAML.
- **`icons list`** — inspect the registered icon/container vocabulary.
- Machine-readable output (`--format json` / `--format github`) and `--strict`
  gating for CI use across the relevant commands.

[0.1.0]: https://github.com/taka-sho/zook/releases/tag/v0.1.0
