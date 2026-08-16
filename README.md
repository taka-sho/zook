# ZOOK

[![Tests](https://github.com/taka-sho/zook/actions/workflows/tests.yml/badge.svg)](https://github.com/taka-sho/zook/actions/workflows/tests.yml)
[![Test results](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/taka-sho/zook/main/.github/badges/tests.json)](https://github.com/taka-sho/zook/actions/workflows/tests.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/taka-sho/zook/main/.github/badges/coverage.json)](https://github.com/taka-sho/zook/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**[日本語版はこちら / Japanese version](README.ja.md)**

zook is a CLI tool that generates PowerPoint (.pptx) architecture diagrams from an infrastructure configuration written in YAML. It's built around growing a diagram over time — tune the look in draw.io, and write those changes back into the YAML.

Documentation site covering usage and features: **https://taka-sho.github.io/zook/** (source in `docs-site/`, built with [Zensical](https://zensical.org/) and published to GitHub Pages; a fully separate Japanese version lives at `/ja/`). The full requirements/design source material is in `docs/README-index.md`.

If a generative AI is going to use this tool to build a diagram, [`AGENTS.md`](./AGENTS.md) lays out the golden path (pick a pattern → confirm the icon vocabulary → validate → generate). If you already have a diagram written in Mermaid `flowchart` notation, convert it to YAML first with `zook from-mermaid`, then follow the same flow ([Mermaid Flowchart Import](https://taka-sho.github.io/zook/mermaid-import/)).

## The Basic Flow: Build a Base, Tune It in draw.io, Sync Back to YAML

Building an architecture diagram with zook is a loop of four steps, repeated. Every time you want to touch up the diagram, you come back to this flow.

1. **Build a base diagram from YAML.** Write your VPCs, AZs, services, and other elements in YAML, and generate a PowerPoint with `build`. Elements auto-layout when you don't specify coordinates, so at first you can focus purely on writing the structure.

   ```bash
   zook build diagram.yaml -o diagram.pptx
   ```

2. **Tune the look in draw.io.** The auto-layout alone won't always give you the spacing and placement you want. Export to draw.io format with `export-drawio` and adjust position/size by actually moving elements around.

   ```bash
   zook export-drawio diagram.yaml -o diagram.drawio
   ```

3. **Sync your draw.io adjustments back into the YAML.** Elements you didn't touch stay auto-placed; only the elements you actually moved get coordinates added to the YAML. Adding/removing nodes or changing colors is out of scope for syncing. draw.io is used instead of PowerPoint here because a draw.io container shape's child coordinates don't change on resize, so they can be written straight back into the YAML with no coordinate conversion needed (a PowerPoint group shape keeps its children's coordinates in its own scaled system, which makes reading them back out awkward).

   ```bash
   zook sync diagram.yaml diagram.drawio -o diagram.yaml
   ```

4. **Regenerate the PowerPoint from the tuned YAML.** The PowerPoint is regenerated with your draw.io placement preserved. When you want to change the structure itself, go back to step 1, edit the YAML, and run through the same four steps again.

   ```bash
   zook build diagram.yaml -o diagram.pptx
   ```

This loop can also be automated in CI. Saving a `.drawio` file in draw.io can trigger CI to run `sync` and automatically open a Pull Request with the updated YAML (`.github/workflows/drawio-sync.yml`). See the [draw.io integration page](https://taka-sho.github.io/zook/drawio-sync/) on the docs site for the full workflow.

## Setup

```bash
git clone https://github.com/taka-sho/zook.git
cd zook

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Confirm you can generate from the bundled sample. Success looks like `Wrote example.pptx` printed, with exit code `0`.

```bash
.venv/bin/zook build docs/example.yaml -o example.pptx
```

## Subcommands

| Command | Role |
|---|---|
| `build` | Generate a PowerPoint (.pptx) from YAML |
| `validate` | Check schema/overlaps/etc. without rendering |
| `doctor` | Auto-resolve collisions in four stages (element overlaps = coordinate adjustment / link routing = connection-side assignment / an obstacle blocking a path = displaced / an obstacle that can't move = detoured with waypoints) |
| `diff` | Take the **structural diff** of two diagrams (elements added/removed/moved, link changes, canvas changes — matched by id and reported with no text-diff noise) |
| `icons list` | List registered icon/container types |
| `preview` | Preview as a lightweight PNG, no PowerPoint needed |
| `export-drawio` | Export to a format editable in draw.io |
| `sync` | Reflect position/size changes made in draw.io back into the YAML |
| `from-mermaid` | Convert Mermaid `flowchart`/`graph` notation to YAML |

The `--registry` option (shared by every subcommand) lets you layer your own icons and frame styles on top of the built-in AWS/GCP/Azure icon registries.

```bash
.venv/bin/zook build diagram.yaml -o out.pptx --registry my-registry.yaml
```

See the [usage page](https://taka-sho.github.io/zook/usage/) for each command's detailed options.

## Approach to Error Handling

Built with CI/CD use in mind, zook distinguishes structural breakage from minor drawing issues. Structural errors — schema violations, duplicate ids, dangling link references — exit immediately as Fatal, while drawing-level issues — an unknown icon type, elements overlapping — are printed as Warnings while generation continues (`--strict` switches Warnings to a non-zero exit too). `--format json`/`github` are also supported, so this plugs directly into a CI gate.

## About the Icons

The bundled PNGs aren't each vendor's official icons — they're self-made placeholders generated by `scripts/generate_placeholder_icons.py` (category-based colors plus a service-name abbreviation). Official AWS/GCP/Azure icons aren't included in the repository, for licensing reasons. Swapping in the real official icons just means placing image files to match the `file` path in each `registry.<provider>.yaml` — no code changes needed.

`export-drawio` writes out using draw.io's official AWS4 shape library, but for AWS icons/containers only. GCP/Azure have no mapping table yet, so this tool's own placeholder PNGs get embedded instead.

## Testing & Quality Assurance

CI runs the tests and measures branch coverage on every push to `main`. **Coverage is a quality gate that fails CI below 85%** (the current measured value is shown in the badges above) — the badges at the top of this README aren't from a third-party service; they're generated from that run's own results ([`.github/badges/`](.github/badges/)) and rendered via shields.io. The numbers shown always reflect the latest run on `main`.

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/ -v                                              # tests only
.venv/bin/pytest tests/ --cov=zook --cov-report=term-missing            # with a coverage breakdown
```

See [`.github/workflows/tests.yml`](.github/workflows/tests.yml) for the CI configuration, and `pyproject.toml`'s `[tool.coverage.*]` for what's measured/excluded.

## Known Limitations (v1)

- Overlap avoidance in auto-layout is limited to an auto-placed element overlapping an explicitly-positioned sibling (a simple "push straight down"). Every other overlap is only detected as a Warning, with no auto-fix, on the assumption you'll hand-edit it after generation.
- The built-in icon registries only cover a Tier-1 vocabulary (26 AWS / 19 GCP / 18 Azure services) — anything beyond that is meant to be added via a user registry with `--registry`.
- A link's connection sides (`fromSide`/`toSide`) only support a horizontal pair or a vertical pair — a cross-axis combination is a Fatal error.

See the [known limitations page](https://taka-sho.github.io/zook/limitations/) on the docs site for the full list.

## Documentation Site & CI

User-facing documentation is generated from `docs-site/` with [Zensical](https://zensical.org/), and GitHub Actions auto-deploys it to GitHub Pages on every push to `main`.

```bash
.venv/bin/pip install zensical
.venv/bin/zensical serve          # preview at http://localhost:8000
.venv/bin/zensical build --clean  # generates the static site into site/ (not committed)
```

- `.github/workflows/tests.yml` — runs `pytest` on push/PR
- `.github/workflows/docs.yml` — deploys docs-site to GitHub Pages on push to `main`
- `.github/workflows/drawio-sync.yml` — triggered by a push to a `.drawio` file; runs `sync` and auto-opens a PR with the updated YAML if there's a diff

## Structure

```
src/zook/
  cli.py        CLI entry point (build/validate/doctor/icons/preview/export-drawio/sync/from-mermaid)
  validate.py   JSON Schema validation + semantic checks (duplicate ids/link references/fromSide-toSide axis match)
  doctor.py     Automatic collision resolution (overlaps=coordinate adjustment/link routing=connection sides/blocking obstacle=displaced/immovable obstacle=detoured with waypoints; powers doctor)
  diff.py       Semantic structural diff between two diagrams (id matching, default-value normalization; powers diff)
  model.py      The parsed data model
  registry.py   Icon/frame-style registry resolution (MultiRegistry: per-provider, aliases, overrides)
  layout.py     Auto-layout (grid/horizontal/vertical, mixing with explicit coordinates, overlap avoidance/detection, connection-side auto-selection)
  render.py     Slide generation via python-pptx (hierarchical groups, connectors, labels)
  preview.py    Lightweight PNG preview via Pillow (no LibreOffice/PowerPoint needed)
  drawio.py     Export/sync to draw.io (mxGraph XML), for continuous diagram management
  mermaid_flowchart.py  Parser for Mermaid's `flowchart`/`graph` notation (powers from-mermaid)
  schemas/      zook.schema.json / icon-registry.schema.json (copies of docs/)
  data/icons/{aws,gcp,azure}/  built-in registries + placeholder icon PNGs
```
