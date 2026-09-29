"""Error policy per docs/yaml-spec.md sec9.

Fatal: structural breakage (schema violation, duplicate id, dangling link
reference). Raised as DiagramError and must stop generation with a non-zero
exit code.

Warning: cosmetic issues (unresolved icon type, out-of-canvas coordinates).
Collected and printed, generation continues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class DiagramError(Exception):
    """Fatal error. Generation must stop; CLI exits non-zero.

    `code` names the kind of error and `details` lists each problem as a
    dict (a schema violation's path, a YAML error's line and column, the
    unknown ids a link refers to and their close matches, ...) - what
    `--format json` reports as `errorCode`/`errorDetails` so an AI can fix
    the input without parsing the message."""

    def __init__(self, message: str, code: Optional[str] = None, details: Optional[list[dict]] = None):
        super().__init__(message)
        self.code = code
        self.details = details or []


def link_ref(link) -> dict:
    """How a Finding names a link: its endpoints, and its id when it has one."""
    ref = {"from": link.from_id, "to": link.to_id}
    if getattr(link, "id", None):
        ref["id"] = link.id
    return ref


class Finding(str):
    """A Warning message that also says what kind of problem it is (`code`)
    and which elements and links it concerns - while still *being* the
    message string, so everything that reads Warnings as text (reports, the
    doctor's weights, `in` checks) keeps working unchanged. See
    docs-site/usage.md "Machine-Readable Output" for the codes."""

    code: str
    elements: tuple
    links: tuple

    def __new__(cls, message: str, code: str, elements=(), links=()):
        finding = super().__new__(cls, message)
        finding.code = code
        finding.elements = tuple(elements)
        finding.links = tuple(link_ref(link) if not isinstance(link, dict) else link for link in links)
        return finding

    def __reduce__(self):  # keep code/ids through copy/pickle
        return (Finding, (str(self), self.code, self.elements, self.links))


def finding_detail(message: str) -> dict:
    """The `--format json` detail object for one Warning."""
    if isinstance(message, Finding):
        return {"code": message.code, "message": str(message), "elements": list(message.elements), "links": list(message.links)}
    return {"code": "warning", "message": str(message), "elements": [], "links": []}


@dataclass
class Warnings:
    messages: list[str] = field(default_factory=list)

    def add(self, message: str) -> None:
        self.messages.append(message)
