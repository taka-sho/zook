"""Error policy per docs/yaml-spec.md sec9.

Fatal: structural breakage (schema violation, duplicate id, dangling link
reference). Raised as DiagramError and must stop generation with a non-zero
exit code.

Warning: cosmetic issues (unresolved icon type, out-of-canvas coordinates).
Collected and printed, generation continues.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field


class DiagramError(Exception):
    """Fatal error. Generation must stop; CLI exits non-zero."""


@dataclass
class Warnings:
    messages: list[str] = field(default_factory=list)

    def add(self, message: str) -> None:
        self.messages.append(message)

    def emit(self, stream=None) -> None:
        # `stream` must default lazily: binding sys.stderr at def-time would
        # capture whatever object sys.stderr was at import, not at call time,
        # breaking under legitimate redirection (e.g. Click's CliRunner).
        if stream is None:
            stream = sys.stderr
        for message in self.messages:
            print(f"Warning: {message}", file=stream)
