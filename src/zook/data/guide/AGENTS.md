# AGENTS.md

*[日本語版はこちら / Japanese version](./AGENTS.ja.md)*

zook is a CLI tool that generates PowerPoint (.pptx) architecture diagrams from an infrastructure configuration written in YAML. Its primary intended user is a generative AI. Picture the scenario: a user asks an AI to "propose an infrastructure setup for X and build an architecture diagram." The AI receiving that request should first present a proposed configuration in text and get agreement on it. Only then does it pick an architecture that fits the requirements, write the YAML with zook, validate it, and generate the diagram. This file is the path that lets that sequence proceed without hesitation.

Everything below also ships with the package, so it works where zook was installed with `pip`/`pipx` rather than cloned: `zook guide` prints the steps that follow, `zook guide yaml` the full YAML spec, `zook patterns list` the reference architectures and `zook schema` the JSON Schema.

## From Architecture Proposal to Diagram Generation

1. **First present the proposed configuration in text and get agreement.** Even after receiving requirements, don't jump straight into building YAML/pptx with zook. Show the user the intended configuration in a lightweight form — a bulleted list or a rough ASCII diagram is enough — and get agreement on the direction before moving to the next step. Don't run any zook command at this stage. Misalignment is far cheaper to fix here than after the diagram has actually been generated.

2. **Look for a close pattern.** `zook patterns list` lists the architecture patterns (a 3-tier web app, a serverless API, asynchronous processing, a container platform, etc.) with what each is for; `zook guide patterns` explains how to choose between them. Start from the closest one with `zook init diagram.yaml --pattern <name>` and edit the difference to fit the requirement — far more reliable at avoiding structural breakage than building the structure from scratch.

3. **Confirm which service names are usable.** A YAML `type` (`EC2`, `ComputeEngine`, etc.) isn't fixed by a schema enum. **The icon registry is the single source of truth for vocabulary.** Before you start writing, always run the following to check the actually-existing `type`s, aliases, and categories.

   ```bash
   zook icons list --format json
   ```

   Writing a `type` that doesn't exist isn't a Fatal error — processing continues with a Warning and a placeholder — but the result won't look as intended. The Warning says how to fix it: the close match (`did you mean 'Lambda'?`) or the provider that has it (`set provider: gcp`). Case, spaces and hyphens don't matter (`API Gateway` finds `APIGateway`).

   **When the vocabulary lacks a service**, decide in this order: (a) use the closest listed service and name the real one in its `label`; (b) draw it as a plain shape — `style: {shape: rect}` (or `rounded`/`diamond`/`circle`) with the name as its label — which suits anything provider-neutral; (c) if the user has the official icon, layer it in with a `--registry` file (`zook schema --icon-registry` shows its format; PNG, JPEG and SVG all work); (d) when the choice changes the meaning of the diagram, ask the user. Actors (`User`, `Admin`, `Client`, `Developer`) and provider-neutral icons (`Server`, `Database`, `Internet`, `Mobile`, `OnPremises`, `SaaS`) work under any `provider`.

4. **Write the YAML, or edit a pattern.** The formal definition of the format is the JSON Schema (`zook schema`); the spec written out in prose is `zook guide yaml`. With no close pattern, `zook init diagram.yaml` writes a small valid starting point. For a container whose children form a flow (a request path, a pipeline, a fork and merge), set `layout: {direction: horizontal, order: flow}`: the children are laid out along their links, so no link runs through another element. Links can carry meaning in their look: `line: dashed` for an asynchronous or standby path, `line: dotted` for monitoring or a logical relation, `color`/`width` to pick out the main flow. When reusing a pattern, only rewrite the parts that don't fit the requirement, and keep the pattern's overall structure (container nesting, layout policy) as intact as possible.

5. **Validate.** Always run this before rendering.

   ```bash
   zook validate diagram.yaml --format json
   ```

   `{"status": "error", ...}` means structural breakage (a schema violation, a duplicate id, a dangling link reference, etc.) — rendering it wouldn't produce a meaningful result. Read the `error` field's contents, fix the issue, and keep iterating until you get `{"status": "ok"}` or `{"status": "warning"}`. Each schema violation is reported on its own line at its exact path (e.g. `$['elements'][0]['children'][1]['style']['labelPosition']: 'bottom' is not one of [...]`), so fix exactly that field; a YAML syntax error or a duplicated key comes with its line and column instead. If the message says YAML read an unquoted value as a number or boolean, quote it (`"16:9"`, `"no"`). You don't have to parse the text: `errorCode` says what kind of error it is and `errorDetails` lists each problem (a schema violation's `pointer` into the YAML, a YAML error's `line`/`column`, an unknown link target's `didYouMean`), and every Warning appears again under `details` with a `code` (`element-overlap`, `unknown-type`, `link-crosses-element`, ...) and the `elements`/`links` it concerns. A `warning` is a minor drawing issue (an overlap, an unknown icon, etc.) — it's fine to proceed as-is, but check the details and judge whether the placement matches your intent.

   For a drawing-level `warning`, don't try to fix coordinates or connection sides by hand-calculating — let `doctor` resolve it first (pixel-level adjustment is exactly what an AI is worst at, so it's far more reliable to let the tool handle it). `doctor` fixes things in five stages: (0) **arrange a container along its links** (`layout.order: flow`) where that helps; (1) resolve sibling-vs-sibling and element-vs-container-label **overlaps** (and children spilling out of their container) by moving elements; (2) resolve a link's (arrow's) **path collisions and apparent direct connections (false edge aliasing)** by assigning connection sides (fromSide/toSide); (3) resolve a path that can't be routed around via a connection side by **displacing the obstacle element (if auto-placed)**; (4) if the obstacle is author-positioned and can't be moved, resolve it by **inserting waypoints into the link to detour around it**. Every change is kept only if a weighted total of the Warnings strictly drops, so doctor never makes a diagram worse, and running it twice changes nothing more. First run `zook doctor diagram.yaml --format json` to see the proposal (a dry run), and if it looks right, write it back with `zook doctor diagram.yaml --fix`. A collision none of the stages can resolve, along with unknown icons and off-slide / shrink-to-fit warnings, is simply reported under `remaining` — read `zook guide limitations` and handle those by editing the YAML or fixing it up in draw.io.

6. **Generate.**

   ```bash
   zook build diagram.yaml -o diagram.pptx
   ```

If you want to adjust the look further, beyond hand-editing the YAML directly, there's also the option of draw.io integration via `zook export-drawio`/`sync` (`zook guide drawio`).

## When the Request Starts From a Mermaid Flowchart

If the user already has a diagram in Mermaid `flowchart`/`graph` notation (or the AI itself built a workflow in Mermaid), convert it first instead of writing the YAML from scratch as above.

```bash
zook from-mermaid diagram.mmd -o diagram.yaml
```

The converted YAML is already validated at this point, so you can go straight to step 6's `build`. See `zook guide mermaid` for supported notation and known limitations. Mermaid diagram types other than `flowchart`/`graph`, such as `sequenceDiagram`, aren't supported.

## Key References

| What you want to know | Command (works from any directory) | In this repository |
|---|---|---|
| The full YAML field spec | `zook guide yaml`, `zook schema` | `docs/yaml-spec.md` (authoritative), `docs-site/yaml-guide.md` (summary) |
| The icon/container vocabulary and how the registry works | `zook icons list`, `zook schema --icon-registry` | `docs/icon-registry-and-vocabulary.md`, `docs-site/icons.md` |
| Architecture patterns by requirement | `zook patterns list`, `zook guide patterns` | `src/zook/data/patterns/` |
| What `doctor` (auto-resolves overlap/link-routing Warnings) covers and how to use it | `zook guide usage` (doctor section) | `docs-site/usage.md` |
| Structural diff (`diff`) between two diagrams — for reviewing changes before/after | `zook guide usage` (diff section) | `docs-site/usage.md` |
| Known limitations (overlaps auto-layout doesn't resolve, GCP/Azure constraints, etc.) | `zook guide limitations` | `docs-site/limitations.md` |
| Continuous diagram management via draw.io integration | `zook guide drawio` | `docs-site/drawio-sync.md` |
| Converting from a Mermaid flowchart | `zook guide mermaid` | `docs-site/mermaid-import.md` |
| Internal design of pptx generation (coordinate system, connectors, etc.) | — | `docs-site/design-notes.md`, `docs/detailed-design-pptx.md` |

## When Making Changes

- If you change `docs/zook.schema.json`/`docs/icon-registry.schema.json`, copy the same content into the identically-named file under `src/zook/schemas/` (that's the copy the package actually loads — the two are required to always be byte-identical).
- If you change `docs/registry.<provider>.yaml`, copy it the same way into `src/zook/data/icons/<provider>/registry.<provider>.yaml`; for a new icon entry, `python scripts/generate_placeholder_icons.py --missing-only` draws its placeholder PNG.
- `zook guide` serves copies of this file, `docs/yaml-spec.md` and some `docs-site/` pages from `src/zook/data/guide/`. After editing any of them, run `python scripts/sync_bundled_docs.py` (`tests/test_bundled_data.py` fails on a stale copy).
- Always run the tests after making a change.

  ```bash
  .venv/bin/pytest tests/ -v
  ```

- `docs/example.yaml`, `docs/example-cloud-actors.yaml`, and `src/zook/data/patterns/*.yaml` are regression fixtures expected to stay at "zero warnings." If your change could affect them, check with `zook validate`.
