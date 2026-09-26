"""Geometry tests: hand-checked numbers, no mocks."""

import math

import pytest

from drafting.geometry import (
    M_PER_FT, format_bearing, format_distance, ft_to_m, load_parcel,
    m_to_ft, resolve_parcel, ParcelError,
)


class P:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def _square_parcel(units="ft"):
    # 100 ft square, clockwise: (0,0) -> (100,0) -> (100,100) -> (0,100)
    pts = {
        "A": P(0.0, 0.0),
        "B": P(ft_to_m(100.0), 0.0),
        "C": P(ft_to_m(100.0), ft_to_m(100.0)),
        "D": P(0.0, ft_to_m(100.0)),
    }
    spec = {
        "format": "survey-drafting/parcel", "schema_version": 1,
        "name": "Square", "units": units,
        "segments": [
            {"from": "A", "to": "B"},
            {"from": "B", "to": "C"},
            {"from": "C", "to": "D"},
            {"from": "D", "to": "A"},
        ],
    }
    return resolve_parcel(spec, pts, x_of=lambda p: p.x, y_of=lambda p: p.y)


def test_square_area_and_perimeter():
    r = _square_parcel()
    assert r.closed
    assert r.misclosure_m == 0.0
    # 100ft x 100ft = 10,000 sq ft; shoelace in metres converts back
    assert abs(r.area_m2 / M_PER_FT ** 2 - 10_000.0) < 0.01
    assert abs(r.perimeter_m / M_PER_FT - 400.0) < 0.01
    assert "0.2296 acres" in r.area_label()  # 10000/43560


def test_leg_bearings_distances():
    r = _square_parcel()
    tags = {l.tag: l for l in r.legs}
    # A->B heads east: azimuth 90
    assert abs(tags["L1"].azimuth_deg - 90.0) < 1e-9
    assert abs(tags["L1"].distance_m - ft_to_m(100.0)) < 1e-9
    # B->C heads north: azimuth 0
    assert abs(tags["L2"].azimuth_deg - 0.0) < 1e-9


def test_format_bearing():
    assert format_bearing(45.0) == "N 45\u00b000'00\" E"
    assert format_bearing(0.0) == "N 0\u00b000'00\" E"
    assert format_bearing(90.0) == "N 90\u00b000'00\" E"
    assert format_bearing(180.0) == "S 0\u00b000'00\" W"
    assert format_bearing(270.0) == "N 90\u00b000'00\" W"
    # 123.456789 deg = 123d 27m 24.44s -> rounds to 24s
    assert format_bearing(123.456789) == "S 56\u00b032'36\" E"


def test_format_distance():
    assert format_distance(ft_to_m(123.456), "ft") == "123.46'"
    assert format_distance(12.345678, "m") == "12.346 m"


def test_curve_params_hand_calc():
    # R=100ft, delta=90deg, chord endpoints consistent: chord = 100*sqrt(2)
    chord = 100.0 * math.sqrt(2.0)
    pts = {"A": P(0.0, 0.0), "B": P(ft_to_m(chord), 0.0)}
    spec = {
        "format": "survey-drafting/parcel", "schema_version": 1,
        "name": "Curve", "units": "ft",
        "segments": [
            {"from": "A", "to": "B",
             "curve": {"radius": 100.0, "delta_deg": 90.0, "turn": "right"}},
            {"from": "B", "to": "A"},
        ],
    }
    r = resolve_parcel(spec, pts, x_of=lambda p: p.x, y_of=lambda p: p.y)
    leg = r.legs[0]
    assert leg.kind == "curve"
    cp = leg.curve
    assert abs(m_to_ft(cp.arc_m) - 100.0 * math.pi / 2) < 1e-9
    assert abs(m_to_ft(cp.tangent_m) - 100.0) < 1e-9
    assert cp.turn == "right"


def test_curve_inconsistency_rejected():
    pts = {"A": P(0.0, 0.0), "B": P(ft_to_m(50.0), 0.0)}  # chord 50
    spec = {
        "format": "survey-drafting/parcel", "schema_version": 1,
        "name": "Bad", "units": "ft",
        "segments": [
            {"from": "A", "to": "B",
             "curve": {"radius": 100.0, "delta_deg": 90.0, "turn": "left"}},
        ],
    }
    with pytest.raises(ParcelError, match="inconsistent"):
        resolve_parcel(spec, pts, x_of=lambda p: p.x, y_of=lambda p: p.y)


def test_open_parcel_misclosure():
    pts = {"A": P(0.0, 0.0), "B": P(ft_to_m(100.0), 0.0),
           "C": P(ft_to_m(100.0), ft_to_m(50.0))}
    spec = {
        "format": "survey-drafting/parcel", "schema_version": 1,
        "name": "Open", "units": "ft",
        "segments": [{"from": "A", "to": "B"}, {"from": "B", "to": "C"}],
    }
    r = resolve_parcel(spec, pts, x_of=lambda p: p.x, y_of=lambda p: p.y)
    assert not r.closed
    assert abs(m_to_ft(r.misclosure_m) - math.hypot(100.0, 50.0)) < 0.01


def test_unknown_point_rejected():
    pts = {"A": P(0.0, 0.0)}
    spec = {
        "format": "survey-drafting/parcel", "schema_version": 1,
        "name": "Bad", "units": "ft",
        "segments": [{"from": "A", "to": "ZZZ"}],
    }
    with pytest.raises(ParcelError, match="unknown point"):
        resolve_parcel(spec, pts, x_of=lambda p: p.x, y_of=lambda p: p.y)


def test_load_parcel_schema(tmp_path):
    bad = tmp_path / "p.json"
    bad.write_text('{"format": "nope", "schema_version": 1}')
    with pytest.raises(ParcelError, match="expected format"):
        load_parcel(str(bad))
    new = tmp_path / "p2.json"
    new.write_text('{"format": "survey-drafting/parcel", '
                   '"schema_version": 99, "segments": []}')
    with pytest.raises(ParcelError, match="newer than supported"):
        load_parcel(str(new))
