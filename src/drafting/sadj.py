"""Read and gate the survey-adjust-workflow adjusted-products contract.

The ``.sadj.json`` file (format ``survey-adjust-workflow/adjusted``,
schema v1) is the single source of truth this package drafts from:
adjusted coordinates, one-sigma uncertainties, per-point source, the
validity verdict, and the path to the justification report.

Validity gate: :func:`check_validity` refuses to draft when
``validity.valid`` is false, raising :class:`DraftRefused` naming every
failed criterion. The CLI turns that into a non-zero exit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

FORMAT = "survey-adjust-workflow/adjusted"
SCHEMA_VERSION = 1


class SadjError(ValueError):
    """The .sadj.json file is malformed or from an unsupported version."""


class DraftRefused(Exception):
    """Raised when the adjustment is not valid -- drafting is refused.

    Carries the failed validity checks so the caller (CLI or app) can
    tell the user exactly which criterion failed.
    """

    def __init__(self, failed: List[Tuple[str, str]]):
        self.failed = failed
        lines = "\n".join(f"  - {name}: {detail}" for name, detail in failed)
        super().__init__(
            "Refusing to draft: the adjustment is not VALID.\n"
            f"Failed criteria:\n{lines}"
        )


@dataclass
class SadjPoint:
    name: str
    easting: Optional[float]      # metres, project CRS; None where the path
    northing: Optional[float]     # doesn't estimate it (level net -> no E/N)
    elevation: Optional[float]
    sigma_e: Optional[float]      # one-sigma, metres
    sigma_n: Optional[float]
    sigma_u: Optional[float]
    source: str                   # rtk-weighted-mean | level-net | traverse
    held: bool = False
    n_occupations: Optional[int] = None


@dataclass
class SadjDoc:
    path: str
    generator: str
    source_job: Dict[str, Any]
    weights: Dict[str, Any]
    paths_run: List[str]
    points: List[SadjPoint]
    validity: Dict[str, Any]
    report: Optional[str]
    notes: List[str] = field(default_factory=list)

    def by_name(self) -> Dict[str, SadjPoint]:
        return {p.name: p for p in self.points}


def _req(obj: Dict[str, Any], key: str, where: str) -> Any:
    if key not in obj:
        raise SadjError(f"{where}: missing required key {key!r}")
    return obj[key]


def read_sadj(path: str) -> SadjDoc:
    """Read and validate a .sadj.json contract file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise SadjError(f"{path}: cannot read as JSON: {exc}") from exc

    if not isinstance(raw, dict):
        raise SadjError(f"{path}: top level must be a JSON object")
    if raw.get("format") != FORMAT:
        raise SadjError(
            f"{path}: expected format {FORMAT!r}, "
            f"got {raw.get('format')!r}"
        )
    version = raw.get("schema_version")
    if not isinstance(version, int):
        raise SadjError(f"{path}: schema_version must be an integer")
    if version > SCHEMA_VERSION:
        raise SadjError(
            f"{path}: schema_version {version} is newer than this "
            f"reader supports ({SCHEMA_VERSION}); upgrade survey-drafting"
        )

    points: List[SadjPoint] = []
    for i, p in enumerate(_req(raw, "points", path)):
        where = f"{path}: points[{i}]"
        points.append(
            SadjPoint(
                name=str(_req(p, "name", where)),
                easting=p.get("easting"),
                northing=p.get("northing"),
                elevation=p.get("elevation"),
                sigma_e=p.get("sigma_e"),
                sigma_n=p.get("sigma_n"),
                sigma_u=p.get("sigma_u"),
                source=str(p.get("source", "unknown")),
                held=bool(p.get("held", False)),
                n_occupations=p.get("n_occupations"),
            )
        )

    return SadjDoc(
        path=path,
        generator=str(raw.get("generator", "unknown")),
        source_job=raw.get("source_job", {}),
        weights=raw.get("weights", {}),
        paths_run=list(raw.get("paths_run", [])),
        points=points,
        validity=raw.get("validity", {}),
        report=raw.get("report"),
        notes=list(raw.get("notes", [])),
    )


def validity_failures(doc: SadjDoc) -> List[Tuple[str, str]]:
    """Return [(criterion, detail)] for every failed validity check."""
    failed: List[Tuple[str, str]] = []
    validity = doc.validity
    if not validity:
        return [("validity block present", "no validity block in .sadj.json")]
    if validity.get("valid") is True:
        return []
    checks = validity.get("checks", [])
    if not checks:
        return [("validity.valid", "valid is not true and no checks listed")]
    for check in checks:
        # checks are [name, passed, detail] per the build #2 contract
        try:
            name, passed = check[0], check[1]
            detail = check[2] if len(check) > 2 else ""
        except (TypeError, IndexError):
            failed.append(("malformed check entry", repr(check)))
            continue
        if not passed:
            failed.append((str(name), str(detail)))
    if not failed:
        # valid flag false but every listed check passed: still refuse,
        # loudly, rather than guess.
        failed.append(
            ("validity.valid", "valid is false with no failing check named")
        )
    return failed


def check_validity(doc: SadjDoc) -> None:
    """Enforce the validity gate. Raises DraftRefused when not valid."""
    failed = validity_failures(doc)
    if failed:
        raise DraftRefused(failed)
