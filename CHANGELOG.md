# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CI now measures branch coverage on every push/PR and fails the build if it
  drops below 85% (`pytest --cov=zook --cov-fail-under=85`). The README's
  coverage and test-result badges are generated from that same run's real
  output (`scripts/update_badges.py`, committed to `.github/badges/` on
  pushes to `main`), not a third-party dashboard.

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
