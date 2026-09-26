"""Sheet layout for deliverables.

Sheets (landscape, inches), a world->page viewport at standard
engineering scales, and the sheet furniture: title strip with the
seal/signature block, north arrow, graphic + numeric scale bar,
legend, and line/curve tables.

Coordinate convention: PDF points, origin at the page's bottom-left.
All world input is in metres.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from .geometry import M_PER_FT, format_bearing, format_distance

# (width_in, height_in), landscape.
SHEETS: Dict[str, Tuple[float, float]] = {
    "ANSI_A": (11.0, 8.5),
    "ANSI_B": (17.0, 11.0),
    "ANSI_C": (22.0, 17.0),
    "ANSI_D": (34.0, 22.0),
    "ANSI_E": (44.0, 34.0),
    "ARCH_C": (24.0, 18.0),
    "ARCH_D": (36.0, 24.0),
}

# Standard drawing scales. Imperial: feet per inch. Metric: ratio.
STD_SCALES_FT = (10, 20, 30, 40, 50, 60, 100)
STD_SCALES_M = (250, 500, 1000, 2000, 5000)

MARGIN_IN = 0.5
STRIP_WIDTH_IN = 4.5  # right-hand title strip


def parse_scale(spec: str, units: str) -> dict:
    """Parse a --scale argument.

    "fit" -> exact fit; "50" -> 1"=50' (ft) or 1:500 (m) snapped to the
    nearest standard scale at or below the request... actually: an
    explicit number must be a standard scale, else StyleError-like
    ValueError naming the valid choices.
    """
    spec = spec.strip().lower()
    if spec == "fit":
        return {"mode": "fit"}
    try:
        val = float(spec)
    except ValueError:
        raise ValueError(
            f"scale must be 'fit' or a standard scale, got {spec!r}")
    if units == "ft":
        if val not in STD_SCALES_FT:
            raise ValueError(
                f"scale {spec} is not standard for ft units; "
                f"choose from {STD_SCALES_FT} or 'fit'")
        return {"mode": "fixed", "units": "ft", "ft_per_in": val}
    if val not in STD_SCALES_M:
        raise ValueError(
            f"scale {spec} is not standard for metric units; "
            f"choose from {STD_SCALES_M} or 'fit'")
    return {"mode": "fixed", "units": "m", "ratio": val}


class Viewport:
    """World (metres) -> page (points) transform for the drawing area."""

    def __init__(self, bbox: Tuple[float, float, float, float],
                 rect_pt: Tuple[float, float, float, float],
                 scale: dict, units: str):
        xmin, ymin, xmax, ymax = bbox
        x0, y0, w, h = rect_pt
        bw = max(xmax - xmin, 1e-9)
        bh = max(ymax - ymin, 1e-9)

        if scale["mode"] == "fit":
            k = min(w / bw, h / bh) * 0.94
            self.scale = {"mode": "fit", "units": units,
                          "k_pt_per_m": k}
        else:
            if units == "ft":
                # 1 ft world = 72 / ft_per_in points
                k = 72.0 / (scale["ft_per_in"] * M_PER_FT)
            else:
                k = 72.0 / (scale["ratio"] * 0.0254)
            self.scale = dict(scale)
        self.k = k
        self.units = units
        # center the bbox in the viewport
        cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
        self.ox = x0 + w / 2.0 - cx * k
        self.oy = y0 + h / 2.0 - cy * k
        self.rect = rect_pt

    def to_page(self, x: float, y: float) -> Tuple[float, float]:
        return (self.ox + x * self.k, self.oy + y * self.k)

    def scale_label(self) -> str:
        s = self.scale
        if s["mode"] == "fit":
            if self.units == "ft":
                fpi = 72.0 / (self.k * M_PER_FT)
                return f"FIT (1\" = {fpi:.1f}')"
            ratio = 72.0 / (self.k * 0.0254)
            return f"FIT (1:{ratio:,.0f})"
        if self.units == "ft":
            return f"1\" = {s['ft_per_in']:g}'"
        return f"1:{s['ratio']:g}"


def _text(c, x, y, s, style, name="label", align="left"):
    ts = style.text_style(name)
    c.set_fill(ts.color)
    c.text(x, y, s, font=ts.font, size=ts.size_pt, align=align)


def draw_north_arrow(c, x: float, y: float, size_pt: float, style) -> None:
    """North arrow: circle with an arrowhead, 'N' above."""
    st = style.layer("annotations")
    c.set_stroke(st.color)
    c.set_fill(st.color)
    c.set_width(1.0)
    c.set_dash("solid")
    r = size_pt / 2.0
    c.circle(x, y, r, fill=False, stroke=True)
    # arrow: shaft + head pointing up
    c.polygon([(x, y - r * 0.7), (x - r * 0.28, y + r * 0.1),
               (x, y + r * 0.85), (x + r * 0.28, y + r * 0.1)], fill=True)
    ts = style.text_style("heading")
    c.set_fill(ts.color)
    c.text(x - ts.size_pt * 0.35, y + r + 2, "N",
           font=ts.font, size=ts.size_pt)


def draw_scale_bar(c, x: float, y: float, scale: dict, units: str,
                   style, bar_in: float = 2.0) -> None:
    """Graphic scale bar + numeric scale label at (x, y) [points]."""
    st = style.layer("annotations")
    ts = style.text_style("label")
    if scale["mode"] == "fit":
        k = scale["k_pt_per_m"]
        if units == "ft":
            world_units = bar_in * 72.0 / (k * M_PER_FT)  # feet
            unit = "ft"
        else:
            world_units = bar_in * 72.0 / k  # metres
            unit = "m"
        nice = _nice_number(world_units)
        bar_pt = nice * (k * M_PER_FT if units == "ft" else k)
        _draw_bar(c, x, y, bar_pt, nice, 4, unit, st, ts)
        return
    if units == "ft":
        fpi = scale["ft_per_in"]
        # bar spans a nice round number of feet close to bar_in inches
        nice = _nice_number(bar_in * fpi)
        bar_pt = nice / fpi * 72.0
        _draw_bar(c, x, y, bar_pt, nice, 4, "ft", st, ts)
    else:
        ratio = scale["ratio"]
        nice = _nice_number(bar_in * 0.0254 * ratio)
        bar_pt = nice / ratio / 0.0254 * 72.0
        _draw_bar(c, x, y, bar_pt, nice, 4, "m", st, ts)


def _nice_number(v: float) -> float:
    """Round to a 1/2/5 * 10^n number near v (for scale bars)."""
    if v <= 0:
        return 1.0
    exp = math.floor(math.log10(v))
    for m in (5, 2, 1):
        if m * 10 ** exp <= v:
            return m * 10 ** exp
    return 10 ** (exp - 1)


def _draw_bar(c, x, y, bar_pt, total, ndiv, unit, st, ts) -> None:
    h = 5.0
    c.set_stroke(st.color)
    c.set_width(0.75)
    c.set_dash("solid")
    div = bar_pt / ndiv
    for i in range(ndiv):
        if i % 2 == 0:
            c.set_fill((0, 0, 0))
        else:
            c.set_fill((255, 255, 255))
        c.rect(x + i * div, y, div, h, fill=True, stroke=True)
    c.set_fill(ts.color)
    for i in range(ndiv + 1):
        val = total * i / ndiv
        lab = f"{val:g}"
        if i == ndiv:
            lab += f" {unit}"
        c.text(x + i * div - 6, y - 9, lab, font=ts.font, size=6.5)


def draw_legend(c, x: float, y: float, entries: List[tuple], style) -> None:
    """entries: [(label, layer_name, kind)] kind in line/symbol/dash."""
    ts = style.text_style("label")
    c.set_fill(ts.color)
    c.text(x, y + 4, "LEGEND", font="Helvetica-Bold", size=8.0)
    yy = y - 10
    for label, layer_name, kind in entries:
        st = style.layer(layer_name)
        c.set_stroke(st.color)
        c.set_fill(st.color)
        c.set_width(max(st.width_pt, 0.75))
        c.set_dash("solid" if kind != "dash" else "dashed")
        if kind == "symbol":
            draw_symbol(c, x + 10, yy + 3, st.symbol, 7.0, st)
        else:
            c.line(x + 2, yy + 3, x + 18, yy + 3)
        c.set_dash("solid")
        c.set_fill(ts.color)
        c.text(x + 24, yy, label, font=ts.font, size=ts.size_pt)
        yy -= 13


def draw_symbol(c, x, y, symbol: str, size_pt: float, st) -> None:
    r = size_pt / 2.0
    c.set_stroke(st.color)
    c.set_fill(st.color)
    c.set_width(1.0)
    if symbol == "circle":
        c.circle(x, y, r, fill=False)
    elif symbol == "square":
        c.rect(x - r, y - r, 2 * r, 2 * r, fill=False)
    elif symbol == "triangle":
        c.polygon([(x, y + r), (x - r, y - r * 0.8), (x + r, y - r * 0.8)],
                  fill=False)
    elif symbol == "cross":
        c.line(x - r, y - r, x + r, y + r)
        c.line(x - r, y + r, x + r, y - r)
    elif symbol == "corner":
        # open circle with center dot: survey corner monument
        c.circle(x, y, r, fill=False)
        c.circle(x, y, 1.2, fill=True, stroke=False)


def draw_title_strip(c, x0: float, y0: float, w: float, h: float,
                     info: dict, parcel, doc, style, units: str,
                     seal: bool = True, tables: bool = True) -> None:
    """Right-hand title strip: title, tables, notes, seal block.

    (x0, y0) bottom-left, w x h points. Sections flow top -> bottom
    with ruled separators; the seal/signature block is fixed at the
    bottom.
    """
    st = style.layer("annotations")
    black = (0, 0, 0)
    c.set_stroke(black)
    c.set_width(1.25)
    c.set_dash("solid")
    c.rect(x0, y0, w, h, fill=False)

    pad = 8.0
    cx = x0 + pad
    top = y0 + h - pad

    def rule(yy):
        c.set_width(0.75)
        c.line(x0, yy, x0 + w, yy)

    def heading(yy, text):
        c.set_fill(black)
        c.text(cx, yy, text, font="Courier-Bold", size=10,
               align="left")
        return yy - 15

    # --- sheet title ---
    yy = top
    c.set_fill(black)
    c.text(x0 + w / 2, yy, info.get("title", "BOUNDARY SURVEY"),
           font="Courier-Bold", size=13, align="center")
    yy -= 17
    c.text(x0 + w / 2, yy, parcel.name, font="Courier-Bold", size=11,
           align="center")
    yy -= 15
    if info.get("location"):
        _text(c, cx, yy, info["location"], style, "note")
        yy -= 12
    if info.get("client"):
        _text(c, cx, yy, f"Client: {info['client']}", style, "note")
        yy -= 12
    yy -= 4
    rule(yy)
    yy -= 12

    # --- line table ---
    line_legs = [l for l in parcel.legs if l.kind == "line"]
    if tables and line_legs:
        yy = heading(yy, "LINE TABLE")
        colx = [cx, cx + 34, cx + 150]
        _text(c, colx[0], yy, "LINE", style, "table")
        _text(c, colx[1], yy, "BEARING", style, "table")
        _text(c, colx[2], yy, "DISTANCE", style, "table")
        yy -= 11
        for leg in line_legs:
            if yy < y0 + 235:
                raise ValueError(
                    "line table overflows the title strip: use a larger "
                    "sheet or split the plat across sheets")
            _text(c, colx[0], yy, leg.tag, style, "table")
            _text(c, colx[1], yy, format_bearing(leg.azimuth_deg),
                  style, "table")
            _text(c, colx[2], yy,
                  format_distance(leg.distance_m, units), style, "table")
            yy -= 11
        yy -= 4
        rule(yy)
        yy -= 12

    # --- curve table ---
    curve_legs = [l for l in parcel.legs if l.kind == "curve"]
    if tables and curve_legs:
        yy = heading(yy, "CURVE TABLE")
        colx = [cx, cx + 34, cx + 92, cx + 158, cx + 218]
        for t, xx in zip(("CURVE", "RADIUS", "DELTA", "ARC", "CHORD"),
                         colx):
            _text(c, xx, yy, t, style, "table")
        yy -= 11
        for leg in curve_legs:
            if yy < y0 + 235:
                raise ValueError(
                    "curve table overflows the title strip: use a larger "
                    "sheet or split the plat across sheets")
            cp = leg.curve
            _text(c, colx[0], yy, leg.tag, style, "table")
            _text(c, colx[1], yy, format_distance(cp.radius_m, units),
                  style, "table")
            _text(c, colx[2], yy, f"{cp.delta_deg:.2f}\u00b0", style, "table")
            _text(c, colx[3], yy, format_distance(cp.arc_m, units),
                  style, "table")
            _text(c, colx[4], yy, format_distance(cp.chord_m, units),
                  style, "table")
            yy -= 11
        yy -= 4
        rule(yy)
        yy -= 12

    # --- notes ---
    yy = heading(yy, "NOTES")
    notes = []
    if info.get("basis_of_bearings"):
        notes.append(f"1. Basis of bearings: {info['basis_of_bearings']}.")
    notes.append(f"2. Areas computed: {parcel.area_label()}.")
    notes.append(f"3. Distances in {'US survey feet' if units == 'ft' else 'metres'}.")
    if info.get("datum_note"):
        notes.append(f"4. {info['datum_note']}")
    notes.append(
        f"5. Coordinates adjusted by {doc.generator}; validity: "
        f"{'VALID' if doc.validity.get('valid') else 'NOT VALID'}. "
        "See adjustment report appendix.")
    for nnote in notes:
        for wrapped in _wrap(nnote, 52):
            if yy < y0 + 225:
                break
            _text(c, cx, yy, wrapped, style, "note")
            yy -= 10
        yy -= 2
    rule(yy - 4)
    yy -= 16

    # --- seal / signature block (fixed at bottom of strip) ---
    seal_h = 205.0 if seal else 0.0
    sy = y0 + pad
    if seal:
        c.set_width(1.0)
        c.rect(x0 + pad, sy, w - 2 * pad, seal_h, fill=False)
        c.set_fill(black)
        c.text(x0 + w / 2, sy + seal_h - 14, "PROFESSIONAL LAND SURVEYOR",
               font="Courier-Bold", size=9, align="center")
        # seal placeholder square (affixed at signing)
        sq = 92.0
        c.rect(x0 + pad + 8, sy + 56, sq, sq, fill=False)
        c.set_fill((120, 120, 120))
        c.text(x0 + pad + 8 + sq / 2 - 14, sy + 56 + sq / 2 - 3, "SEAL",
               font="Courier", size=10, align="left")
        # credential lines
        lx = x0 + pad + 8 + sq + 12
        lw = w - 2 * pad - 8 - sq - 12 - 8
        surv = info.get("surveyor", {})
        c.set_fill(black)
        c.text(lx, sy + 150, "Name:", font="Helvetica", size=7)
        c.line(lx, sy + 146, lx + lw, sy + 146)
        if surv.get("name"):
            c.text(lx + 34, sy + 150, surv["name"], font="Helvetica", size=7)
        c.text(lx, sy + 128, "License No.:", font="Helvetica", size=7)
        c.line(lx, sy + 124, lx + lw, sy + 124)
        if surv.get("license_no"):
            c.text(lx + 58, sy + 128, surv["license_no"],
                   font="Helvetica", size=7)
        c.text(lx, sy + 106, "State:", font="Helvetica", size=7)
        c.line(lx, sy + 102, lx + lw, sy + 102)
        if surv.get("state"):
            c.text(lx + 30, sy + 106, surv["state"], font="Helvetica", size=7)
        c.text(lx, sy + 82, "Signature:", font="Helvetica", size=7)
        c.line(lx, sy + 62, lx + lw, sy + 62)
        c.text(lx, sy + 44, "Date:", font="Helvetica", size=7)
        c.line(lx + 26, sy + 44, lx + lw, sy + 44)
        c.set_fill((120, 120, 120))
        c.text(x0 + pad + 8, sy + 12,
               "Seal and signature affixed to the signed original.",
               font="Helvetica-Oblique", size=6.5)

    # --- sheet index above the seal block ---
    iy = sy + seal_h + 14
    c.set_fill(black)
    c.text(cx, iy, f"SHEET {info.get('sheet_no', 1)} OF "
           f"{info.get('sheet_count', 1)}", font="Courier-Bold", size=10)
    iy -= 14
    _text(c, cx, iy, f"Scale: {info.get('scale_label', '')}", style, "note")
    iy -= 11
    _text(c, cx, iy, f"Date: {info.get('date', '')}", style, "note")
    iy -= 11
    if info.get("firm"):
        _text(c, cx, iy, info["firm"], style, "note")
        iy -= 11
    if info.get("project_no"):
        _text(c, cx, iy, f"Project: {info['project_no']}", style, "note")


def _wrap(text: str, width: int) -> List[str]:
    words = text.split()
    lines, cur = [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > width:
            lines.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    if cur:
        lines.append(cur)
    return lines
