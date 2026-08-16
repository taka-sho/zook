# Usage

[🇯🇵 日本語版](/zook/ja/usage/){ .md-button }

zook has nine subcommands: `build`/`validate`/`doctor`/`diff`/`icons`/`preview`/`export-drawio`/`sync`/`from-mermaid`.

```bash
zook --help
```

## build — Generate a PowerPoint

```bash
zook build <input.yaml> -o <output.pptx>
```

- `input.yaml` — a diagram definition file following the [YAML Input Guide](yaml-guide.md)
- `-o, --output` — the output `.pptx` path (required)
- `--registry` — override the built-in registries with your own (see [Icon Registry](icons.md))
- `--strict` — exit non-zero if there's even one Warning (default: non-zero only on Fatal)
- `--format {text,json,github}` — output format (below)

## validate — Check Without Rendering

Everything `build` does minus the actual pptx generation (the python-pptx call). Schema validation, semantic validation, and overlap detection all run, making this well-suited to a fast loop for checking LLM-generated YAML.

```bash
zook validate diagram.yaml
zook validate diagram.yaml --strict          # treat Warnings as failures too
zook validate diagram.yaml --format json      # machine-readable output for CI
```

## doctor — Auto-Resolve Overlaps and Link-Routing Collisions

`validate` **only detects** problems like "sibling elements overlap" or "a link runs through a node" — fixing them (adjusting coordinates or connection sides) is left to the author. `doctor` takes that a step further: using the same geometry `validate` computes, it actually resolves the collision and shows you the result (write it straight back into the YAML with `-o`/`--fix`). The idea is that the tool handles the "pixel-level coordinate adjustment and connection-side trial-and-error" that a generative AI is worst at.

```bash
zook doctor diagram.yaml                       # dry run: just shows the proposed changes
zook doctor diagram.yaml -o fixed.yaml          # write the resolved YAML to a new file
zook doctor diagram.yaml --fix                  # rewrite the original file in place (ignored if -o is given)
zook doctor diagram.yaml --format json          # machine-readable output (moves/linkChanges/remaining, etc.)
```

`doctor` resolves things in four stages (in this order, since each later stage depends on the earlier ones' results):

1. **Element overlaps (coordinate adjustment).** Resolves the **sibling-vs-sibling and element-vs-container-label overlaps** `validate` reports, by nudging elements apart. It gives direct children of a broken container explicit coordinates (x/y), so the resulting YAML reproduces the resolved layout exactly.
2. **Link routing (connection-side assignment).** A link has no coordinates of its own — its path is determined by both endpoints' positions (settled by this point) and its connection sides. So **a link running through a node, an apparent direct connection (false edge aliasing), and link-label collisions** are resolved by assigning `fromSide`/`toSide`. Each candidate assignment is checked against the actual warning count, and only kept if it **strictly decreases** — so the routing can never get worse.
3. **Displacing an obstacle (coordinate adjustment).** A path that still runs through a node even after trying every connection side can't be moved, so instead **the obstacle is pushed perpendicular to the path**. Only auto-placed elements are moved — the move is actually applied, stages 1–2 are re-run, and it's kept only if the **total warning count strictly decreases**; otherwise it's fully rolled back (so this stage, too, can never make things worse).
4. **Detouring the link (inserting waypoints).** If the obstacle is author-positioned and can't be moved, instead **detour waypoints are inserted into the link** to route it around the obstacle. Waypoints that go around the obstacle's bounding box are actually inserted, and kept only if the **total warning count strictly decreases**; otherwise rolled back. A link whose routing (waypoints or connection sides) the author already specified is treated as intentional and is never a target for this.

- Defaults to a **dry run** that just shows the proposed changes (matching AGENTS.md's "propose first, agree, then build" policy). Only writes to a file when `-o` or `--fix` is given. Existing comments and key ordering are preserved (the same ruamel round-trip `sync` uses — see [draw.io Integration](drawio-sync.md)).
- A position (x/y), connection side (fromSide/toSide), or waypoints the author explicitly set is treated as intentional and never overwritten. When choosing what to move, an auto-placed element is preferred over an explicitly-positioned one; obstacle displacement only ever moves **auto-placed elements**; connection-side assignment and detouring only target **links whose routing the author didn't specify**.
- A collision no stage can resolve (e.g. the obstacle and both endpoints are all author-positioned, with the connection sides fixed too) is reported under `remaining`, and `status` becomes `partial`. **Off-canvas coordinates and unknown icons** are out of scope for `doctor` and also appear under `remaining` — handle those via draw.io, editing the YAML, or extending the registry (see [Known Limitations](limitations.md)).
- With `--strict`, a residual collision that couldn't be auto-resolved (`status: partial`) causes a non-zero exit.

## diff — Structural Diff Between Two Diagrams

Since zook treats a diagram as code in YAML, being able to review changes in Git is one of its strengths. But a plain text diff of YAML mixes in noise — reordered children, reformatted mappings, coordinates written by auto-layout — burying the change you actually care about. `diff` compares two diagrams **by meaning**. Elements are matched by `id`, links by id or by their endpoints, and only what actually changed is reported: elements added, removed, **moved between containers (re-parented)**, or modified field-by-field; links added, removed, or modified; and canvas changes.

```bash
zook diff old.yaml new.yaml                 # human-readable structural diff
zook diff old.yaml new.yaml --format json    # machine-readable (for CI/AI)
zook diff old.yaml new.yaml --exit-code       # non-zero exit if there's a difference (like git diff --exit-code)
```

```text
~ canvas.aspectRatio: "16:9" -> "4:3"
+ api (node Lambda) in vpc
- cache (node ElastiCache) in vpc
> web: moved vpc -> edge
~ db (node RDS): type "RDS" -> "Aurora"; label "Primary DB" -> "Main DB"
+ link api -> db
~ link web -> db: style "straight" -> "elbow"
```

The symbols are `+` added / `-` removed / `>` moved (re-parented) / `~` modified.

- **Default-value normalization**: omitting a value on one side and writing the equivalent default explicitly on the other (e.g. a node's `provider: aws`, or a container's `layout: {direction: grid}`) means the same thing, so it's not reported as a diff. Reordering children isn't reported either.
- **Re-parenting detection**: when an element moves to a different container, it's reported as a single "move," not an add plus a remove (e.g. `web` moving from `vpc` to `edge`) — a structural change a text diff can't express.
- Both files must pass validation (schema and semantic). Fatal input is reported as `error`.
- `--exit-code` is handy for CI gates like "fail if an unintended diagram change is detected."

## icons list — List Registered Icon/Container Types

```bash
zook icons list                  # all of aws/gcp/azure
zook icons list --provider gcp    # a specific provider only
zook icons list --format json
```

```text
[aws]
  node   EC2                  [Compute] (aliases: ec2, AmazonEC2)
  node   Lambda               [Compute] (aliases: lambda, AWSLambda)
  ...
  group  vpc
  group  cloud
  ...
```

Check the names that are actually usable before a typo'd `type` turns into a Warning. Combined with `--registry`, this lists the vocabulary with your custom registry layered on.

## preview — Lightweight PNG Preview

Get an instant visual check with no PowerPoint or LibreOffice needed (a simplified render via Pillow — the look differs somewhat from the actual pptx).

```bash
zook preview diagram.yaml -o diagram.png
```

## export-drawio / sync — Hand-Tune in draw.io, Manage Continuously

Hand-tune a generated diagram in [draw.io](https://www.diagrams.net/), then mechanically feed its position/size changes back into the YAML. See [draw.io Integration](drawio-sync.md) for the full workflow.

```bash
zook export-drawio diagram.yaml -o diagram.drawio   # write out a format draw.io can open
# ... adjust position/size in draw.io and save ...
zook sync diagram.yaml diagram.drawio -o diagram.yaml # reflect the changes back into the YAML
```

## from-mermaid — Convert From a Mermaid Flowchart

Converts [Mermaid](https://mermaid.js.org/)'s `flowchart`/`graph` notation into zook YAML. See [Mermaid Flowchart Import](mermaid-import.md) for details.

```bash
zook from-mermaid diagram.mmd -o diagram.yaml
```

## Overriding With Your Own Icons/Styles

The `--registry` option (shared by `build`/`validate`/`doctor`/`icons list`/`preview`/`export-drawio`/`sync`) lets you layer your own icon and frame-style definitions on top of the built-in registries. Defining the same key lets the user side win. Your registry's `provider` field decides which provider it layers onto (default `aws`).

```bash
zook build diagram.yaml -o diagram.pptx --registry my-registry.yaml
```

`my-registry.yaml` follows the [`icon-registry.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/icon-registry.schema.json) format. See [Icon Registry](icons.md) for details.

## Error Handling {: #error-handling }

zook clearly distinguishes "structural breakage" from "minor drawing issues" (designed with CI/CD use in mind).

### Fatal (stderr + non-zero exit)

These stop generation immediately.

- The YAML violates the JSON Schema (a missing required field, a type mismatch, an unknown field, only one of `x`/`y` set, etc.)
- An element's `id` is duplicated
- A `links` entry's `from`/`to` references a nonexistent `id`
- Both `link.fromSide`/`toSide` are set with a mismatched axis (`top`/`bottom` vertical vs `left`/`right` horizontal)

```bash
$ zook build broken.yaml -o out.pptx
Error: Duplicate element id(s): web
$ echo $?
1
```

### Warning (printed to stderr, generation continues)

These print a warning but let generation continue (exit code `0` by default; `1` with `--strict`).

- A `type` can't be resolved in the registry (unknown service name) → drawn with a placeholder icon
- An element's coordinates fall outside the canvas → placed as-is, not clipped
- Elements overlap at their coordinates (between siblings) → mechanically detected as a rectangle overlap from the computed coordinates. Explicitly-positioned children are never auto-corrected, but an **auto-placed child is automatically shifted when it overlaps an explicitly-positioned sibling** (a Warning is only raised if that still doesn't resolve it)
- A child element overlaps its container's own label-text area
- A link's (arrow's) path, or its own label, overlaps an unrelated element, another link's label, or a container's label → mechanically judged from the actual rendered path from the connection points (`straight`/`elbow` are exact; only `curved` is a straight-line approximation). Overlap with a container's label is never excluded even for an ancestor container
- Two separate links' Z-routes run collinear through a shared node's connection point, reading as one direct connection (false edge aliasing — see [Known Limitations](limitations.md) for details)

Setting `canvas.overlapMargin` (see [YAML Input Guide](yaml-guide.md#canvas)) extends detection beyond literal overlaps to "too close" as well, for any of the above.

```bash
$ zook build diagram.yaml -o out.pptx
Warning: unknown type 'QuantumFlux' for node 'mystery'; using placeholder icon
Warning: element 'web' overlaps element 'cache'
Wrote out.pptx
```

### Machine-Readable Output (`--format`)

`build`/`validate`/`doctor`/`diff`/`export-drawio`/`sync`/`from-mermaid` also support `--format json` (a single-line JSON object) and `--format github` (GitHub Actions `::warning::`/`::error::` annotations).

```bash
$ zook validate diagram.yaml --format json
{"status": "warning", "warnings": ["unknown type 'QuantumFlux' for node 'mystery'; using placeholder icon"]}
```

CI/CD pipelines can gate on the exit code (combinable with `--strict`) or on the `--format` output.

## About the Generated PowerPoint

- Nested structures like VPC → AZ → service are generated as hierarchical groups in PowerPoint too — each level can be dragged and edited individually.
- Connectors (arrows) attach to the connection points of rectangular shapes (icons, container frames) and follow shape movement to some degree (see [Design Notes](design-notes.md) for details).
- The generated diagram targets being good enough as "a starting point for hand-editing," not a perfect automatic layout. Some overlaps (auto-placed vs. explicit) are automatically avoided, but everything else is only detected as a Warning, on the assumption you'll fix it up by hand in PowerPoint.
