"""Minimal vector PDF writer (stdlib only, no third-party libraries).

Writes PDF 1.4 with a real cross-reference table: pages, vector
content (lines, polygons, hatches, rects, circles), text in the
standard 14 base fonts (no embedding needed), and raster images
(JPEG passed through with DCTDecode, PNG decoded to raw RGB and
Flate-encoded). Output opens in any standard reader.

Text alignment note: exact center/right alignment is supported for
the monospace Courier family (fixed 600/1000 em advance -- exact).
Proportional fonts render left-aligned; other alignments fall back
to left rather than fake the metrics.
"""

from __future__ import annotations

import math
import zlib
from typing import Dict, List, Optional, Tuple

# WinAnsi-safe substitutions for characters outside latin-1.
_TEXT_SUBS = {
    "\u0394": "Delta",   # Greek capital delta
    "\u03b4": "delta",
    "\u2032": "'",       # prime
    "\u2033": '"',       # double prime
    "\u2013": "-", "\u2014": "-",
    "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
    "\u00b0": "\u00b0",  # degree sign is fine in WinAnsi (0xB0)
}


def sanitize_text(s: str) -> str:
    out = []
    for ch in s:
        if ch in _TEXT_SUBS:
            out.append(_TEXT_SUBS[ch])
            continue
        try:
            ch.encode("latin-1")
            out.append(ch)
        except UnicodeEncodeError:
            out.append("?")
    return "".join(out)


def _esc(s: str) -> str:
    s = sanitize_text(s)
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


_DASHES = {
    "solid": [],
    "dashed": [6, 3],
    "dotted": [1.5, 2.5],
    "dashdot": [8, 3, 1.5, 3],
}

# Standard-14 base font names this writer will emit.
BASE_FONTS = (
    "Helvetica", "Helvetica-Bold", "Helvetica-Oblique",
    "Times-Roman", "Times-Bold",
    "Courier", "Courier-Bold",
)


def _rgb(color: Tuple[int, int, int]) -> str:
    r, g, b = color
    return f"{r / 255:.3f} {g / 255:.3f} {b / 255:.3f}"


class Canvas:
    """One page's vector content, in PDF points (1/72 inch)."""

    def __init__(self, width_pt: float, height_pt: float):
        self.width_pt = width_pt
        self.height_pt = height_pt
        self.ops: List[bytes] = []
        self._fonts_used: List[str] = []
        self._images_used: List[str] = []

    # -- graphics state -------------------------------------------------
    def set_stroke(self, color: Tuple[int, int, int]) -> None:
        self.ops.append(f"{_rgb(color)} RG\n".encode("latin-1"))

    def set_fill(self, color: Tuple[int, int, int]) -> None:
        self.ops.append(f"{_rgb(color)} rg\n".encode("latin-1"))

    def set_width(self, w_pt: float) -> None:
        self.ops.append(f"{w_pt:.2f} w\n".encode("latin-1"))

    def set_dash(self, linetype: str) -> None:
        pat = _DASHES.get(linetype, [])
        if pat:
            self.ops.append(
                ("[" + " ".join(f"{v:g}" for v in pat) + "] 0 d\n").encode())
        else:
            self.ops.append(b"[] 0 d\n")

    # -- paths -----------------------------------------------------------
    @staticmethod
    def _path(pts: List[Tuple[float, float]]) -> bytes:
        out = [f"{pts[0][0]:.2f} {pts[0][1]:.2f} m\n".encode("latin-1")]
        for x, y in pts[1:]:
            out.append(f"{x:.2f} {y:.2f} l\n".encode("latin-1"))
        return b"".join(out)

    def line(self, x1, y1, x2, y2) -> None:
        self.ops.append(self._path([(x1, y1), (x2, y2)]) + b"S\n")

    def polyline(self, pts, close=False) -> None:
        op = b"h S\n" if close else b"S\n"
        self.ops.append(self._path(pts) + op)

    def polygon(self, pts, fill=True, stroke=True) -> None:
        if fill and stroke:
            op = b"h B\n"
        elif fill:
            op = b"h f\n"
        else:
            op = b"h S\n"
        self.ops.append(self._path(pts) + op)

    def rect(self, x, y, w, h, fill=False, stroke=True) -> None:
        op = f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re\n".encode("latin-1")
        if fill and stroke:
            self.ops.append(op + b"B\n")
        elif fill:
            self.ops.append(op + b"f\n")
        else:
            self.ops.append(op + b"S\n")

    def circle(self, x, y, r, fill=False, stroke=True) -> None:
        # 4 cubic Bezier arcs (kappa approximation).
        k = 0.552284749831 * r
        self.ops.append(
            (f"{x + r:.2f} {y:.2f} m\n"
             f"{x + r:.2f} {y + k:.2f} {x + k:.2f} {y + r:.2f} "
             f"{x:.2f} {y + r:.2f} c\n"
             f"{x - k:.2f} {y + r:.2f} {x - r:.2f} {y + k:.2f} "
             f"{x - r:.2f} {y:.2f} c\n"
             f"{x - r:.2f} {y - k:.2f} {x - k:.2f} {y - r:.2f} "
             f"{x:.2f} {y - r:.2f} c\n"
             f"{x + k:.2f} {y - r:.2f} {x + r:.2f} {y - k:.2f} "
             f"{x + r:.2f} {y:.2f} c\n").encode("latin-1"))
        if fill and stroke:
            self.ops.append(b"B\n")
        elif fill:
            self.ops.append(b"f\n")
        else:
            self.ops.append(b"S\n")

    def hatch_polygon(self, pts, spacing_pt=6.0, angle_deg=45.0) -> None:
        """Fill a polygon with diagonal hatch lines (clipped)."""
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        self.ops.append(b"q\n")
        self.ops.append(self._path(pts) + b"h W n\n")
        th = math.radians(angle_deg)
        dx, dy = math.cos(th), math.sin(th)
        # lines perpendicular offset across the bbox diagonal
        diag = math.hypot(xmax - xmin, ymax - ymin) + spacing_pt
        nx, ny = -dy, dx
        cx, cy = (xmin + xmax) / 2.0, (ymin + ymax) / 2.0
        n = int(diag / spacing_pt) + 2
        for i in range(-n, n + 1):
            ox, oy = cx + nx * i * spacing_pt, cy + ny * i * spacing_pt
            self.ops.append(
                (f"{ox - dx * diag:.2f} {oy - dy * diag:.2f} m\n"
                 f"{ox + dx * diag:.2f} {oy + dy * diag:.2f} l\n"
                 "S\n").encode("latin-1"))
        self.ops.append(b"Q\n")

    # -- text ------------------------------------------------------------
    def _font_tag(self, font: str) -> str:
        if font not in BASE_FONTS:
            raise ValueError(f"unsupported base font {font!r}")
        if font not in self._fonts_used:
            self._fonts_used.append(font)
        return f"/F{BASE_FONTS.index(font) + 1}"

    def text(self, x, y, s, font="Helvetica", size=8.0, align="left") -> None:
        tag = self._font_tag(font)
        s = _esc(s)
        if align in ("center", "right") and font.startswith("Courier"):
            # exact: every WinAnsi char advances 600/1000 em
            adv = len(sanitize_text(s)) * 600 / 1000.0 * size
            if align == "center":
                x -= adv / 2.0
            else:
                x -= adv
        # proportional fonts: left-aligned only (documented limitation)
        self.ops.append(
            (f"BT {tag} {size:.1f} Tf {x:.2f} {y:.2f} Td "
             f"({s}) Tj ET\n").encode("latin-1"))

    # -- images ----------------------------------------------------------
    def image(self, x, y, w_pt, h_pt, img_tag: str) -> None:
        if img_tag not in self._images_used:
            self._images_used.append(img_tag)
        self.ops.append(
            (f"q {w_pt:.2f} 0 0 {h_pt:.2f} {x:.2f} {y:.2f} cm "
             f"{img_tag} Do Q\n").encode("latin-1"))

    def content_bytes(self) -> bytes:
        return b"".join(self.ops)


class PDFDocument:
    """Assembles pages, fonts, and images into a complete PDF file."""

    def __init__(self):
        self._pages: List[Canvas] = []
        self._images: List[Tuple[str, int, int, bytes, str]] = []
        # (tag, w, h, data, kind)  kind: "jpeg-rgb" | "jpeg-gray" |
        # "flate-rgb" | "flate-gray"

    def add_page(self, width_pt: float, height_pt: float) -> Canvas:
        c = Canvas(width_pt, height_pt)
        self._pages.append(c)
        return c

    def add_image(self, data: bytes, w: int, h: int,
                  kind: str) -> str:
        if kind not in ("jpeg-rgb", "jpeg-gray", "flate-rgb", "flate-gray"):
            raise ValueError(f"unknown image kind {kind!r}")
        tag = f"/Im{len(self._images) + 1}"
        self._images.append((tag, w, h, data, kind))
        return tag

    # -- assembly --------------------------------------------------------
    def build(self) -> bytes:
        objs: List[bytes] = []

        def new_obj(body: bytes) -> int:
            objs.append(body)
            return len(objs)  # 1-based object number

        # Object 1: catalog (placeholder, fixed up after pages exist).
        catalog_id = new_obj(b"<< /Type /Catalog /Pages 2 0 R >>")
        assert catalog_id == 1
        # Object 2: pages tree (placeholder).
        pages_id = new_obj(b"<< /Type /Pages /Kids [] /Count 0 >>")
        assert pages_id == 2

        # Fonts: one object per base font used anywhere.
        used_fonts: List[str] = []
        for page in self._pages:
            for f in page._fonts_used:
                if f not in used_fonts:
                    used_fonts.append(f)
        font_ids: Dict[str, int] = {}
        for fname in used_fonts:
            tag = f"/F{BASE_FONTS.index(fname) + 1}"
            fid = new_obj(
                f"<< /Type /Font /Subtype /Type1 /BaseFont /{fname} "
                f"/Encoding /WinAnsiEncoding >>".encode("latin-1"))
            font_ids[tag] = fid

        # Images.
        image_ids: Dict[str, int] = {}
        for tag, w, h, data, kind in self._images:
            if kind.startswith("jpeg"):
                cs = "/DeviceRGB" if kind == "jpeg-rgb" else "/DeviceGray"
                body = (
                    f"<< /Type /XObject /Subtype /Image /Width {w} "
                    f"/Height {h} /ColorSpace {cs} /BitsPerComponent 8 "
                    f"/Filter /DCTDecode /Length {len(data)} >>\n"
                    f"stream\n".encode("latin-1") + data +
                    b"\nendstream")
            else:
                cs = "/DeviceRGB" if kind == "flate-rgb" else "/DeviceGray"
                colors = 3 if kind == "flate-rgb" else 1
                stride = w * colors
                framed = bytearray()
                for row in range(h):
                    framed.append(0)  # predictor: none
                    framed.extend(data[row * stride:(row + 1) * stride])
                comp = zlib.compress(bytes(framed), 6)
                body = (
                    f"<< /Type /XObject /Subtype /Image /Width {w} "
                    f"/Height {h} /ColorSpace {cs} /BitsPerComponent 8 "
                    f"/Filter /FlateDecode /DecodeParms << /Predictor 1 "
                    f"/Colors {colors} /BitsPerComponent 8 /Columns {w} >> "
                    f"/Length {len(comp)} >>\n"
                    f"stream\n".encode("latin-1") + comp +
                    b"\nendstream")
            image_ids[tag] = new_obj(body)

        # Pages + content streams.
        page_ids: List[int] = []
        for page in self._pages:
            content = page.content_bytes()
            content_id = new_obj(
                f"<< /Length {len(content)} >>\nstream\n".encode("latin-1")
                + content + b"\nendstream")
            font_res = " ".join(
                f"{tag} {font_ids[tag]} 0 R" for tag in font_ids)
            xobj_res = " ".join(
                f"{tag} {image_ids[tag]} 0 R"
                for tag in page._images_used if tag in image_ids)
            resources = f"<< /Font << {font_res} >>"
            if xobj_res:
                resources += f" /XObject << {xobj_res} >>"
            resources += " >>"
            pid = new_obj(
                f"<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {page.width_pt:.2f} {page.height_pt:.2f}] "
                f"/Resources {resources} "
                f"/Contents {content_id} 0 R >>".encode("latin-1"))
            page_ids.append(pid)

        # Fix the pages tree now that page ids are known.
        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        objs[1] = (f"<< /Type /Pages /Kids [{kids}] "
                   f"/Count {len(page_ids)} >>").encode("latin-1")

        # Serialize with xref table.
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: List[int] = []
        for i, body in enumerate(objs, start=1):
            offsets.append(len(out))
            out.extend(f"{i} 0 obj\n".encode("latin-1"))
            out.extend(body)
            out.extend(b"\nendobj\n")
        xref_pos = len(out)
        out.extend(f"xref\n0 {len(objs) + 1}\n".encode("latin-1"))
        out.extend(b"0000000000 65535 f \n")
        for off in offsets:
            out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
        out.extend(
            f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF".encode("latin-1"))
        return bytes(out)
