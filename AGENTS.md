# AGENTS.md

*[日本語版はこちら / Japanese version](./AGENTS.ja.md)*

zook is a CLI tool that generates PowerPoint (.pptx) architecture diagrams from an infrastructure configuration written in YAML. Its primary intended user is a generative AI. Picture the scenario: a user asks an AI to "propose an infrastructure setup for X and build an architecture diagram." The AI receiving that request should first present a proposed configuration in text and get agreement on it. Only then does it pick an architecture that fits the requirements, write the YAML with zook, validate it, and generate the diagram. This file is the path that lets that sequence proceed without hesitation.

## From Architecture Proposal to Diagram Generation

1. **First present the proposed configuration in text and get agreement.** Even after receiving requirements, don't jump straight into building YAML/pptx with zook. Show the user the intended configuration in a lightweight form — a bulleted list or a rough ASCII diagram is enough — and get agreement on the direction before moving to the next step. Don't run any zook command at this stage. Misalignment is far cheaper to fix here than after the diagram has actually been generated.

2. **Look for a close pattern.** `docs/patterns/README.md` lists architecture patterns by requirement (a 3-tier web app, a serverless API, asynchronous processing, a container platform, etc.) along with "what kind of requirement calls for this one." Basing your YAML on a close pattern's file and editing the difference to fit the requirement is far more reliable at avoiding structural breakage than building the structure from scratch.

3. **Confirm which service names are usable.** A YAML `type` (`EC2`, `ComputeEngine`, etc.) isn't fixed by a schema enum. **The icon registry is the single source of truth for vocabulary.** Before you start writing, always run the following to check the actually-existing `type`s, aliases, and categories.

   ```bash
   zook icons list --format json
   ```

   Writing a `type` that doesn't exist isn't a Fatal error — processing continues with a Warning and a placeholder — but the result won't look as intended.

4. **Write the YAML, or edit a pattern.** The formal definition of the format is `docs/zook.schema.json` (JSON Schema); the spec written out in prose is `docs/yaml-spec.md`. When reusing a pattern, only rewrite the parts that don't fit the requirement, and keep the pattern's overall structure (container nesting, layout policy) as intact as possible.

5. **Validate.** Always run this before rendering.

   ```bash
   zook validate diagram.yaml --format json
   ```

   `{"status": "error", ...}` means structural breakage (a schema violation, a duplicate id, a dangling link reference, etc.) — rendering it wouldn't produce a meaningful result. Read the `error` field's contents, fix the issue, and keep iterating until you get `{"status": "ok"}` or `{"status": "warning"}`. A schema-violation message comes with a specific cause in the form `(closest match: ...)`, which is the most efficient place to start reading. A `warning` is a minor drawing issue (an overlap, an unknown icon, etc.) — it's fine to proceed as-is, but check the details and judge whether the placement matches your intent.

   For a drawing-level `warning`, don't try to fix coordinates or connection sides by hand-calculating — let `doctor` resolve it first (pixel-level adjustment is exactly what an AI is worst at, so it's far more reliable to let the tool handle it). `doctor` fixes things in four stages: (1) resolve sibling-vs-sibling and element-vs-container-label **overlaps** by nudging elements apart; (2) resolve a link's (arrow's) **path collisions and apparent direct connections (false edge aliasing)** by assigning connection sides (fromSide/toSide); (3) resolve a path that can't be routed around via a connection side by **displacing the obstacle element (if auto-placed)**; (4) if the obstacle is author-positioned and can't be moved, resolve it by **inserting waypoints into the link to detour around it**. Every stage only ever applies "a change verified not to make things worse." First run `zook doctor diagram.yaml --format json` to see the proposal (a dry run), and if it looks right, write it back with `zook doctor diagram.yaml --fix`. A collision none of the stages can resolve, along with off-canvas coordinates and unknown icons, is simply reported under `remaining` — read `docs-site/limitations.md` and handle those by editing the YAML or fixing it up in draw.io.

6. **Generate.**

   ```bash
   zook build diagram.yaml -o diagram.pptx
   ```

If you want to adjust the look further, beyond hand-editing the YAML directly, there's also the option of draw.io integration via `zook export-drawio`/`sync` (`docs-site/drawio-sync.md`).

## When the Request Starts From a Mermaid Flowchart

If the user already has a diagram in Mermaid `flowchart`/`graph` notation (or the AI itself built a workflow in Mermaid), convert it first instead of writing the YAML from scratch as above.

```bash
zook from-mermaid diagram.mmd -o diagram.yaml
```

The converted YAML is already validated at this point, so you can go straight to step 6's `build`. See `docs-site/mermaid-import.md` for supported notation and known limitations. Mermaid diagram types other than `flowchart`/`graph`, such as `sequenceDiagram`, aren't supported.

## Key References

| What you want to know | Where to look |
|---|---|
| The full YAML field spec | `docs/yaml-spec.md` (authoritative), `docs-site/yaml-guide.md` (summary) |
| The icon/container vocabulary and how the registry works | `docs/icon-registry-and-vocabulary.md`, `docs-site/icons.md` |
| Architecture patterns by requirement | `docs/patterns/README.md` |
| What `doctor` (auto-resolves overlap/link-routing Warnings) covers and how to use it | `docs-site/usage.md` (doctor section) |
| Structural diff (`diff`) between two diagrams — for reviewing changes before/after | `docs-site/usage.md` (diff section) |
| Known limitations (overlaps auto-layout doesn't resolve, GCP/Azure constraints, etc.) | `docs-site/limitations.md` |
| Continuous diagram management via draw.io integration | `docs-site/drawio-sync.md` |
| Converting from a Mermaid flowchart | `docs-site/mermaid-import.md` |
| Internal design of pptx generation (coordinate system, connectors, etc.) | `docs-site/design-notes.md`, `docs/detailed-design-pptx.md` |

## When Making Changes

- If you change `docs/zook.schema.json`/`docs/icon-registry.schema.json`, copy the same content into the identically-named file under `src/zook/schemas/` (that's the copy the package actually loads — the two are required to always be byte-identical).
- If you change `docs/registry.<provider>.yaml`, copy it the same way into `src/zook/data/icons/<provider>/registry.<provider>.yaml`.
- Always run the tests after making a change.

  ```bash
  .venv/bin/pytest tests/ -v
  ```

- `docs/example.yaml`, `docs/example-cloud-actors.yaml`, and `docs/patterns/*.yaml` are regression fixtures expected to stay at "zero warnings." If your change could affect them, check with `zook validate`.
