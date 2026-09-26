"""PDF writer tests: real structural validation, not file-exists."""

import re

import pytest

from drafting.pdf import PDFDocument, sanitize_text


def _parse_xref(data: bytes):
    """Return {obj_num: offset} from the xref table; verify trailer."""
    assert data.startswith(b"%PDF-1.4")
    m = re.search(rb"startxref\s+(\d+)\s*%%EOF", data)
    assert m, "missing startxref/%%EOF"
    xref_pos = int(m.group(1))
    assert data[xref_pos:xref_pos + 4] == b"xref"
    hdr = re.match(rb"xref\s+0\s+(\d+)\s*\n", data[xref_pos:])
    assert hdr, "bad xref header"
    count = int(hdr.group(1))
    pos = xref_pos + len(hdr.group(0))
    entries = {}
    for i in range(count):
        line = data[pos:pos + 20]
        off = int(line[:10])
        typ = line[17:18]
        if typ == b"n":
            entries[i] = off
        pos += 20
    assert 0 not in entries  # object 0 is the free head
    # every offset must point at "<n> 0 obj"
    for num, off in entries.items():
        head = data[off:off + 20]
        assert head.startswith(f"{num} 0 obj".encode()), \
            f"xref entry {num} -> bad offset {off}: {head!r}"
    # trailer references the catalog
    assert b"/Root 1 0 R" in data
    return entries


def test_minimal_pdf_structure():
    doc = PDFDocument()
    c = doc.add_page(612, 792)
    c.set_stroke((0, 0, 0))
    c.set_width(1.0)
    c.line(10, 10, 100, 100)
    c.text(10, 120, "Hello (world) \\ test", font="Helvetica", size=10)
    data = doc.build()
    entries = _parse_xref(data)
    assert len(entries) >= 4  # catalog, pages, font, page, content
    assert b"(Hello \\(world\\) \\\\ test)" in data  # escaped
    assert b"/BaseFont /Helvetica" in data


def test_polygon_and_hatch_emit_clipping():
    doc = PDFDocument()
    c = doc.add_page(612, 792)
    c.hatch_polygon([(10, 10), (100, 10), (100, 100), (10, 100)])
    data = doc.build()
    _parse_xref(data)
    assert b"W n" in data  # clipping path used


def test_circle_uses_beziers():
    doc = PDFDocument()
    c = doc.add_page(612, 792)
    c.circle(50, 50, 10, fill=False)
    data = doc.build()
    assert data.count(b" c\n") == 4


def test_dash_patterns():
    doc = PDFDocument()
    c = doc.add_page(100, 100)
    c.set_dash("dashed")
    c.line(0, 0, 10, 10)
    c.set_dash("solid")
    c.line(0, 0, 10, 10)
    data = doc.build()
    assert b"[6 3] 0 d" in data
    assert b"[] 0 d" in data


def test_sanitize_text():
    assert sanitize_text("N 45\u00b030'15\" E") == "N 45\u00b030'15\" E"
    assert sanitize_text("a\u0394b") == "aDeltab"
    assert sanitize_text("x\u2603y") == "x?y"  # snowman -> ?


def test_courier_centering_is_exact():
    doc = PDFDocument()
    c = doc.add_page(612, 792)
    c.text(306, 400, "ABCD", font="Courier-Bold", size=10, align="center")
    data = doc.build()
    # 4 chars * 600/1000 * 10pt = 24pt wide -> x = 306 - 12 = 294
    assert b"294.00 400.00 Td" in data


def test_flate_image_round_trip():
    import zlib
    doc = PDFDocument()
    # 2x1 RGB: red, green
    raw = bytes([255, 0, 0, 0, 255, 0])
    tag = doc.add_image(raw, 2, 1, "flate-rgb")
    c = doc.add_page(100, 100)
    c.image(10, 10, 20, 10, tag)
    data = doc.build()
    entries = _parse_xref(data)
    assert b"/Filter /FlateDecode" in data
    assert b"/Predictor 1" in data
    m = re.search(rb"/Length (\d+) >>\s*stream\r?\n", data)
    assert m
    comp = data[m.end():m.end() + int(m.group(1))]
    framed = zlib.decompress(comp)
    # predictor byte 0 + the two pixels
    assert framed == bytes([0, 255, 0, 0, 0, 255, 0])


def test_jpeg_passthrough():
    # minimal 1x1 gray JPEG: SOI, JFIF, DQT, SOF0 (gray 1x1), DHT, SOS, EOI.
    # It only needs to survive byte-identical passthrough, not decode.
    jfif = (b"\xff\xd8"
            b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00\x43\x00" + bytes([8] * 64)
            + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
            + b"\xff\xc4\x00\x1f\x00" + bytes(29)
            + b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\xd2\xcf\x20"
            + b"\xff\xd9")
    doc = PDFDocument()
    tag = doc.add_image(jfif, 1, 1, "jpeg-gray")
    c = doc.add_page(100, 100)
    c.image(0, 0, 10, 10, tag)
    data = doc.build()
    _parse_xref(data)
    assert b"/Filter /DCTDecode" in data
    assert b"/DeviceGray" in data
    assert jfif in data  # passed through byte-identical
