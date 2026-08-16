# Architecture Diagram Generator — Requirements Specification

**Version:** 0.1 (requirements-analysis phase)
**Date:** 2026-07-25
**Status:** Draft / input for detailed requirements definition

---

## 1. Overview

Build a new tool that automatically generates PowerPoint (.pptx) slides from a cloud architecture definition written in YAML. Diagrams are managed as code (Git), keeping changes clearly diffable. Longer term, an LLM is expected to generate the YAML itself, so a diagram comes out of just handing over requirements — "semi-automated generation."

## 2. Background & Problem

- Existing diagrams-as-code tools (e.g. awsdac) get you "managed as code," "AWS icons," and "auto-layout," but are constrained on **precise aspect-ratio control** and **direct PowerPoint output**.
- Running a conversion script as an extra step forces a compromise every time and is costly to maintain.
- In practice at Japanese enterprises ("JTC"), what matters is less visual polish and more "how easy it is to work with in PowerPoint," "how much information you can pack in," and "reproducibility/maintainability."
- Since the final deliverable is hand-edited by a human in PowerPoint anyway, a diagram that's "good enough as an editing starting point" is preferable to a perfectly optimized auto-layout.

## 3. Purpose

Build a single pipeline from YAML input to PowerPoint output that achieves:

- Managing architecture diagrams as code in Git, so changes are reviewable.
- Standard PowerPoint output, on the assumption a human will hand-edit it afterward.
- A machine-readable, low-ambiguity spec, with an eye toward LLM-driven YAML generation.

## 4. Scope

### 4.1 In scope (v1)

- Input format: **YAML**
- Output format: **PowerPoint (.pptx)**
- Supported provider: **AWS** (starting with the major services)
- Supported services (initial): Lambda / EC2 / RDS / S3
- Elements: VPC (drawn as a rectangular boundary), multiple Availability Zones (AZs)
- Generation unit: **1 YAML = 1 slide**

### 4.2 Out of scope (not handled in v1)

- Large-scale batch generation (generating dozens of diagrams in one run is not a target use case)
- Creating or operating actual cloud resources (no IaC functionality — rendering only)
- Fully automatic, polished layout (since hand-editing afterward is assumed, we won't over-optimize)

## 5. User Personas & Use Cases

| Persona | Primary use case |
|---|---|
| PM / Sales | Produce architecture diagrams (including hypothetical ones) for customer-facing proposals |
| SRE / Infrastructure engineer | Update and share architecture diagrams alongside internal infrastructure changes |
| Architect | Manage design-time architecture diagrams as code |

- Intended for a broad range of roles, including users without deep technical expertise.
- In real-world use, the primary flow is expected to be an LLM generating the YAML, with the user mainly handing over requirements and making small tweaks.

## 6. Usage Frequency & Scale

- Frequency: roughly once a week to a couple of times a month.
- Diagrams generated per run: a small number (bulk generation is out of scope).
- Performance requirements are lenient — some latency generating a single diagram is acceptable.

## 7. Functional Requirements

### 7.1 Input (YAML)

- R-IN-01: Architecture configurations can be defined in YAML.
- R-IN-02: A VPC can be defined, with multiple services placed inside it.
- R-IN-03: Multiple AZs can be defined, and services assigned to any of them.
- R-IN-04: Each service can be given a type (e.g. EC2) and a display name.
- R-IN-05: Each element can optionally be given a position (X, Y) and size.
- R-IN-06: Elements with no position specified are automatically arranged (see §10).
- R-IN-07: Relationships (links) between services can be defined (see §11).
- R-IN-08: The structure prioritizes unambiguous machine (LLM) generation and parsing over human readability.

### 7.2 Output (PowerPoint)

- R-OUT-01: One YAML file generates one .pptx slide.
- R-OUT-02: The slide's aspect ratio (16:9 / 4:3 etc.) can be specified.
- R-OUT-03: Generated diagram elements are placed in a form a human can select, move, and edit in PowerPoint (native shapes/images wherever possible).
- R-OUT-04: The look should draw on the official AWS PowerPoint template/icon conventions.
- R-OUT-05: Prioritize the ability to pack in information (labels, annotations, etc. attachable to elements) over aggressive whitespace optimization.

### 7.3 Drawing Elements

- R-DR-01: A VPC is drawn as a rectangle (frame) that can contain child elements.
- R-DR-02: An AZ can be drawn as a group nested inside a VPC (nested structure).
- R-DR-03: A service can be drawn as an icon plus a label.
- R-DR-04: The displayed icon size can be specified.
- R-DR-05: Support both a "connect with an arrow (link line)" pattern and a "no line, just placed inside a group/area" pattern for expressing relationships.

### 7.4 Icons & Providers

- R-IC-01: Initially support the major AWS services (Lambda / EC2 / RDS / S3).
- R-IC-02: Use official AWS SVG icons.
- R-IC-03: Design icons to be referenced from an external folder, so providers (AWS/GCP/Azure etc.) and custom icons are easy to add later (e.g. `icons/aws/`, `icons/gcp/`, `icons/custom/`).
- R-IC-04: Stay general enough to place arbitrary icon images, without being locked to one specific cloud.

### 7.5 Operations & CI/CD

- R-OP-01: YAML is managed in Git, with change diffs reviewable.
- R-OP-02: Provide a CLI command that produces PPTX from YAML.
- R-OP-03: This command can be invoked from a CI/CD pipeline, regenerating diagrams alongside infrastructure changes.

## 8. Non-Functional Requirements

- R-NF-01 (maintainability): Adding a provider or icon requires no changes to the core implementation.
- R-NF-02 (machine readability): Formally define the YAML schema (e.g. via JSON Schema) to reduce LLM generation errors.
- R-NF-03 (quality): The output only needs to be "reasonably good" — final polish is assumed to happen by hand in PowerPoint.
- R-NF-04 (portability): No dependency on a specific OS or GUI; works as a standalone CLI (runnable in CI/CD).
- R-NF-05 (extensibility): Keep an eye toward eventually exposing this as an MCP server, callable directly by an LLM such as Claude.

## 9. Direction for the Input Spec (YAML)

- The root holds overall diagram settings (canvas size / aspect ratio).
- Containment is expressed as a VPC → AZ → service hierarchy (children).
- Each element optionally has `x` / `y` / `size`; when omitted, it's auto-placed.
- Links are expressed as references between elements (from / to), with an optional label.
- Note: exact field names and the finalized schema are settled in the detailed-requirements phase. What follows is an illustration of the intended structure (not final).

```yaml
version: "1.0"
canvas:
  aspectRatio: "16:9"      # 16:9 / 4:3 etc.
vpcs:
  - name: "MyVPC"
    availabilityZones:
      - name: "AZ-A"
        children:
          - type: "EC2"
            name: "WebServer"
            # x / y / size are optional; auto-placed if omitted
          - type: "RDS"
            name: "Database"
      - name: "AZ-B"
        children:
          - type: "Lambda"
            name: "Worker"
links:
  - from: "WebServer"
    to: "Database"
    label: "3306"          # optional; a lineless layout is also allowed
```

## 10. Direction for Position & Layout

- Elements with no position specified are automatically arranged within their container (VPC/AZ).
- Elements with `x`/`y` specified are placed at that absolute position.
- Auto-placement and explicit positioning can be mixed (some elements positioned, the rest automatic).
- Prioritize a placement that's reasonable as a starting point for hand-editing over strict layout aesthetics.

## 11. Direction for Relationships & Links

- Services can be connected with arrows (link lines).
- Lines can optionally carry a label (port number, protocol, etc.).
- It should also be possible to skip lines entirely and simply place icons inside a group/area.

## 12. Future Extensions

- Expose this as an MCP server so an LLM such as Claude can semi-automate "hand over requirements → generate YAML → produce the diagram."
- To that end, keep the YAML schema and generation rules maintained as a **spec written for AI consumption**.
- Extend in stages to multi-cloud (GCP/Azure) and arbitrary icon references.

## 13. Constraints & Assumptions

- This is a rendering-only tool; it does not provision or modify actual infrastructure.
- The final deliverable is assumed to be hand-edited by a human in PowerPoint.
- Initial service support is limited to AWS's Lambda / EC2 / RDS / S3.

## 14. Open Items (to be settled in detailed requirements)

1. The formal YAML schema definition (field names, required/optional, enums, types); whether to formalize it as JSON Schema.
2. Behavior when an aspect ratio is specified (letterbox / stretch / auto-adjust).
3. Whether diagram elements in PowerPoint should be native shapes or embedded images (a tradeoff against ease of hand-editing).
4. Drawing rules for nested AZ/VPC representation (border color, background color, label position).
5. The auto-layout algorithm (is a simple grid alignment sufficient?).
6. The CLI's argument spec and how it integrates into CI/CD.
7. Implementation language and key libraries (e.g. Python + python-pptx is assumed, but not finalized until the detailed-design phase).

---

*This document is a deliverable of the requirements-analysis phase. Detailed requirements and technology selection happen in the next phase.*
