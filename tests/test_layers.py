"""Layer tests: world files, PNG decoding, layer stack assembly."""

import struct
import zlib

import pytest

from drafting.layers import (
    Layer, LayerError, WorldFileRaster, build_layers, decode_png,
)


def _make_png(path, w=4, h=3):
    """Write a small RGB PNG with a distinctive pattern (filter 1)."""
    def chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + \
            struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    stride = w * 3
    raw = bytearray()
    prev = [10, 20, 30]
    for row in range(h):
        raw.append(1)  # Sub filter
        for col in range(w):
            px = [(row * 40 + col * 17 + k) % 256 for k in range(3)]
            for k in range(3):
                a = prev[k] if col > 0 else 0
                raw.append((px[k] - a) & 0xFF)
            prev = px
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw)))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


def test_decode_png_round_trip(tmp_path):
    p = tmp_path / "t.png"
    _make_png(p)
    data, w, h, cs = decode_png(str(p))
    assert (w, h, cs) == (4, 3, "rgb")
    assert len(data) == 4 * 3 * 3
    # first pixel of first row: row=0,col=0 -> (0+0+k)%256
    assert data[0:3] == bytes([0, 1, 2])
    # second pixel: (0+17+k) % 256
    assert data[3:6] == bytes([17, 18, 19])


def test_decode_png_rejects_interlaced(tmp_path):
    p = tmp_path / "t.png"
    _make_png(p)
    raw = bytearray(p.read_bytes())
    raw[28] = 1  # IHDR interlace byte offset: 8 sig + 8 chunk hdr + 12 = 28
    p.write_bytes(bytes(raw))
    with pytest.raises(LayerError, match="interlaced"):
        decode_png(str(p))


def _make_world_raster(tmp_path):
    img = tmp_path / "ortho.png"
    _make_png(img, w=100, h=50)
    # 0.5 m pixels, origin upper-left at (500000, 4500000)
    (tmp_path / "ortho.pgw").write_text("0.5\n0\n0\n-0.5\n500000\n4500000\n")
    return str(img)


def test_world_file_extent(tmp_path):
    r = WorldFileRaster(_make_world_raster(tmp_path))
    xmin, ymin, xmax, ymax = r.extent_world()
    assert (xmin, ymin, xmax, ymax) == (500000.0, 4500000.0 - 25.0,
                                       500050.0, 4500000.0)


def test_world_file_bad_count(tmp_path):
    img = tmp_path / "x.png"
    _make_png(img)
    (tmp_path / "x.pgw").write_text("0.5\n0\n")
    with pytest.raises(LayerError, match="6 lines"):
        WorldFileRaster(str(img))


def test_build_layers_stack():
    from drafting.geometry import resolve_parcel, ft_to_m

    class P:
        def __init__(self, x, y):
            self.x, self.y = x, y

    pts = {"A": P(0, 0), "B": P(ft_to_m(100), 0), "C": P(ft_to_m(100), ft_to_m(100))}
    spec = {"format": "survey-drafting/parcel", "schema_version": 1,
            "name": "T", "units": "ft",
            "segments": [{"from": "A", "to": "B"}, {"from": "B", "to": "C"},
                         {"from": "C", "to": "A"}]}
    parcel = resolve_parcel(spec, pts, x_of=lambda p: p.x, y_of=lambda p: p.y)
    by_name = {"A": {"x": 0, "y": 0, "held": True},
               "B": {"x": ft_to_m(100), "y": 0, "held": False},
               "C": {"x": ft_to_m(100), "y": ft_to_m(100), "held": False}}
    layers = build_layers(parcel, by_name, style=None)
    assert list(layers) == ["basemap", "boundary", "easements", "linework",
                            "points", "control", "annotations"]
    # boundary polygon present; 3 annotation callouts; A held -> control
    assert any(e["type"] == "polygon"
               for e in layers["boundary"].entities)
    assert len(layers["annotations"].entities) == 3
    assert len(layers["control"].entities) == 1
    assert len(layers["points"].entities) == 3  # A,B,C corners
    # visibility toggle exists
    layers["annotations"].visible = False
    assert not layers["annotations"].visible
