"""survey-drafting: plats, plans, and maps from adjusted survey data.

Build #3 of the SurveySuite desktop product. It owns the
**adjusted coordinates -> professional deliverables** step:
``.sadj.json`` (from survey-adjust-workflow) in, plat/plan/map PDF out,
with the adjustment's validity gate, weights, and justification report
travelling with the deliverable.

Engine-only, zero third-party dependencies. The peer engine
``survey-cogo`` supplies inverses and area; everything else here is
self-contained, including the minimal vector PDF writer.
"""

from __future__ import annotations

from .sadj import (
    DraftRefused,
    SadjDoc,
    SadjPoint,
    check_validity,
    read_sadj,
)
from .geometry import (
    ResolvedParcel,
    format_bearing,
    load_parcel,
    resolve_parcel,
)
from .styles import DEFAULT_STYLE, Style, load_style, style_template
from .layers import Layer, WorldFileRaster, build_layers
from .compose import compose_deliverable

__version__ = "0.1.1"

__all__ = [
    "__version__",
    "DraftRefused",
    "SadjDoc",
    "SadjPoint",
    "check_validity",
    "read_sadj",
    "ResolvedParcel",
    "format_bearing",
    "load_parcel",
    "resolve_parcel",
    "DEFAULT_STYLE",
    "Style",
    "load_style",
    "style_template",
    "Layer",
    "WorldFileRaster",
    "build_layers",
    "compose_deliverable",
]
