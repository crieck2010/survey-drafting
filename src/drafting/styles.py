"""User-dictated styling for deliverables.

The same philosophy as the weights config in build #2: presentation is
a human-editable, validated JSON document, not buried constants. The
desktop app (build #5) will edit this file; the engine validates it
and fails loud on any problem, naming the exact key.

``draft style-template`` prints the default style with documentation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

FORMAT = "survey-drafting/style"
SCHEMA_VERSION = 1

LINE_TYPES = ("solid", "dashed", "dotted", "dashdot")
SYMBOLS = ("circle", "square", "triangle", "cross", "none")
FONTS = ("Helvetica", "Helvetica-Bold", "Times-Roman", "Courier")

# Layers the composer knows about. Extra user layers are allowed; they
# just need a style entry or they fall back to DEFAULT_LAYER_STYLE.
KNOWN_LAYERS = (
    "control", "boundary", "linework", "points",
    "annotations", "easements", "basemap",
)


class StyleError(ValueError):
    """The style sheet is malformed."""


def _color(value: Any, where: str) -> tuple:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(not isinstance(c, int) or not 0 <= c <= 255 for c in value)
    ):
        raise StyleError(
            f"{where}: color must be [R, G, B] ints 0-255, got {value!r}"
        )
    return (value[0], value[1], value[2])


@dataclass
class LayerStyle:
    color: tuple = (0, 0, 0)
    width_pt: float = 0.75
    linetype: str = "solid"
    symbol: str = "none"
    symbol_size_pt: float = 6.0
    fill: bool = False

    def validate(self, where: str) -> None:
        if self.width_pt <= 0:
            raise StyleError(f"{where}: width_pt must be positive")
        if self.linetype not in LINE_TYPES:
            raise StyleError(
                f"{where}: linetype must be one of {LINE_TYPES}, "
                f"got {self.linetype!r}"
            )
        if self.symbol not in SYMBOLS:
            raise StyleError(
                f"{where}: symbol must be one of {SYMBOLS}, "
                f"got {self.symbol!r}"
            )
        if self.symbol_size_pt <= 0:
            raise StyleError(f"{where}: symbol_size_pt must be positive")


@dataclass
class TextStyle:
    font: str = "Helvetica"
    size_pt: float = 8.0
    color: tuple = (0, 0, 0)

    def validate(self, where: str) -> None:
        if self.font not in FONTS:
            raise StyleError(
                f"{where}: font must be one of {FONTS}, got {self.font!r}"
            )
        if self.size_pt <= 0:
            raise StyleError(f"{where}: size_pt must be positive")


@dataclass
class Style:
    layers: Dict[str, LayerStyle] = field(default_factory=dict)
    text: Dict[str, TextStyle] = field(default_factory=dict)
    title_font: str = "Helvetica-Bold"

    def layer(self, name: str) -> LayerStyle:
        return self.layers.get(name, LayerStyle())

    def text_style(self, name: str) -> TextStyle:
        return self.text.get(name, TextStyle())


def _default_layers() -> Dict[str, LayerStyle]:
    return {
        "control": LayerStyle(color=(200, 0, 0), width_pt=1.0,
                              symbol="triangle", symbol_size_pt=9.0),
        "boundary": LayerStyle(color=(0, 0, 0), width_pt=1.75),
        "linework": LayerStyle(color=(60, 60, 60), width_pt=0.75),
        "points": LayerStyle(color=(0, 0, 180), width_pt=0.75,
                             symbol="circle", symbol_size_pt=5.0),
        "annotations": LayerStyle(color=(0, 0, 0), width_pt=0.5),
        "easements": LayerStyle(color=(0, 120, 0), width_pt=0.75,
                                linetype="dashed"),
        "basemap": LayerStyle(color=(0, 0, 0), width_pt=0.5),
    }


def _default_text() -> Dict[str, TextStyle]:
    return {
        "label": TextStyle("Helvetica", 7.0, (0, 0, 0)),
        "title": TextStyle("Helvetica-Bold", 14.0, (0, 0, 0)),
        "heading": TextStyle("Helvetica-Bold", 10.0, (0, 0, 0)),
        "table": TextStyle("Helvetica", 7.0, (0, 0, 0)),
        "note": TextStyle("Helvetica", 7.5, (40, 40, 40)),
    }


DEFAULT_STYLE = Style(layers=_default_layers(), text=_default_text())


def style_template() -> dict:
    """The default style as a documented JSON-serializable dict."""

    def ls(s: LayerStyle) -> dict:
        return {
            "color": list(s.color),
            "width_pt": s.width_pt,
            "linetype": s.linetype,
            "symbol": s.symbol,
            "symbol_size_pt": s.symbol_size_pt,
            "fill": s.fill,
        }

    def ts(s: TextStyle) -> dict:
        return {"font": s.font, "size_pt": s.size_pt, "color": list(s.color)}

    return {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "_doc": (
            "survey-drafting style sheet. layers: per-layer drawing style "
            "(color as [R,G,B] 0-255, width_pt, linetype solid|dashed|dotted|"
            "dashdot, symbol circle|square|triangle|cross|none). text: named "
            "text styles. Unknown layers fall back to a plain black style."
        ),
        "layers": {k: ls(v) for k, v in _default_layers().items()},
        "text": {k: ts(v) for k, v in _default_text().items()},
    }


def load_style(path: str) -> Style:
    """Load and validate a style sheet. Fails loud on any problem."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise StyleError(f"{path}: cannot read as JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise StyleError(f"{path}: top level must be a JSON object")
    if raw.get("format") != FORMAT:
        raise StyleError(
            f"{path}: expected format {FORMAT!r}, got {raw.get('format')!r}"
        )
    version = raw.get("schema_version")
    if not isinstance(version, int):
        raise StyleError(f"{path}: schema_version must be an integer")
    if version > SCHEMA_VERSION:
        raise StyleError(
            f"{path}: schema_version {version} newer than supported "
            f"({SCHEMA_VERSION}); upgrade survey-drafting"
        )

    layers: Dict[str, LayerStyle] = {}
    for lname, spec in (raw.get("layers") or {}).items():
        where = f"{path}: layers[{lname!r}]"
        if not isinstance(spec, dict):
            raise StyleError(f"{where}: must be an object")
        try:
            ls = LayerStyle(
                color=_color(spec.get("color", [0, 0, 0]), where),
                width_pt=float(spec.get("width_pt", 0.75)),
                linetype=str(spec.get("linetype", "solid")),
                symbol=str(spec.get("symbol", "none")),
                symbol_size_pt=float(spec.get("symbol_size_pt", 6.0)),
                fill=bool(spec.get("fill", False)),
            )
        except (TypeError, ValueError) as exc:
            raise StyleError(f"{where}: {exc}") from exc
        ls.validate(where)
        layers[lname] = ls

    text: Dict[str, TextStyle] = {}
    for tname, spec in (raw.get("text") or {}).items():
        where = f"{path}: text[{tname!r}]"
        if not isinstance(spec, dict):
            raise StyleError(f"{where}: must be an object")
        ts = TextStyle(
            font=str(spec.get("font", "Helvetica")),
            size_pt=float(spec.get("size_pt", 8.0)),
            color=_color(spec.get("color", [0, 0, 0]), where),
        )
        ts.validate(where)
        text[tname] = ts

    return Style(layers=layers, text=text)
