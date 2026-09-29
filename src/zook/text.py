"""Text measurement without font files: how wide a label is, and where it wraps.

Layout used to give every label a fixed one-line box, so a Japanese label of
six or more characters, a long English one, or an explicit line break
silently wrapped onto lines nothing had reserved room for - running into the
arrow below, the container edge or the next row - and every overlap check
still said "clear", because it measured the box, not the text.

There is no font file to measure with (and the renderer is PowerPoint, not
us), so widths are estimated per character from Unicode East Asian Width: a
full-width character (CJK, kana, full-width forms) is 1 em, a Latin one is
roughly half that, with narrow/wide classes for the letters whose width
differs most. The estimate errs slightly wide, so a label reserved one line
really fits on one line in the default fonts (Calibri / MS PGothic / Yu
Gothic); that is what the overlap checks need.

Units: font sizes are points; everything returned is logical units
(1 pt = 4/3 logical units, see render.LOGICAL_TO_PT).
"""

from __future__ import annotations

import unicodedata

PT_TO_LOGICAL = 4 / 3
LINE_SPACING = 1.2  # PowerPoint's single line spacing, as a multiple of the font size
TEXT_PADDING_EM = 0.4  # breathing room above/below the lines of a label box

_NARROW = set("iljtfrI.,:;!|'`()[]{} ")
_WIDE = set("mwMW@%&")


def _is_full_width(ch: str) -> bool:
    """Wide/full-width characters, plus the East-Asian "ambiguous" ones beyond
    Latin-1 - arrows, circled numbers, em dashes, ellipses, box drawing,
    Greek/Cyrillic: the CJK fonts that draw Japanese labels draw these full
    width too, and even Calibri's are near 1em."""
    eaw = unicodedata.east_asian_width(ch)
    return eaw in ("W", "F") or (eaw == "A" and ord(ch) > 0xFF)


def char_width_em(ch: str) -> float:
    if _is_full_width(ch):
        return 1.0
    if unicodedata.combining(ch):
        return 0.0
    if ch in _NARROW:
        return 0.3
    if ch in _WIDE:
        return 0.9
    if ch.isupper():
        return 0.65
    return 0.55


def text_width(text: str, font_size: float) -> float:
    """Width of one line of `text` at `font_size` points, in logical units."""
    return sum(char_width_em(ch) for ch in text) * font_size * PT_TO_LOGICAL


def line_height(font_size: float) -> float:
    return font_size * PT_TO_LOGICAL * LINE_SPACING


def text_block_height(line_count: int, font_size: float) -> float:
    """Height of a label box holding `line_count` lines, padding included.
    One line at 9pt is 18 - the fixed label height layout used before."""
    return max(1, line_count) * line_height(font_size) + font_size * TEXT_PADDING_EM


def _tokens(paragraph: str) -> list[str]:
    """Break opportunities as PowerPoint sees them: between Latin words
    (a word keeps its trailing spaces), after a hyphen or slash inside one,
    and between any two full-width characters."""
    tokens: list[str] = []
    word = ""
    for ch in paragraph:
        if _is_full_width(ch):
            if word:
                tokens.append(word)
                word = ""
            tokens.append(ch)
        elif ch in (" ", "-", "/"):
            word += ch
            tokens.append(word)
            word = ""
        else:
            word += ch
    if word:
        tokens.append(word)
    return tokens


def wrap_lines(text: str, font_size: float, max_width: float) -> list[str]:
    """`text` split into the lines it will occupy in a box `max_width` wide:
    explicit line breaks first, then greedy word wrap, as PowerPoint does -
    a word that doesn't fit on the current line starts the next one, and
    only a word wider than a whole line is broken between characters."""

    def fits(line: str) -> bool:
        # (a tolerance: a box sized to the text and the text itself can differ
        # in the last bit, which broke "async" into "asyn" / "c")
        return text_width(line.rstrip(), font_size) <= max_width + 1e-6

    lines: list[str] = []
    for paragraph in text.replace("\r\n", "\n").split("\n"):
        current = ""
        for token in _tokens(paragraph):
            if fits(current + token):
                current += token
                continue
            if current.strip():
                lines.append(current.rstrip())
                current = ""
            token = token if current else token.lstrip()
            while len(token.rstrip()) > 1 and not fits(token):  # wider than a whole line
                cut = len(token)
                while cut > 1 and not fits(token[:cut]):
                    cut -= 1
                lines.append(token[:cut].rstrip())
                token = token[cut:]
            current = token
        lines.append(current.rstrip())
    return lines


def longest_word_width(text: str, font_size: float) -> float:
    """Width of the widest unbreakable run (a Latin word, up to a space,
    hyphen or slash) - what a box must fit to wrap `text` without breaking
    inside a word."""
    return max(
        (text_width(token.rstrip(), font_size) for line in text.replace("\r\n", "\n").split("\n") for token in _tokens(line)),
        default=0.0,
    )


def natural_width(text: str, font_size: float) -> float:
    """Width of the widest explicit line - the width the text wants unwrapped."""
    return max((text_width(line, font_size) for line in text.replace("\r\n", "\n").split("\n")), default=0.0)
