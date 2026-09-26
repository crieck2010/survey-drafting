"""Metes-and-bounds legal description generator.

Produces the written legal description that accompanies a plat: a
point of beginning, then "thence <bearing>, <distance> to ..." for
each leg (with curve calls spelled out), closing back to the point of
beginning, with the computed area. The caller supplies the header
(location, lot designation, basis of bearings, monumentation); the
calls themselves come from the resolved parcel so the description can
never disagree with the drawing.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .geometry import ResolvedParcel, format_bearing, format_distance, m_to_ft


def generate_legal_description(
    parcel: ResolvedParcel,
    header: Optional[Dict[str, str]] = None,
    point_coords: Optional[Dict[str, tuple]] = None,
) -> str:
    """Render a metes-and-bounds description for a resolved parcel.

    ``header`` may carry: location, designation, basis_of_bearings,
    monuments, surveyor, date. ``point_coords`` maps point name ->
    (easting, northing) in metres, used to tie the point of beginning
    to coordinates when provided.
    """
    header = header or {}
    lines: List[str] = []
    push = lines.append

    if header.get("designation"):
        push(f"BEING {header['designation']}")
        push("")
    if header.get("location"):
        push(f"SITUATE in {header['location']}")
        push("")
    push("Bounded and described as follows:")
    push("")

    legs = parcel.legs
    if not legs:
        raise ValueError("parcel has no legs")

    pob = legs[0].frm
    pob_note = ""
    if point_coords and pob in point_coords:
        e, n = point_coords[pob]
        if parcel.units == "ft":
            pob_note = (
                f" (having coordinates E {m_to_ft(e):,.2f}', "
                f"N {m_to_ft(n):,.2f}')"
            )
        else:
            pob_note = f" (E {e:,.3f}, N {n:,.3f})"
    push(f"BEGINNING at point {pob!r}{pob_note},")

    for leg in legs:
        brg = format_bearing(leg.azimuth_deg)
        if leg.kind == "line":
            dist = format_distance(leg.distance_m, parcel.units)
            push(f"thence {brg}, a distance of {dist} to point {leg.to!r};")
        else:
            cp = leg.curve
            assert cp is not None
            arc = format_distance(cp.arc_m, parcel.units)
            rad = format_distance(cp.radius_m, parcel.units)
            chord = format_distance(cp.chord_m, parcel.units)
            chord_brg = format_bearing(cp.chord_bearing_deg)
            push(
                f"thence along a curve to the {cp.turn} having a radius of "
                f"{rad}, a central angle of {cp.delta_deg:.2f} degrees, "
                f"an arc length of {arc} (chord {chord_brg}, {chord}) "
                f"to point {leg.to!r};"
            )

    push("thence to the POINT OF BEGINNING.")
    push("")
    push(f"Containing {parcel.area_label()}, more or less.")
    if header.get("basis_of_bearings"):
        push("")
        push(f"Basis of bearings: {header['basis_of_bearings']}.")
    if header.get("monuments"):
        push("")
        push(f"Monumentation: {header['monuments']}.")
    if not parcel.closed:
        push("")
        push(
            "NOTE: the boundary as described does not close; "
            f"misclosure {format_distance(parcel.misclosure_m, parcel.units)}."
        )
    return "\n".join(lines)
