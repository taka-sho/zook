# Usage

[🇯🇵 日本語版](/zook/ja/usage/){ .md-button }

zook's commands: `build`/`validate`/`doctor`/`diff`/`icons`/`preview`/`export-drawio`/`sync`/`from-mermaid`, plus `guide`/`schema`/`patterns`/`init`, which serve the docs, schema and reference patterns bundled with the package.

```bash
zook --help
zook --version
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
zook doctor diagram.yaml -o fixed.yaml          # write the resolved YAML to a new file (always written, even if nothing needed fixing)
zook doctor diagram.yaml --fix                  # rewrite the original file in place, only if something changed (ignored if -o is given)
zook doctor diagram.yaml --format json          # machine-readable output (moves/pinned/linkChanges/remaining, etc.)
```

`doctor` judges every change by one objective: the **weighted** total of the Warnings `validate` would report that doctor can influence. An element overlap, a child spilling out of its container, or a link running back through its own endpoint weighs most; a link crossing a node more than one crossing a container's frame; label collisions and apparent direct connections less. Off-slide / shrink-to-fit Warnings count too, so pushing something off the slide is never a "fix". Every change is applied, re-measured, and kept only if the total **strictly decreases** — otherwise rolled back exactly — so doctor never makes a diagram worse. It resolves things in four stages (in this order, since each later stage depends on the earlier ones' results), and repeats the sequence while a round still improves, so running it again on its own output changes nothing:

1. **Element overlaps (coordinate adjustment).** Resolves **sibling-vs-sibling and element-vs-container-label overlaps, and a child spilling outside its container**, by moving elements the shortest distance — right, down, left or up — that clears the collision while staying inside the container (and on the slide, at the top level). It gives direct children of a broken container explicit coordinates (x/y), so the resulting YAML reproduces the resolved layout exactly.
2. **Link routing (connection-side assignment).** A link has no coordinates of its own — its path is determined by both endpoints' positions (settled by this point) and its connection sides. So **a link running through a node or back through its own endpoint, an apparent direct connection (false edge aliasing), and link-label collisions** are resolved by assigning `fromSide`/`toSide` (a same-side pair is a U route around the obstacle). Candidates are scored incrementally — only the warnings that involve the re-routed link are recomputed — and the chosen one is verified against the full checks.
3. **Displacing an obstacle (coordinate adjustment).** A path that still runs through a node after trying every connection side can't be moved, so instead **the obstacle is pushed perpendicular to the path**, staying inside its container. Only auto-placed elements are moved; stages 1–2 are re-run for each candidate move.
4. **Detouring the link (inserting waypoints).** If the obstacle is author-positioned and can't be moved, **right-angled detour waypoints are inserted into the link** to route it around the obstacle. A link whose routing (waypoints or connection sides) the author already specified is treated as intentional and is never a target for this.

- Defaults to a **dry run** that just shows the proposed changes (matching AGENTS.md's "propose first, agree, then build" policy). Only writes to a file when `-o` or `--fix` is given. `-o PATH` always writes `PATH` — a byte-for-byte copy when there was nothing to fix — so `zook doctor d.yaml -o fixed.yaml && zook build fixed.yaml ...` never reads a missing or stale file; `--fix` leaves an already-clean file untouched. Existing comments, key ordering and the file's own indentation style are preserved, and integer coordinates stay integers (the same ruamel round-trip `sync` uses — see [draw.io Integration](drawio-sync.md)).
- A connection side (fromSide/toSide) or waypoints the author set are never changed. When choosing what to move, an auto-placed element is preferred over an explicitly-positioned one; only when **both** elements of an overlapping pair are author-positioned does doctor move one of them (the later-declared) — and only if that strictly improves the diagram. Obstacle displacement only ever moves **auto-placed elements**.
- The report lists **`moves`** (elements whose rendered position changed) and **`pinned`** (auto-placed elements that got an explicit x/y at the spot they already occupied, so their container stops re-packing around a moved sibling — the file changes for them although nothing visibly moves), plus `linkChanges`.
- Whatever no stage can resolve is reported under `remaining`, and `status` becomes `partial`. **Unknown icons** and off-slide / shrink-to-fit Warnings are also listed under `remaining` (they don't make the status `partial`) — handle those by editing the YAML or extending the registry (see [Known Limitations](limitations.md)).
- With `--strict`, anything left in `remaining` causes a non-zero exit.

## diff — Structural Diff Between Two Diagrams

Since zook treats a diagram as code in YAML, being able to review changes in Git is one of its strengths. But a plain text diff of YAML mixes in noise — reformatted mappings, reordered elements that sit at explicit coordinates, defaults written out — burying the change you actually care about. `diff` compares two diagrams **by meaning**. Elements are matched by `id`; links by id, then by their endpoints and attributes; and only what actually changed is reported: elements added, removed, **moved between containers (re-parented)**, **reordered** (auto-placed siblings, whose order is their placement), or modified field-by-field; links added, removed, or modified; and canvas changes.

```bash
zook diff old.yaml new.yaml                 # human-readable structural diff
zook diff old.yaml new.yaml --format json    # machine-readable (for CI/AI)
zook diff old.yaml new.yaml --exit-code       # exit 1 if there's a difference (like git diff --exit-code); an invalid input exits 2
```

```text
~ canvas.aspectRatio: "16:9" -> "4:3"
+ api (node Lambda) in vpc
- cache (node ElastiCache) in vpc
> web: moved vpc -> edge
~ db (node RDS): type "RDS" -> "Aurora"; label "Primary DB" -> "Main DB"
~ order in vpc: web, db -> db, web
+ link api -> db ("SQL")
~ link web -> db ("3306"): style "straight" -> "elbow"
```

The symbols are `+` added / `-` removed / `>` moved (re-parented) / `~` modified.

- **Default-value normalization**: omitting a value on one side and writing the equivalent default explicitly on the other (a node's `provider: aws`, a container's `layout: {direction: grid}`, `labelPosition: below`, a frame colour equal to the registry's, `size: 64` on an icon) means the same thing, so it's not reported as a diff. Reordering explicitly positioned elements isn't reported either; reordering auto-placed ones is, since it moves them.
- **Links between the same two elements** are paired identical-first, so deleting one of two parallel links is one removal; a link that only gained an `id` is a modification of its id, not an add plus a remove.
- **Re-parenting detection**: when an element moves to a different container, it's reported as a single "move," not an add plus a remove (e.g. `web` moving from `vpc` to `edge`) — a structural change a text diff can't express.
- Both files must pass validation (schema and semantic). Fatal input is reported as `error`, prefixed with which side failed (`old diagram old.yaml: ...` / `new diagram new.yaml: ...`), and exits **2** — so under `--exit-code` it can't be mistaken for "the diagrams differ" (1).
- `--exit-code` is handy for CI gates like "fail if an unintended diagram change is detected."

## icons list — List Registered Icon/Container Types

```bash
zook icons list                  # all of aws/gcp/azure
zook icons list --provider gcp    # a specific provider only
zook icons list --format json
```

```text
[aws]
  node   EC2                  [Compute] (aliases: AmazonEC2)
  node   Lambda               [Compute] (aliases: AWSLambda)
  ...
  group  vpc
  group  cloud
  ...
```

Check the names that are actually usable before a typo'd `type` turns into a Warning. Lookup ignores case, spaces, hyphens, underscores and dots (`API Gateway` finds `APIGateway`), and icons marked `any provider` (actors, Server, Internet, ...) work in a GCP/Azure diagram too. Combined with `--registry`, this lists the vocabulary with your custom registry layered on.

## preview — Lightweight PNG Preview

Get an instant visual check with no PowerPoint or LibreOffice needed (a simplified render via Pillow — the look differs somewhat from the actual pptx).

```bash
zook preview diagram.yaml -o diagram.png
zook preview diagram.yaml -o diagram.png --format json   # same warnings/status as validate
```

The output must be a `.png` path. `--format`/`--strict` behave as they do for `build`.

Text is drawn with a system font that has Japanese/Chinese/Korean glyphs (Hiragino, Noto Sans CJK, Yu Gothic, ...). Set `ZOOK_PREVIEW_FONT` to a `.ttf`/`.ttc` to choose one; if that file can't be loaded or has no CJK glyphs, it is ignored with a Warning and the usual candidates are used instead. That font's Latin letters are usually a little wider than the slide's Calibri, so a line that would overrun its label box is drawn slightly smaller rather than spilling out of it. Line widths and arrowheads keep their slide size under a shrink-to-fit, as they do in the .pptx.

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

## guide / schema / patterns / init — Start Without the Repository

The workflow, the YAML spec, the reference patterns and the JSON Schema ship inside the package, so an AI agent working in its own repository (with zook installed by `pipx`/`uv tool`) can read them without a clone.

```bash
zook guide                        # the step-by-step workflow (AGENTS.md's agent part)
zook guide yaml                   # the full YAML spec; also: patterns, usage, limitations, mermaid, drawio
zook schema                       # the diagram JSON Schema (--icon-registry: a --registry file's)
zook patterns list                # reference architectures, with what each is for (--format json)
zook patterns show serverless-api # one pattern's YAML
zook init diagram.yaml            # a small valid starter diagram
zook init diagram.yaml --pattern container-platform   # or start from a pattern (--force to overwrite)
```

## Overriding With Your Own Icons/Styles

The `--registry` option (shared by `build`/`validate`/`doctor`/`icons list`/`preview`/`export-drawio`/`sync`/`from-mermaid`, and repeatable) lets you layer your own icon and frame-style definitions on top of the built-in registries. Redefining a type merges field by field, the user side winning. Your registry's `provider` field decides which provider it layers onto (default `aws`; `custom` for a vocabulary of your own).

```bash
zook build diagram.yaml -o diagram.pptx --registry my-registry.yaml
```

`my-registry.yaml` follows the [`icon-registry.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/icon-registry.schema.json) format (`zook schema --icon-registry` prints it). Icon files can be PNG, JPEG or SVG. See [Icon Registry](icons.md) for details.

## Error Handling {: #error-handling }

zook clearly distinguishes "structural breakage" from "minor drawing issues" (designed with CI/CD use in mind).

### Fatal (stderr + non-zero exit)

These stop generation immediately.

- The file can't be read as YAML: a syntax error (reported with its line and column), a **mapping key written twice** (e.g. two `links:` blocks — rejected rather than silently keeping the last one), or a file that isn't UTF-8 (a UTF-8 BOM is fine)
- The YAML violates the JSON Schema (a missing required field, a type mismatch, an unknown field, only one of `x`/`y` set, etc.). Each violation is reported at its exact path, e.g. `$['elements'][0]['children'][1]['style']['labelPosition']: 'bottom' is not one of [...]`. An unquoted value YAML reads as a number or boolean (`aspectRatio: 16:9` becomes `969`, `label: no` becomes `false`) gets a hint to quote it
- A number is `.nan`/`.inf`, or absurdly large (beyond ±1,000,000)
- An element's `id` is duplicated
- A `links` entry's `from`/`to` references a nonexistent `id`
- Both `link.fromSide`/`toSide` are set with a mismatched axis (`top`/`bottom` vertical vs `left`/`right` horizontal)
- An input can't be read (missing, unreadable, a directory), an output path can't be written (e.g. its directory doesn't exist, or it is a directory), or the output is the input file itself for `build`/`preview`/`export-drawio`/`from-mermaid` (and, for `sync`, the `.drawio` being synced) — including a differently-cased path to the same file
- A `--registry` file doesn't match [`icon-registry.schema.json`](https://github.com/taka-sho/zook/blob/main/docs/icon-registry.schema.json)

```bash
$ zook build broken.yaml -o out.pptx
Error: Duplicate element id(s): web
$ echo $?
1
```

### Warning (printed to stderr, generation continues)

These print a warning but let generation continue (exit code `0` by default; `1` with `--strict`).

- A `type` can't be resolved in the registry (unknown service name) → drawn with a placeholder icon; the Warning names the closest types, or the provider that has this one
- An icon file can't be read as an image (PNG and JPEG are used as-is, SVG is rasterized) → drawn with a placeholder icon
- A container `type` isn't in the registry → drawn as a plain frame; the Warning names the closest container type (`type: group` is the deliberately plain frame)
- The diagram had to be shrunk below 70% to fit the slide (the default `canvas.fit: shrink`; a milder shrink is silent) → shrunk anyway, and the Warning names any explicitly positioned element lying outside the canvas, since one mistyped coordinate (`x: 12000` for `1200`) is the usual cause
- With `canvas.fit: none`, anything drawn outside the canvas (an element, a node label, a link or its label) → placed as-is, not clipped
- Elements overlap at their coordinates (between siblings) → mechanically detected as a rectangle overlap from the computed coordinates. Explicitly-positioned children are never auto-corrected, but an **auto-placed child is automatically shifted when it overlaps an explicitly-positioned sibling** (a Warning is only raised if that still doesn't resolve it)
- A child element overlaps its container's own label-text area
- A child element extends outside its own container (an explicit x/y beyond the container's explicit width/height, or a negative x/y)
- A link's path runs back through one of its own endpoint nodes (e.g. `fromSide: top` on a link that goes down)
- A link's label covers one of its own endpoint nodes. A label that would hide the arrowhead of a short link is moved beside the line — past the endpoint icons if need be — so this only fires when no such spot is free
- A link's (arrow's) path, or its own label, overlaps an unrelated element, another link's label, or a container's label → mechanically judged from the actual rendered path from the connection points (`straight`/`elbow` are exact; only `curved` is a straight-line approximation). Overlap with a container's label is never excluded even for an ancestor container
- Two separate links' Z-routes run collinear through a shared node's connection point, reading as one direct connection (false edge aliasing — see [Known Limitations](limitations.md) for details)

Setting `canvas.overlapMargin` (see [YAML Input Guide](yaml-guide.md#canvas)) extends detection beyond literal overlaps to "too close" as well, for any of the above.

```bash
$ zook build diagram.yaml -o out.pptx
Warning: unknown type 'Lamda' for node 'fn' (provider 'aws'); using placeholder icon - did you mean 'Lambda'?
Warning: element 'web' overlaps element 'cache'
Wrote out.pptx
```

### Machine-Readable Output (`--format`)

`build`/`validate`/`doctor`/`diff`/`preview`/`export-drawio`/`sync`/`from-mermaid` also support `--format json` (a single-line JSON object on stdout) and `--format github` (GitHub Actions `::warning::`/`::error::` annotations; a multi-line message is kept on one annotation). `icons list --format json` prints the vocabulary as JSON (under `github` only an error becomes an annotation).

Under `--format json`, `warnings` (and doctor's `remaining`) stays a list of message strings; `details` (`remainingDetails`) repeats each one with a stable **`code`**, the ids of the **`elements`** it concerns and the **`links`** (`{"from", "to", "id"}`) — so a tool or an AI can act on a Warning without parsing its text. An error comes with `errorCode` and `errorDetails` the same way (each schema violation's `path` and `pointer`, a YAML error's `line`/`column`, an unknown link endpoint's `didYouMean`).

```bash
$ zook validate diagram.yaml --format json
{"status": "warning", "warnings": ["unknown type 'Lamda' for node 'fn' ..."], "details": [{"code": "unknown-type", "message": "unknown type 'Lamda' for node 'fn' ...", "elements": ["fn"], "links": []}]}
$ zook validate broken.yaml --format json
{"status": "error", "warnings": [], "details": [], "error": "YAML error in broken.yaml at line 7, column 10: ...", "errorCode": "yaml-syntax", "errorDetails": [{"file": "broken.yaml", "line": 7, "column": 10}]}
```

| Warning `code` | Meaning (`elements` / `links`) |
|---|---|
| `unknown-type` / `unknown-container-type` | a `type` isn't in the registry; the message names the closest ones (the element) |
| `icon-file-missing` / `icon-file-unreadable` | the registry's icon file is missing or not an image (the element) |
| `element-overlap` | two sibling elements overlap (both) |
| `container-label-overlap` | an element overlaps its container's label (element, container) |
| `outside-container` | a child extends outside its container (child, container) |
| `link-crosses-element` / `link-crosses-container-label` / `link-crosses-link-label` | a link's path runs through an element / a container's label / another link's label (that element or container; the link, and the other link) |
| `link-through-own-endpoint` | a link doubles back through one of its own endpoints |
| `link-label-overlaps-element` / `link-label-overlaps-container-label` / `link-labels-overlap` / `link-label-covers-endpoint` | a link's label covers something |
| `link-aliasing` | two links share a collinear segment and read as one connection (both links) |
| `canvas-shrunk` / `off-canvas` | shrunk below 70% to fit the slide (any stray explicitly positioned elements) / drawn outside the slide with `fit: none` |
| `registry-alias-ignored` | a `--registry` alias names another type |
| `preview-font-ignored` / `preview-no-cjk-font` | preview only: the font setting |
| `sync-…` | `sync` only: something edited in draw.io that isn't synced (`sync-reparent-ignored`, `sync-label-changed`, `sync-link-added`, ...) |

| `errorCode` | Meaning |
|---|---|
| `schema` | schema violations (`errorDetails`: `path`, `pointer`, `message` each) |
| `yaml-syntax` / `duplicate-key` / `not-utf8` / `not-a-diagram` | the file can't be read as a diagram |
| `duplicate-id` / `duplicate-link-id` / `unknown-link-endpoint` / `link-side-axis-mismatch` / `invalid-number` | the diagram's ids, links or numbers don't hold together |
| `invalid-registry` | a `--registry` file doesn't match its schema |
| `io-error` / `internal-error` / `fatal` | a path can't be read or written / a zook bug / anything else |

Every failure — a Fatal, an unreadable file, an unwritable output path — is reported this way, never as a Python traceback. An unexpected internal error is reported the same way with an `internal error: ...` message (set `ZOOK_DEBUG=1` to also print the traceback to stderr, and please report it).

CI/CD pipelines can gate on the exit code (combinable with `--strict`) or on the `--format` output.

### Exit Codes

| Code | Meaning |
|---|---|
| `0` | Success (Warnings may have been reported) |
| `1` | Fatal / error — or, with `--strict`, at least one Warning (`doctor --strict`: a collision it couldn't resolve). For `diff --exit-code`: the diagrams differ |
| `2` | `diff` only: an input was invalid (a missing or unreadable input file is reported like any other error: `1`, or `2` for `diff`). Also used by the argument parser for a usage error such as an unknown option |

## About the Generated PowerPoint

- Nested structures like VPC → AZ → service are generated as hierarchical groups in PowerPoint too — each level can be dragged and edited individually.
- Connectors (arrows) attach to the connection points of rectangular shapes (icons, container frames) and follow shape movement to some degree (see [Design Notes](design-notes.md) for details).
- The generated diagram targets being good enough as "a starting point for hand-editing," not a perfect automatic layout. Some overlaps (auto-placed vs. explicit) are automatically avoided, but everything else is only detected as a Warning, on the assumption you'll fix it up by hand in PowerPoint.
