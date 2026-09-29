# Installation

[🇯🇵 日本語版](/zook/ja/installation/){ .md-button }

## Requirements

- Python 3.10 or later
- (Recommended) a pptx viewer such as LibreOffice, if you want to check icon rasterization quality

## Install as a Command

zook isn't on PyPI yet; install it straight from GitHub with pipx or uv, which give it its own environment:

```bash
pipx install git+https://github.com/taka-sho/zook.git
# or
uv tool install git+https://github.com/taka-sho/zook.git
```

The workflow for AI agents, the full YAML spec, the reference patterns and the JSON Schema are all part of the package, so nothing else needs to be cloned:

```bash
zook guide                    # the workflow, step by step
zook patterns list            # reference architectures
zook init diagram.yaml --pattern serverless-api
zook validate diagram.yaml && zook build diagram.yaml -o diagram.pptx
```

## Setup for Development

Clone the repository, create a virtual environment, and install.

```bash
git clone https://github.com/taka-sho/zook.git
cd zook

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

The `zook` command is now available.

```bash
.venv/bin/zook --help
```

```text
Usage: zook [OPTIONS] COMMAND [ARGS]...

  zook: generate PowerPoint architecture diagrams from a YAML definition.

Options:
  --version  Show the version and exit.
  --help     Show this message and exit.

Commands:
  build          Generate a .pptx from INPUT_PATH.
  diff           Show the structural difference between two diagrams...
  doctor         Auto-resolve overlaps and link-routing collisions in...
  export-drawio  Export INPUT_PATH as a .drawio file for manual editing...
  from-mermaid   Convert a Mermaid flowchart (INPUT_PATH, e.g.
  guide          Print a bundled guide.
  icons          Inspect the icon/group registry.
  init           Write a starter diagram to OUTPUT_PATH (default...
  patterns       The bundled reference architectures - start from the...
  preview        Render a quick PNG preview of INPUT_PATH (no...
  schema         Print the JSON Schema a diagram YAML is validated...
  sync           Sync position/size changes made in an edited DRAWIO_PATH...
  validate       Check INPUT_PATH for Fatal/Warning issues without...

  New to zook, or an AI agent writing a diagram? Start with `zook guide`.
```

See [Usage](usage.md) for details on each subcommand.

## Verifying It Works

Confirm you can generate a pptx from the bundled sample YAML (`docs/example.yaml`).

```bash
.venv/bin/zook build docs/example.yaml -o example.pptx
```

Success looks like `Wrote example.pptx` printed, with exit code `0`.

## Running the Tests

```bash
.venv/bin/pytest tests/ -v
```
