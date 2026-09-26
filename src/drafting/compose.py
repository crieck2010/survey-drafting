"""Compose deliverables: .sadj.json + parcel + style -> plat/plan/map PDF.

Pipeline:

1. Read the ``.sadj.json`` contract and enforce the validity gate --
   drafting is refused (loudly) when the adjustment is not VALID.
2. Load the parcel definition, resolve point names against the
   adjusted coordinates (single source of truth).
3. Assemble the toggleable layer stack (basemap raster optional).
4. Lay out the sheet: viewport at the requested scale, title strip
   with seal/signature block (plats), north arrow, scale bar, legend,
   line/curve tables.
5. Render vector PDF, then append the adjustment justification report
   (and the metes-and-bounds description for plats) as appendix pages.
6. Write a manifest JSON describing the whole deliverable set with
   SHA-256 provenance.

Engine-only: all inputs are file paths / plain dicts so the desktop
app (build #5) can call :func:`compose_deliverable` directly.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from typing import Dict, List, Optional

from . import geometry
from .sadj import DraftRefused, check_validity, read_sadj
from .geometry import load_parcel, resolve_parcel
from .layers import Layer, WorldFileRaster, build_layers
from .layout import (
    SHEETS, draw_legend, draw_north_arrow, draw_scale_bar,
    draw_symbol, draw_title_strip, parse_scale, Viewport,
)
from .pdf import PDFDocument
from .styles import Style


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _points_by_name(doc) -> Dict[str, dict]:
    out = {}
    for p in doc.points:
        out[p.name] = {"x": p.easting, "y": p.northing,
                       "z": p.elevation, "held": p.held,
                       "source": p.source}
    return out


def _draw_layers(doc_pdf: PDFDocument, canvas, layers: Dict[str, Layer],
                 vp: Viewport, style: Style) -> None:
    for lname in ("basemap", "easements", "boundary", "linework",
                  "points", "control", "annotations"):
        layer = layers.get(lname)
        if layer is None or not layer.visible:
            continue
        st = style.layer(lname)
        for ent in layer.entities:
            _draw_entity(doc_pdf, canvas, ent, st, vp, style)


def _draw_entity(doc_pdf, c, ent: dict, st, vp: Viewport, style: Style) -> None:
    c.set_stroke(st.color)
    c.set_fill(st.color)
    c.set_width(st.width_pt)
    c.set_dash(st.linetype)
    t = ent["type"]
    if t == "line":
        pts = [vp.to_page(x, y) for x, y in ent["pts"]]
        c.polyline(pts)
    elif t == "polygon":
        pts = [vp.to_page(x, y) for x, y in ent["pts"]]
        if ent.get("hatch"):
            c.hatch_polygon(pts)
        c.polygon(pts, fill=False, stroke=True)
    elif t == "point":
        if ent["at"][0] is None or ent["at"][1] is None:
            return  # elevation-only station: nothing planimetric to draw
        x, y = vp.to_page(*ent["at"])
        symbol = ent.get("symbol") or st.symbol
        draw_symbol(c, x, y, symbol, st.symbol_size_pt, st)
        if ent.get("label"):
            ts = style.text_style("label")
            c.set_fill(ts.color)
            c.text(x + 4, y + 4, str(ent["label"]),
                   font=ts.font, size=ts.size_pt)
    elif t == "text":
        if ent["at"][0] is None or ent["at"][1] is None:
            return
        x, y = vp.to_page(*ent["at"])
        ts = style.text_style(ent.get("style", "label"))
        c.set_fill(ts.color)
        c.set_dash("solid")
        c.text(x, y, str(ent["text"]), font=ts.font, size=ts.size_pt)
    elif t == "raster":
        src = ent["source"]
        xmin, ymin, xmax, ymax = src.extent_world()
        x0, y0 = vp.to_page(xmin, ymin)
        x1, y1 = vp.to_page(xmax, ymax)
        data, w, h, kind = src.image()
        if kind in ("rgb", "gray"):
            kind = "flate-" + kind
        tag = doc_pdf.add_image(data, w, h, kind)
        c.image(x0, y0, x1 - x0, y1 - y0, tag)
    c.set_dash("solid")


def _append_text_pages(doc_pdf: PDFDocument, title: str,
                       text: str, page_w_pt: float) -> None:
    """Render monospace text pages (report / legal description)."""
    lines: List[str] = []
    for raw in text.splitlines():
        while len(raw) > 108:
            lines.append(raw[:108])
            raw = raw[108:]
        lines.append(raw)
    per_page = 62
    for i in range(0, max(len(lines), 1), per_page):
        c = doc_pdf.add_page(page_w_pt, page_w_pt * 11 / 17)
        c.set_fill((0, 0, 0))
        c.text(36, page_w_pt * 11 / 17 - 36, title,
               font="Courier-Bold", size=11)
        y = page_w_pt * 11 / 17 - 58
        for line in lines[i:i + per_page]:
            c.text(36, y, line, font="Courier", size=8)
            y -= 11.5


def compose_deliverable(sadj_path: str, parcel_path: str, style: Style,
                        out_pdf: str, options: Optional[dict] = None
                        ) -> dict:
    """Build the deliverable PDF + manifest. Returns the manifest dict.

    ``options`` keys: kind ("plat"|"plan"|"map"), sheet (SHEETS key),
    scale ("fit" or standard), title, location, client, firm,
    project_no, drawn_by, checked_by, date, surveyor {name, license_no,
    state}, basis_of_bearings, datum_note, basemap (image path or
    RasterSource, e.g. survey-basemap's GeoTIFFRasterSource),
    basemap_world (world file path), hide (list of layer names),
    sheet_no, sheet_count.
    """
    opts = dict(options or {})
    kind = opts.get("kind", "plat")
    if kind not in ("plat", "plan", "map"):
        raise ValueError(f"kind must be plat|plan|map, got {kind!r}")

    # 1. Validity gate.
    doc = read_sadj(sadj_path)
    check_validity(doc)  # raises DraftRefused naming failed criteria

    # 2. Parcel resolved against the adjusted coordinates.
    parcel_spec = load_parcel(parcel_path)
    units = parcel_spec.get("units", "ft")
    points = _points_by_name(doc)
    parcel = resolve_parcel(
        parcel_spec,
        {n: _Pt(p) for n, p in points.items()},
        x_of=lambda p: p.x,
        y_of=lambda p: p.y,
    )

    # 3. Layers.
    basemap = None
    if opts.get("basemap") is not None:
        _bm = opts["basemap"]
        if isinstance(_bm, str):
            basemap = WorldFileRaster(_bm, opts.get("basemap_world"))
        elif hasattr(_bm, "extent_world") and hasattr(_bm, "image"):
            basemap = _bm  # a RasterSource (e.g. survey-basemap GeoTIFF)
        else:
            raise ValueError(
                "basemap option must be an image path or a RasterSource "
                f"(extent_world/image), got {type(_bm).__name__}")
    layers = build_layers(parcel, points, style, basemap=basemap)
    for hidden in opts.get("hide") or []:
        if hidden in layers:
            layers[hidden].visible = False
        else:
            raise ValueError(f"unknown layer {hidden!r}; known: "
                             f"{sorted(layers)}")

    # 4. Sheet + viewport.
    sheet = opts.get("sheet", "ARCH_D")
    if sheet not in SHEETS:
        raise ValueError(f"unknown sheet {sheet!r}; choose from "
                         f"{sorted(SHEETS)}")
    sw_in, sh_in = SHEETS[sheet]
    sw, sh = sw_in * 72.0, sh_in * 72.0
    margin = 36.0
    strip_w = 4.5 * 72.0
    strip_x0 = sw - margin - strip_w
    vrect = (margin, margin, strip_x0 - 12 - margin, sh - 2 * margin)

    bbox = _content_bbox(layers)
    scale = parse_scale(str(opts.get("scale", "fit")), units)
    vp = Viewport(bbox, vrect, scale, units)

    doc_pdf = PDFDocument()
    c = doc_pdf.add_page(sw, sh)

    # sheet border
    c.set_stroke((0, 0, 0))
    c.set_width(1.5)
    c.set_dash("solid")
    c.rect(margin, margin, sw - 2 * margin, sh - 2 * margin, fill=False)

    # 5. Draw.
    _draw_layers(doc_pdf, c, layers, vp, style)

    vx, vy, vw, vh = vrect
    draw_north_arrow(c, vx + vw - 40, vy + vh - 48, 44.0, style)
    draw_scale_bar(c, vx + 24, vy + 30, vp.scale, units, style)
    draw_legend(c, vx + vw - 150, vy + 24,
                [("Boundary", "boundary", "line"),
                 ("Control", "control", "symbol"),
                 ("Survey points", "points", "symbol"),
                 ("Easement", "easements", "dash")], style)

    info = dict(opts)
    info["scale_label"] = vp.scale_label()
    draw_title_strip(c, strip_x0, margin, strip_w, sh - 2 * margin,
                     info, parcel, doc, style, units,
                     seal=(kind == "plat"), tables=(kind != "map"))

    # 6. Appendices: the justification report travels with the plat.
    report_path = None
    if doc.report:
        base = os.path.dirname(os.path.abspath(sadj_path))
        cand = doc.report if os.path.isabs(doc.report) else \
            os.path.join(base, doc.report)
        if os.path.exists(cand):
            report_path = cand
    if report_path:
        with open(report_path, "r", encoding="utf-8") as fh:
            _append_text_pages(doc_pdf, "ADJUSTMENT REPORT (appendix)",
                               fh.read(), sw)
    if kind == "plat":
        from .legal import generate_legal_description
        coords = {n: (p["x"], p["y"]) for n, p in points.items()}
        legal = generate_legal_description(
            parcel,
            header={"designation": parcel.name,
                    "location": opts.get("location", ""),
                    "basis_of_bearings": opts.get("basis_of_bearings", ""),
                    "monuments": opts.get("monuments", "")},
            point_coords=coords)
        _append_text_pages(doc_pdf, "LEGAL DESCRIPTION (appendix)",
                           legal, sw)

    pdf_bytes = doc_pdf.build()
    with open(out_pdf, "wb") as fh:
        fh.write(pdf_bytes)

    # 7. Manifest with provenance.
    manifest = {
        "format": "survey-drafting/deliverable",
        "schema_version": 1,
        "generator": f"survey-drafting 0.1.0",
        "kind": kind,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "inputs": {
            "sadj": {"path": sadj_path, "sha256": sha256_file(sadj_path)},
            "parcel": {"path": parcel_path,
                       "sha256": sha256_file(parcel_path)},
            "report": ({"path": report_path,
                        "sha256": sha256_file(report_path)}
                       if report_path else None),
        },
        "outputs": {"pdf": {"path": out_pdf,
                            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                            "bytes": len(pdf_bytes)}},
        "validity": doc.validity.get("valid"),
        "sheet": sheet,
        "scale": vp.scale_label(),
        "units": units,
    }
    manifest_path = os.path.splitext(out_pdf)[0] + ".manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def _content_bbox(layers: Dict[str, Layer]):
    xs, ys = [], []
    for layer in layers.values():
        if not layer.visible:
            continue
        for ent in layer.entities:
            t = ent["type"]
            if t in ("line", "polygon"):
                for x, y in ent["pts"]:
                    xs.append(x)
                    ys.append(y)
            elif t in ("point", "text"):
                if ent["at"][0] is not None and ent["at"][1] is not None:
                    xs.append(ent["at"][0])
                    ys.append(ent["at"][1])
            elif t == "raster":
                xmin, ymin, xmax, ymax = ent["source"].extent_world()
                xs += [xmin, xmax]
                ys += [ymin, ymax]
    if not xs:
        raise ValueError("nothing visible to draw")
    return min(xs), min(ys), max(xs), max(ys)


class _Pt:
    """Duck-typed point accessor for resolve_parcel."""

    def __init__(self, d: dict):
        self._d = d

    @property
    def x(self):
        return self._d["x"]

    @property
    def y(self):
        return self._d["y"]
