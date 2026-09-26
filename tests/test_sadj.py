"""Validity-gate tests: the gate must refuse loudly and precisely."""

import json

import pytest

from drafting.sadj import (
    DraftRefused, SadjError, check_validity, read_sadj, validity_failures,
)


def _doc(tmp_path, **kw):
    base = {
        "format": "survey-adjust-workflow/adjusted",
        "schema_version": 1,
        "generator": "survey-adjust-workflow 0.1.0",
        "source_job": {}, "weights": {},
        "paths_run": ["rtk"],
        "points": [
            {"name": "101", "easting": 500000.0, "northing": 4500000.0,
             "elevation": 100.0, "sigma_e": 0.01, "sigma_n": 0.01,
             "sigma_u": 0.02, "source": "rtk-weighted-mean",
             "held": False, "n_occupations": 3},
        ],
        "validity": {"valid": True,
                     "checks": [["Datum defined", True, "held BASE-1"]]},
        "report": "report.md",
    }
    base.update(kw)
    p = tmp_path / "r.sadj.json"
    p.write_text(json.dumps(base))
    return str(p)


def test_valid_passes(tmp_path):
    doc = read_sadj(_doc(tmp_path))
    check_validity(doc)  # must not raise
    assert doc.by_name()["101"].easting == 500000.0


def test_invalid_refused_with_criteria(tmp_path):
    path = _doc(tmp_path, validity={
        "valid": False,
        "checks": [["Datum defined", True, "held BASE-1"],
                   ["Redundancy", False, "dof=0, need >= 1"],
                   ["Model validated", False, "chi2 failed"]],
    })
    doc = read_sadj(path)
    failed = validity_failures(doc)
    assert [f[0] for f in failed] == ["Redundancy", "Model validated"]
    with pytest.raises(DraftRefused) as ei:
        check_validity(doc)
    assert "Redundancy" in str(ei.value)
    assert "dof=0" in str(ei.value)


def test_missing_validity_block_refused(tmp_path):
    doc = read_sadj(_doc(tmp_path, validity={}))
    with pytest.raises(DraftRefused, match="validity block"):
        check_validity(doc)


def test_newer_schema_rejected(tmp_path):
    with pytest.raises(SadjError, match="newer than this reader"):
        read_sadj(_doc(tmp_path, schema_version=99))


def test_wrong_format_rejected(tmp_path):
    with pytest.raises(SadjError, match="expected format"):
        read_sadj(_doc(tmp_path, format="something/else"))


def test_not_json_rejected(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json{")
    with pytest.raises(SadjError, match="cannot read as JSON"):
        read_sadj(str(p))
