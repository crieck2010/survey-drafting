"""Parcel and boundary geometry for drafting.

A parcel is an ordered list of segments over *adjusted* point names
(resolved from the ``.sadj.json`` point set -- the single source of
truth). Each segment is a straight leg or a circular curve. Inverses
(azimuth/distance) come from the ``survey-cogo`` engine; this module
adds the drafting layer on top: curve tables, areas with circular
segment corrections, unit handling, and plat-style labels.

Units: all internal math is in metres. Labels render in the parcel's
declared units -- ``"ft"`` (US survey foot, 1200/3937 m exactly, the
standard for NY plats) or ``"m"``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ._peers import require_cogo

FORMAT = "survey-drafting/parcel"
SCHEMA_VERSION = 1

# US survey foot, exact by definition.
M_PER_FT = 1200.0 / 3937.0
SQFT_PER_ACRE = 43560.0


class ParcelError(ValueError):
    """The parcel definition is malformed or inconsistent."""


def m_to_ft(m: float) -> float:
    return m / M_PER_FT


def ft_to_m(ft: float) -> float:
    return ft * M_PER_FT


@dataclass
class CurveParams:
    radius_m: float
    delta_deg: float
    turn: str            # "left" | "right"
    arc_m: float
    tangent_m: float
    chord_m: float       # implied by radius/delta (checked vs measured)
    chord_bearing_deg: float


@dataclass
class Leg:
    tag: str             # "L1", "C1", ...
    frm: str
    to: str
    kind: str            # "line" | "curve"
    azimuth_deg: float   # chord azimuth for curves
    distance_m: float    # chord length for curves
    curve: Optional[CurveParams] = None


@dataclass
class ResolvedParcel:
    name: str
    units: str
    legs: List[Leg]
    closed: bool
    misclosure_m: float
    area_m2: float
    perimeter_m: float

    def area_label(self) -> str:
        if self.units == "ft":
            sqft = self.area_m2 / (M_PER_FT ** 2)
            return f"{sqft:,.2f} sq ft ({sqft / SQFT_PER_ACRE:,.4f} acres)"
        ha = self.area_m2 / 10_000.0
        return f"{self.area_m2:,.2f} sq m ({ha:.4f} ha)"

    def distance_label(self, distance_m: float) -> str:
        if self.units == "ft":
            return f"{m_to_ft(distance_m):,.2f}'"
        return f"{distance_m:,.3f} m"


def format_bearing(azimuth_deg: float) -> str:
    """Azimuth -> quadrant bearing label, e.g. ``N 45°30'15" E``.

    Seconds round to the nearest whole second, the plat convention.
    """
    az = azimuth_deg % 360.0
    if az < 90:
        quad, base = ("N", "E"), az
    elif az < 180:
        quad, base = ("S", "E"), 180 - az
    elif az < 270:
        quad, base = ("S", "W"), az - 180
    else:
        quad, base = ("N", "W"), 360 - az
    total_sec = int(round(base * 3600.0))
    d, rem = divmod(total_sec, 3600)
    mnt, sec = divmod(rem, 60)
    if d == 90 and (mnt or sec):
        # rounding pushed past the quadrant edge; clamp cleanly
        d, mnt, sec = 90, 0, 0
    if d == 90 and mnt == 0 and sec == 0:
        # exactly due east/west reads "N 90°..." by convention
        quad = ("N", quad[1])
    return f"{quad[0]} {d:d}\u00b0{mnt:02d}'{sec:02d}\" {quad[1]}"


def format_distance(distance_m: float, units: str) -> str:
    if units == "ft":
        return f"{m_to_ft(distance_m):,.2f}'"
    return f"{distance_m:,.3f} m"


def load_parcel(path: str) -> dict:
    """Load and schema-check a parcel definition file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ParcelError(f"{path}: cannot read as JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ParcelError(f"{path}: top level must be a JSON object")
    if raw.get("format") != FORMAT:
        raise ParcelError(
            f"{path}: expected format {FORMAT!r}, got {raw.get('format')!r}"
        )
    version = raw.get("schema_version")
    if not isinstance(version, int):
        raise ParcelError(f"{path}: schema_version must be an integer")
    if version > SCHEMA_VERSION:
        raise ParcelError(
            f"{path}: schema_version {version} newer than supported "
            f"({SCHEMA_VERSION}); upgrade survey-drafting"
        )
    units = raw.get("units", "ft")
    if units not in ("ft", "m"):
        raise ParcelError(f"{path}: units must be 'ft' or 'm', got {units!r}")
    segments = raw.get("segments")
    if not segments or not isinstance(segments, list):
        raise ParcelError(f"{path}: 'segments' must be a non-empty list")
    return raw


def _curve_params(radius_m: float, delta_deg: float, turn: str,
                  chord_m: float, chord_az: float) -> CurveParams:
    if radius_m <= 0:
        raise ParcelError(f"curve radius must be positive, got {radius_m}")
    if not (0 < delta_deg < 180):
        raise ParcelError(
            f"curve delta must be in (0, 180) degrees, got {delta_deg}"
        )
    if turn not in ("left", "right"):
        raise ParcelError(f"curve turn must be 'left' or 'right', got {turn!r}")
    half = math.radians(delta_deg) / 2.0
    implied_chord = 2.0 * radius_m * math.sin(half)
    tol = max(0.005, 0.001 * chord_m)
    if abs(implied_chord - chord_m) > tol:
        raise ParcelError(
            f"curve geometry inconsistent: radius {radius_m:.3f} m + "
            f"delta {delta_deg:.4f}\u00b0 implies chord {implied_chord:.3f} m "
            f"but the endpoints are {chord_m:.3f} m apart"
        )
    return CurveParams(
        radius_m=radius_m,
        delta_deg=delta_deg,
        turn=turn,
        arc_m=radius_m * math.radians(delta_deg),
        tangent_m=radius_m * math.tan(half),
        chord_m=implied_chord,
        chord_bearing_deg=chord_az,
    )


def resolve_parcel(parcel: dict, points: Dict[str, object],
                   x_of, y_of) -> ResolvedParcel:
    """Resolve a parcel spec against adjusted points.

    ``points`` maps point name -> point record; ``x_of``/``y_of`` extract
    easting/northing in metres (so callers can pass SadjPoint or any
    duck-typed record). Raises ParcelError on any inconsistency.
    """
    cogo = require_cogo()
    name = str(parcel.get("name", "Untitled parcel"))
    units = parcel.get("units", "ft")
    to_m = ft_to_m if units == "ft" else (lambda v: v)

    legs: List[Leg] = []
    ordered_xy: List[tuple] = []
    n_line = n_curve = 0

    for i, seg in enumerate(parcel["segments"]):
        where = f"segments[{i}]"
        frm = seg.get("from")
        to = seg.get("to")
        if frm not in points:
            raise ParcelError(f"{where}: unknown point {frm!r}")
        if to not in points:
            raise ParcelError(f"{where}: unknown point {to!r}")
        e1, n1, e2, n2 = x_of(points[frm]), y_of(points[frm]), \
            x_of(points[to]), y_of(points[to])
        if e1 is None or n1 is None or e2 is None or n2 is None:
            raise ParcelError(
                f"{where}: point {frm!r} or {to!r} has no planimetric "
                "coordinates in the adjusted set"
            )
        p1 = cogo.Point(northing=n1, easting=e1, name=str(frm))
        p2 = cogo.Point(northing=n2, easting=e2, name=str(to))
        try:
            inv = cogo.inverse(p1, p2)
        except Exception as exc:
            raise ParcelError(
                f"{where}: cannot inverse {frm!r}->{to!r}: {exc}"
            ) from exc

        curve_spec = seg.get("curve")
        if curve_spec is None:
            n_line += 1
            legs.append(Leg(tag=f"L{n_line}", frm=str(frm), to=str(to),
                            kind="line", azimuth_deg=inv.azimuth,
                            distance_m=inv.distance))
        else:
            n_curve += 1
            cp = _curve_params(
                radius_m=to_m(float(curve_spec["radius"])),
                delta_deg=float(curve_spec["delta_deg"]),
                turn=str(curve_spec.get("turn", "right")),
                chord_m=inv.distance,
                chord_az=inv.azimuth,
            )
            legs.append(Leg(tag=f"C{n_curve}", frm=str(frm), to=str(to),
                            kind="curve", azimuth_deg=inv.azimuth,
                            distance_m=inv.distance, curve=cp))
        if i == 0:
            ordered_xy.append((e1, n1))
        ordered_xy.append((e2, n2))

    # Closure check.
    first = parcel["segments"][0]["from"]
    last = parcel["segments"][-1]["to"]
    closed = first == last
    misclosure = 0.0
    if not closed:
        e1, n1 = x_of(points[first]), y_of(points[first])
        e2, n2 = x_of(points[last]), y_of(points[last])
        misclosure = math.hypot(e2 - e1, n2 - n1)

    # Area: chord polygon by shoelace (signed, to learn the winding),
    # plus circular-segment corrections for curves. A curve's segment is
    # added when the arc bulges toward the interior -- i.e. when the
    # turn direction matches the interior side (left for CCW, right
    # for clockwise traversal).
    signed = 0.0
    n = len(ordered_xy)
    for i in range(n):
        x1, y1 = ordered_xy[i]
        x2, y2 = ordered_xy[(i + 1) % n]
        signed += x1 * y2 - x2 * y1
    signed /= 2.0
    ccw = signed > 0
    area = abs(signed)
    for leg in legs:
        if leg.kind == "curve" and leg.curve is not None:
            cp = leg.curve
            dr = math.radians(cp.delta_deg)
            seg_area = 0.5 * cp.radius_m ** 2 * (dr - math.sin(dr))
            toward_interior = (cp.turn == "left") == ccw
            area += seg_area if toward_interior else -seg_area
    area = abs(area)

    perimeter = sum(
        leg.curve.arc_m if leg.kind == "curve" and leg.curve else leg.distance_m
        for leg in legs
    )

    return ResolvedParcel(
        name=name, units=units, legs=legs, closed=closed,
        misclosure_m=misclosure, area_m2=area, perimeter_m=perimeter,
    )
