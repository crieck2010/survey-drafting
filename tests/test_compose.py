"""End-to-end tests: synthetic .sadj.json -> plat PDF + manifest."""

import json
import re

import pytest

from drafting.compose import compose_deliverable
from drafting.geometry import ft_to_m
from drafting.legal import generate_legal_description
from drafting.sadj import DraftRefused
from drafting.styles import DEFAULT_STYLE


def _sadj(tmp_path, valid=True):
    pts = []
    E0, N0 = 500000.0, 4500000.0
    corners = {"101": (E0, N0), "102": (E0 + ft_to_m(200), N0),
               "103": (E0 + ft_to_m(200), N0 + ft_to_m(150)),
               "104": (E0, N0 + ft_to_m(150))}
    for name, (e, n) in corners.items():
        pts.append({"name": name, "easting": e, "northing": n,
                    "elevation": 100.0, "sigma_e": 0.012,
                    "sigma_n": 0.011, "sigma_u": 0.020,
                    "source": "rtk-weighted-mean", "held": False,
                    "n_occupations": 2})
    pts.append({"name": "BASE-1", "easting": E0 - 50, "northing": N0 - 50,
                "elevation": 99.5, "sigma_e": 0, "sigma_n": 0, "sigma_u": 0,
                "source": "base", "held": True})
    report = tmp_path / "report.md"
    report.write_text("# Adjustment report\n\nVALID: yes\n")
    doc = {
        "format": "survey-adjust-workflow/adjusted", "schema_version": 1,
        "generator": "survey-adjust-workflow 0.1.0",
        "source_job": {"path": "job.sfield.json", "sha256": "abc"},
        "weights": {"path": "w.json", "sha256": "def"},
        "paths_run": ["rtk"],
        "points": pts,
        "validity": {"valid": valid, "checks": [
            ["Datum defined", True, "held BASE-1"],
            ["Redundancy", valid, "ok" if valid else "dof=0"]]},
        "report": "report.md",
    }
    p = tmp_path / "r.sadj.json"
    p.write_text(json.dumps(doc))
    return str(p)


def _parcel(tmp_path):
    spec = {"format": "survey-drafting/parcel", "schema_version": 1,
            "name": "Lot 7", "units": "ft",
            "segments": [{"from": "101", "to": "102"},
                         {"from": "102", "to": "103"},
                         {"from": "103", "to": "104"},
                         {"from": "104", "to": "101"}]}
    p = tmp_path / "parcel.json"
    p.write_text(json.dumps(spec))
    return str(p)


def _parse_xref(data: bytes):
    m = re.search(rb"startxref\s+(\d+)\s*%%EOF", data)
    xref_pos = int(m.group(1))
    hdr = re.match(rb"xref\s+0\s+(\d+)\s*\n", data[xref_pos:])
    count = int(hdr.group(1))
    pos = xref_pos + len(hdr.group(0))
    for i in range(count):
        off = int(data[pos:pos + 10])
        if data[pos + 17:pos + 18] == b"n":
            head = data[off:off + 16]
            assert head.startswith(f"{i} 0 obj".encode()), (i, off, head)
        pos += 20


def test_compose_plat_pdf(tmp_path):
    sadj = _sadj(tmp_path)
    out = str(tmp_path / "plat.pdf")
    manifest = compose_deliverable(
        sadj, _parcel(tmp_path), DEFAULT_STYLE, out,
        {"kind": "plat", "sheet": "ANSI_C", "scale": "fit",
         "title": "BOUNDARY SURVEY", "location": "Test Town, NY",
         "surveyor": {"name": "C. Rieck", "license_no": "000000",
                      "state": "NY"}})
    data = (tmp_path / "plat.pdf").read_bytes()
    assert data.startswith(b"%PDF-1.4")
    _parse_xref(data)
    # title strip content made it into the page stream
    assert b"BOUNDARY SURVEY" in data
    assert b"PROFESSIONAL LAND SURVEYOR" in data
    assert b"LINE TABLE" in data
    # report appendix embedded as text pages
    assert b"ADJUSTMENT REPORT \\(appendix\\)" in data
    assert b"LEGAL DESCRIPTION \\(appendix\\)" in data
    # manifest
    assert manifest["validity"] is True
    assert manifest["kind"] == "plat"
    assert manifest["inputs"]["report"]["sha256"]
    man_path = str(tmp_path / "plat.manifest.json")
    assert json.loads(open(man_path).read())["outputs"]["pdf"]["bytes"] \
        == len(data)


def test_compose_refuses_invalid(tmp_path):
    sadj = _sadj(tmp_path, valid=False)
    with pytest.raises(DraftRefused, match="Redundancy"):
        compose_deliverable(sadj, _parcel(tmp_path), DEFAULT_STYLE,
                            str(tmp_path / "x.pdf"), {"kind": "plat"})


def test_compose_map_has_no_tables_or_seal(tmp_path):
    sadj = _sadj(tmp_path)
    out = str(tmp_path / "map.pdf")
    compose_deliverable(sadj, _parcel(tmp_path), DEFAULT_STYLE, out,
                        {"kind": "map", "sheet": "ANSI_B"})
    data = (tmp_path / "map.pdf").read_bytes()
    _parse_xref(data)
    assert b"PROFESSIONAL LAND SURVEYOR" not in data
    assert b"LINE TABLE" not in data
    assert b"ADJUSTMENT REPORT \\(appendix\\)" in data  # report always travels


def test_compose_fixed_scale(tmp_path):
    sadj = _sadj(tmp_path)
    out = str(tmp_path / "p.pdf")
    manifest = compose_deliverable(sadj, _parcel(tmp_path), DEFAULT_STYLE,
                                   out, {"kind": "plan", "scale": "50"})
    assert manifest["scale"] == '1" = 50\''
    data = (tmp_path / "p.pdf").read_bytes()
    _parse_xref(data)


def test_hide_layer(tmp_path):
    sadj = _sadj(tmp_path)
    out = str(tmp_path / "p.pdf")
    compose_deliverable(sadj, _parcel(tmp_path), DEFAULT_STYLE, out,
                        {"kind": "plat", "hide": ["annotations"]})
    assert (tmp_path / "p.pdf").exists()
    with pytest.raises(ValueError, match="unknown layer"):
        compose_deliverable(sadj, _parcel(tmp_path), DEFAULT_STYLE, out,
                            {"kind": "plat", "hide": ["nope"]})


def test_legal_description_content(tmp_path):
    from drafting.geometry import load_parcel, resolve_parcel

    class P:
        def __init__(self, x, y):
            self.x, self.y = x, y

    E0, N0 = 500000.0, 4500000.0
    pts = {"101": P(E0, N0), "102": P(E0 + ft_to_m(200), N0),
           "103": P(E0 + ft_to_m(200), N0 + ft_to_m(150)),
           "104": P(E0, N0 + ft_to_m(150))}
    spec = load_parcel(_parcel(tmp_path))
    parcel = resolve_parcel(spec, pts, x_of=lambda p: p.x,
                            y_of=lambda p: p.y)
    text = generate_legal_description(
        parcel,
        header={"designation": "Lot 7",
                "location": "Test Town, NY",
                "basis_of_bearings": "NYSPCS Long Island, NAD83(2011)"},
        point_coords={"101": (E0, N0)})
    assert "BEGINNING at point '101'" in text
    assert "POINT OF BEGINNING" in text
    assert "200.00'" in text  # first leg distance
    assert "Basis of bearings: NYSPCS Long Island, NAD83(2011)." in text
    assert "acres), more or less" in text


def test_cli_smoke(tmp_path, capsys):
    from drafting.cli import main
    sadj = _sadj(tmp_path)
    parcel = _parcel(tmp_path)
    out = str(tmp_path / "cli.pdf")
    rc = main(["plat", "--adjusted", sadj, "--parcel", parcel,
               "--out", out, "--sheet", "ANSI_B",
               "--title", "CLI TEST"])
    assert rc == 0
    assert (tmp_path / "cli.pdf").exists()
    captured = capsys.readouterr()
    assert "wrote" in captured.out


def test_cli_refuses_invalid_exit_code(tmp_path, capsys):
    from drafting.cli import main
    sadj = _sadj(tmp_path, valid=False)
    rc = main(["plat", "--adjusted", sadj, "--parcel", _parcel(tmp_path),
               "--out", str(tmp_path / "x.pdf")])
    assert rc == 3
    assert "Refusing to draft" in capsys.readouterr().err


# --- v0.1.2 regression: elevation-only points don't break composition ---
def test_compose_skips_elevation_only_points(tmp_path):
    import json
    from drafting import compose
    from drafting.styles import DEFAULT_STYLE
    sadj = {
        "format": "survey-adjust-workflow/adjusted",
        "schema_version": 1,
        "source_job": {"path": "job.sfield.json", "sha256": "x"},
        "weights": {"path": None, "sha256": None, "config_sha256": "y"},
        "package_versions": {},
        "paths_run": ["rtk", "levels"],
        "points": [
            {"name": "A", "easting": 100.0, "northing": 200.0,
             "elevation": 10.0, "sigma_e": 0.01, "sigma_n": 0.01,
             "sigma_u": 0.02, "source": "rtk-weighted-mean+level-net"},
            {"name": "B", "easting": 130.0, "northing": 200.0,
             "elevation": 10.1, "sigma_e": 0.01, "sigma_n": 0.01,
             "sigma_u": 0.02, "source": "rtk-weighted-mean+level-net"},
            {"name": "BASE1", "easting": None, "northing": None,
             "elevation": 12.0, "sigma_e": None, "sigma_n": None,
             "sigma_u": 0.0, "source": "level-net", "held": True},
        ],
        "validity": {"valid": True,
                     "checks": [["c", True, "d"]]},
        "report": "report.md",
        "notes": [],
    }
    sp = tmp_path / "a.sadj.json"
    sp.write_text(json.dumps(sadj))
    parcel = {"format": "survey-drafting/parcel", "schema_version": 1,
              "units": "ft", "boundary_order": ["A", "B"],
              "segments": [{"from": "A", "to": "B", "kind": "line"},
                           {"from": "B", "to": "A", "kind": "line"}]}
    pp = tmp_path / "p.parcel.json"
    pp.write_text(json.dumps(parcel))
    (tmp_path / "report.md").write_text("# report\n")
    out = tmp_path / "plat.pdf"
    manifest = compose.compose_deliverable(str(sp), str(pp),
                                           DEFAULT_STYLE, str(out),
                                           options={"kind": "plat"})
    assert out.exists() and manifest["validity"] is True
