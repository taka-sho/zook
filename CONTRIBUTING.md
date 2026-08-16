# Contributing to zook

Thanks for your interest in zook! This is a small, focused tool and
contributions are welcome — bug reports, docs fixes, new registry entries, and
features all help.

## Ground rules

- **Read the docs first.** `AGENTS.md` explains what zook is and how it's meant
  to be driven; `docs/yaml-spec.md` is the authoritative input spec; the
  design rationale lives in `docs/detailed-design-pptx.md` and
  `docs-site/design-notes.md`.
- **Keep render and detection in agreement.** The overlap/crossing checks and
  the renderers derive geometry from the same functions on purpose. If you
  change how something is drawn, change the matching check too — a diagram
  reported clean must render clean.
- **Warnings vs Fatal.** Structural breakage (schema violation, duplicate id,
  dangling link) is Fatal; drawing-level issues (overlaps, unknown icons) are
  Warnings. Don't turn one into the other without discussion.

## Development setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest tests/ -v
```

## Before opening a pull request

- **Run the tests.** `.venv/bin/pytest tests/` must pass.
- **Keep the schema copies in sync.** If you edit `docs/zook.schema.json` or
  `docs/icon-registry.schema.json`, copy the same content to the matching file
  under `src/zook/schemas/` — the two are required to be byte-identical. Same
  for `docs/registry.<provider>.yaml` → `src/zook/data/icons/<provider>/`.
- **Keep the reference diagrams warning-free.** `docs/example.yaml`,
  `docs/example-cloud-actors.yaml` and `docs/patterns/*.yaml` are regression
  fixtures expected to validate with zero warnings; check with `zook validate`.
- **Add tests** for new behavior, and update the docs (`docs-site/` and the
  spec under `docs/`) when you change the input format or CLI.

## Reporting bugs

Open an issue with the smallest YAML that reproduces the problem and the exact
command you ran. For a rendering issue, attaching the `zook preview` PNG helps.

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
