"""Style sheet tests: defaults work, bad input fails loud."""

import json

import pytest

from drafting.styles import (
    DEFAULT_STYLE, StyleError, load_style, style_template,
)


def test_default_style_sane():
    for lname in ("control", "boundary", "linework", "points",
                  "annotations", "easements", "basemap"):
        st = DEFAULT_STYLE.layer(lname)
        st.validate(f"default:{lname}")
    assert DEFAULT_STYLE.text_style("label").size_pt == 7.0


def test_template_round_trips(tmp_path):
    p = tmp_path / "style.json"
    p.write_text(json.dumps(style_template()))
    st = load_style(str(p))
    assert st.layer("boundary").width_pt == 1.75
    assert st.layer("boundary").color == (0, 0, 0)
    assert st.layer("control").symbol == "triangle"


def _write(tmp_path, obj):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(obj))
    return str(p)


def _base():
    return dict(style_template())


def test_bad_color_rejected(tmp_path):
    d = _base()
    d["layers"]["boundary"]["color"] = [300, 0, 0]
    with pytest.raises(StyleError, match="color"):
        load_style(_write(tmp_path, d))


def test_bad_linetype_rejected(tmp_path):
    d = _base()
    d["layers"]["boundary"]["linetype"] = "zigzag"
    with pytest.raises(StyleError, match="linetype"):
        load_style(_write(tmp_path, d))


def test_bad_symbol_rejected(tmp_path):
    d = _base()
    d["layers"]["points"]["symbol"] = "star"
    with pytest.raises(StyleError, match="symbol"):
        load_style(_write(tmp_path, d))


def test_bad_font_rejected(tmp_path):
    d = _base()
    d["text"]["label"]["font"] = "Comic Sans"
    with pytest.raises(StyleError, match="font"):
        load_style(_write(tmp_path, d))


def test_newer_schema_rejected(tmp_path):
    d = _base()
    d["schema_version"] = 99
    with pytest.raises(StyleError, match="newer than supported"):
        load_style(_write(tmp_path, d))


def test_unknown_layer_falls_back():
    assert DEFAULT_STYLE.layer("nope").width_pt == 0.75
