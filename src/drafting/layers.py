"""Layer model for deliverables.

A deliverable is a stack of named layers, each with a visibility
toggle -- the toggle the desktop app (build #5) exposes at print
time. Vector layers carry entities in world metres; the basemap
layer carries a raster source.

Raster contract (build #4 plugs in here): a ``RasterSource`` reports
its world extent in metres (project CRS) and its decoded image bytes.
v1 ships ``WorldFileRaster`` -- a PNG/JPEG plus a world file
(.pgw/.jgw), which is what ODM and DJI Terra export alongside
orthomosaics. Build #4 adds a ``GeoTIFFRaster`` implementing the same
interface; the composer never changes.
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


class LayerError(ValueError):
    """A layer or raster source is malformed."""


@dataclass
class Layer:
    """A named, toggleable drawing layer.

    Entities are plain dicts in world metres:
      {"type": "line", "pts": [(x, y), ...]}
      {"type": "polygon", "pts": [(x, y), ...], "hatch": True/False}
      {"type": "point", "at": (x, y), "label": "101"}
      {"type": "text", "at": (x, y), "text": "...", "style": "label",
       "angle_deg": 0.0}
      {"type": "raster", "source": RasterSource}
    """
    name: str
    visible: bool = True
    entities: List[dict] = field(default_factory=list)

    def add(self, entity: dict) -> "Layer":
        self.entities.append(entity)
        return self


class RasterSource:
    """Interface every basemap raster implements (build #4 extends)."""

    name: str = "raster"

    def extent_world(self) -> Tuple[float, float, float, float]:
        """(xmin, ymin, xmax, ymax) in metres, project CRS."""
        raise NotImplementedError

    def image(self) -> Tuple[bytes, int, int, str]:
        """(image bytes, width_px, height_px, kind).

        kind is "rgb" or "gray" (raw row-major bytes, top row first,
        8 bits/component) or "jpeg-rgb"/"jpeg-gray" (raw JPEG stream).
        """
        raise NotImplementedError


def _read_world_file(path: str) -> Tuple[float, float, float, float,
                                         float, float]:
    """Parse a world file: A D B E C F (pixel size, rotation, origin)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            vals = [float(line.strip()) for line in fh if line.strip()]
    except (OSError, ValueError) as exc:
        raise LayerError(f"{path}: cannot parse world file: {exc}") from exc
    if len(vals) != 6:
        raise LayerError(
            f"{path}: world file needs 6 lines, got {len(vals)}"
        )
    return vals[0], vals[1], vals[2], vals[3], vals[4], vals[5]


def _png_size(path: str) -> Tuple[int, int]:
    with open(path, "rb") as fh:
        sig = fh.read(8)
        if sig != b"\x89PNG\r\n\x1a\n":
            raise LayerError(f"{path}: not a PNG file")
        length = struct.unpack(">I", fh.read(4))[0]
        ctype = fh.read(4)
        if ctype != b"IHDR" or length != 13:
            raise LayerError(f"{path}: malformed PNG IHDR")
        w, h = struct.unpack(">II", fh.read(8))
        return w, h


def _jpeg_size(path: str) -> Tuple[int, int, int]:
    """Return (width, height, components) from the first SOF marker."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:2] != b"\xff\xd8":
        raise LayerError(f"{path}: not a JPEG file")
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):  # SOF
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            ncomp = data[i + 9]
            return w, h, ncomp
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + seg_len
    raise LayerError(f"{path}: could not find JPEG dimensions")


def decode_png(path: str) -> Tuple[bytes, int, int, str]:
    """Decode a PNG to raw RGB/gray bytes (stdlib only).

    Supports non-interlaced, 8-bit, color types 0 (gray), 2 (RGB),
    6 (RGBA -> RGB). Raises LayerError otherwise.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise LayerError(f"{path}: not a PNG file")
    pos = 8
    w = h = bit_depth = color_type = interlace = None
    idat = b""
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            w, h, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", chunk)
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if w is None:
        raise LayerError(f"{path}: PNG missing IHDR")
    if interlace:
        raise LayerError(f"{path}: interlaced PNG not supported")
    if bit_depth != 8 or color_type not in (0, 2, 6):
        raise LayerError(
            f"{path}: unsupported PNG (bit depth {bit_depth}, "
            f"color type {color_type}); need 8-bit gray/RGB/RGBA"
        )
    channels = {0: 1, 2: 3, 6: 4}[color_type]
    stride = w * channels
    raw = zlib.decompress(idat)
    out = bytearray()
    prev = bytearray(stride)
    p = 0
    for _ in range(h):
        f = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        recon = bytearray(stride)
        for i in range(stride):
            a = recon[i - channels] if i >= channels else 0
            b = prev[i]
            c_ = prev[i - channels] if i >= channels else 0
            if f == 0:
                val = line[i]
            elif f == 1:
                val = (line[i] + a) & 0xFF
            elif f == 2:
                val = (line[i] + b) & 0xFF
            elif f == 3:
                val = (line[i] + (a + b) // 2) & 0xFF
            elif f == 4:
                pa, pb, pc = abs(b - c_), abs(a - c_), abs(a + b - 2 * c_)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c_)
                val = (line[i] + pr) & 0xFF
            else:
                raise LayerError(f"{path}: bad PNG filter {f}")
            recon[i] = val
        if channels == 4:
            del recon[3::4]  # drop alpha
            out.extend(recon[:w * 3])
        else:
            out.extend(recon)
        prev = recon
    colorspace = "gray" if channels == 1 else "rgb"
    return bytes(out), w, h, colorspace


class WorldFileRaster(RasterSource):
    """v1 basemap raster: image file + world file.

    ``image_path`` may be .png (decoded with stdlib) or .jpg/.jpeg
    (embedded as-is). ``world_path`` defaults to the image path with
    its extension replaced by .pgw/.jgw.
    """

    def __init__(self, image_path: str, world_path: Optional[str] = None):
        self.image_path = image_path
        if world_path is None:
            base, ext = os.path.splitext(image_path)
            ext = ext.lower()
            wfe = {".png": ".pgw", ".jpg": ".jgw", ".jpeg": ".jgw"}.get(ext)
            if wfe is None:
                raise LayerError(
                    f"{image_path}: cannot infer world file extension "
                    f"for {ext!r}; pass world_path explicitly"
                )
            world_path = base + wfe
        self.world_path = world_path
        self.name = os.path.basename(image_path)
        self._ext = ext.lower()
        if self._ext == ".png":
            self._size = _png_size(image_path) + (3,)
        elif self._ext in (".jpg", ".jpeg"):
            self._size = _jpeg_size(image_path)
        else:
            raise LayerError(
                f"{image_path}: v1 basemap supports .png/.jpg only"
            )
        self._world = _read_world_file(world_path)

    def extent_world(self) -> Tuple[float, float, float, float]:
        a, d, b, e_, c, f = self._world
        w, h = self._size[0], self._size[1]
        # world coords of the four image corners (col, row)
        xs = [c + a * col + b * row for col, row in
              ((0, 0), (w, 0), (0, h), (w, h))]
        ys = [f + d * col + e_ * row for col, row in
              ((0, 0), (w, 0), (0, h), (w, h))]
        return min(xs), min(ys), max(xs), max(ys)

    def image(self) -> Tuple[bytes, int, int, str]:
        w, h = self._size[0], self._size[1]
        if self._ext == ".png":
            return decode_png(self.image_path)
        ncomp = self._size[2]
        kind = "jpeg-rgb" if ncomp == 3 else "jpeg-gray"
        with open(self.image_path, "rb") as fh:
            return fh.read(), w, h, kind


def build_layers(parcel, points_by_name, style,
                 basemap: Optional[RasterSource] = None) -> Dict[str, Layer]:
    """Assemble the standard layer stack for a resolved parcel.

    Returns layers in draw order (bottom first): basemap, boundary,
    easements (empty until build #5), linework, points, control,
    annotations. Callers toggle ``layer.visible`` before composing.
    """
    from .geometry import format_bearing, format_distance

    layers: Dict[str, Layer] = {}
    for lname in ("basemap", "boundary", "easements", "linework",
                  "points", "control", "annotations"):
        layers[lname] = Layer(name=lname)

    if basemap is not None:
        layers["basemap"].add({"type": "raster", "source": basemap})

    # Boundary polygon (chord polygon; curves annotated separately).
    ordered = []
    for i, leg in enumerate(parcel.legs):
        p = points_by_name[leg.frm]
        if i == 0:
            ordered.append((p["x"], p["y"]))
        q = points_by_name[leg.to]
        ordered.append((q["x"], q["y"]))
    layers["boundary"].add({"type": "polygon", "pts": ordered, "hatch": False})

    # Bearing/distance callouts at leg midpoints, offset perpendicular.
    for leg in parcel.legs:
        p, q = points_by_name[leg.frm], points_by_name[leg.to]
        mx, my = (p["x"] + q["x"]) / 2.0, (p["y"] + q["y"]) / 2.0
        import math
        dx, dy = q["x"] - p["x"], q["y"] - p["y"]
        length = math.hypot(dx, dy) or 1.0
        # offset to the left of the leg direction, ~2% of leg length
        off = 0.02 * length + 0.3
        lx, ly = mx - dy / length * off, my + dx / length * off
        if leg.kind == "line":
            text = (f"{leg.tag}  {format_bearing(leg.azimuth_deg)}  "
                    f"{format_distance(leg.distance_m, parcel.units)}")
        else:
            cp = leg.curve
            text = (f"{leg.tag}  R={format_distance(cp.radius_m, parcel.units)} "
                    f"\u0394={cp.delta_deg:.2f}\u00b0")
        layers["annotations"].add(
            {"type": "text", "at": (lx, ly), "text": text, "style": "label"}
        )

    # Points: boundary corners get corner symbols; held stations get the
    # control symbol (a held corner appears on both layers).
    corner_names = {leg.frm for leg in parcel.legs} | \
        {leg.to for leg in parcel.legs}
    for pname, p in points_by_name.items():
        if pname in corner_names:
            layers["points"].add(
                {"type": "point", "at": (p["x"], p["y"]),
                 "label": pname, "symbol": "corner"})
        if p.get("held"):
            layers["control"].add(
                {"type": "point", "at": (p["x"], p["y"]), "label": pname})
        if pname not in corner_names and not p.get("held"):
            layers["points"].add(
                {"type": "point", "at": (p["x"], p["y"]), "label": pname})

    return layers
